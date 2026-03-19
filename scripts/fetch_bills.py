"""
fetch_bills.py
Polls the Congress.gov API for bills that have cleared committee and
queues them for processing if they are new or have been updated.

Includes smart update filtering to skip unchanged bills and API enrichment
to fetch subjects, summaries, titles, and cosponsor data.

Usage:
    python scripts/fetch_bills.py           # Normal run
    python scripts/fetch_bills.py --dry-run # Print what would be queued, no writes
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
from utils import hash_text, bill_folder_name

API_KEY = os.environ.get("CONGRESS_API_KEY", "")
BASE_URL = "https://api.congress.gov/v3"
DATA_DIR = Path(__file__).parent.parent / "data" / "bills"

# Bill stages that indicate the bill has cleared committee.
COMMITTEE_CLEARED_ACTIONS = [
    "Reported by",
    "Ordered to be Reported",
    "Reported (Amended)",
    "Committee on",
]

PAGE_SIZE = 50
TARGET_CONGRESS = 119


def fetch_json(url: str, params: dict) -> dict:
    """Make a GET request to the Congress.gov API with rate-limit handling."""
    params["api_key"] = API_KEY
    params["format"] = "json"
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                print("Rate limited. Waiting 10 seconds...")
                time.sleep(10)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            print(f"Request failed ({e}), retrying...")
            time.sleep(3)
    return {}


def get_bills_list(congress: int, offset: int = 0) -> list[dict]:
    """Fetch a page of bills from the given Congress."""
    url = f"{BASE_URL}/bill/{congress}"
    params = {
        "limit": PAGE_SIZE,
        "offset": offset,
        "sort": "updateDate+desc",
    }
    data = fetch_json(url, params)
    return data.get("bills", [])


def get_bill_detail(congress: int, bill_type: str, bill_number: str) -> dict:
    """Fetch detailed bill info including sponsor."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type.lower()}/{bill_number}"
    data = fetch_json(url, {})
    return data.get("bill", {})


def get_bill_actions(congress: int, bill_type: str, bill_number: str) -> list[dict]:
    """Fetch the action history for a specific bill."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type.lower()}/{bill_number}/actions"
    data = fetch_json(url, {"limit": 50})
    return data.get("actions", [])


def get_bill_subjects(congress: int, bill_type: str, bill_number: str) -> dict:
    """Fetch legislative subjects and policy area for a bill."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type.lower()}/{bill_number}/subjects"
    data = fetch_json(url, {"limit": 100})

    subjects = []
    policy_area = ""

    # Handle nested structure - subjects can be under "subjects" key
    subjects_data = data.get("subjects", data)

    # Extract legislative subjects
    leg_subjects = subjects_data.get("legislativeSubjects", [])
    for item in leg_subjects:
        if isinstance(item, dict) and "name" in item:
            subjects.append(item["name"])
        elif isinstance(item, str):
            subjects.append(item)

    # Extract policy area
    pa = subjects_data.get("policyArea", {})
    if isinstance(pa, dict):
        policy_area = pa.get("name", "")
    elif isinstance(pa, str):
        policy_area = pa

    return {"subjects": subjects, "policy_area": policy_area}


def get_bill_summaries(congress: int, bill_type: str, bill_number: str) -> str:
    """Fetch the most recent CRS summary for a bill."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type.lower()}/{bill_number}/summaries"
    data = fetch_json(url, {"limit": 10})

    summaries = data.get("summaries", [])
    if not summaries:
        return ""

    # Take the most recent summary
    latest = summaries[0]
    text = latest.get("text", "")

    # Strip HTML tags if present
    if text and "<" in text:
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

    return text


def get_bill_titles(congress: int, bill_type: str, bill_number: str) -> dict:
    """Fetch all titles for a bill, including short title if available."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type.lower()}/{bill_number}/titles"
    data = fetch_json(url, {"limit": 50})

    titles = data.get("titles", [])
    short_title = ""
    official_title = ""

    for item in titles:
        title_type = item.get("titleType", "").lower()
        title_text = item.get("title", "")

        if "short" in title_type and not short_title:
            short_title = title_text
        elif ("official" in title_type or "display" in title_type) and not official_title:
            official_title = title_text

    return {"short_title": short_title, "official_title": official_title}


def get_bill_cosponsors_count(congress: int, bill_type: str, bill_number: str) -> int:
    """Fetch the cosponsor count for a bill (not individual names)."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type.lower()}/{bill_number}/cosponsors"
    data = fetch_json(url, {"limit": 1})
    pagination = data.get("pagination", {})
    return pagination.get("count", 0)


def get_bill_text_url(congress: int, bill_type: str, bill_number: str) -> str | None:
    """Fetch the URL of the most recent plain-text version of a bill."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type.lower()}/{bill_number}/text"
    data = fetch_json(url, {"limit": 10})
    versions = data.get("textVersions", [])
    if not versions:
        return None

    latest = versions[0]
    formats = latest.get("formats", [])

    for fmt in formats:
        if fmt.get("type", "").upper() == "Formatted Text":
            return fmt.get("url")
    for fmt in formats:
        if fmt.get("type", "").upper() in ("XML", "Formatted XML"):
            return fmt.get("url")
    return None


def bill_has_cleared_committee(actions: list[dict]) -> tuple[bool, str]:
    """Check whether any action indicates committee clearance."""
    for action in actions:
        text = action.get("text", "")
        for keyword in COMMITTEE_CLEARED_ACTIONS:
            if keyword.lower() in text.lower():
                return True, text[:120]
    return False, ""


def load_existing_meta(folder: Path) -> dict:
    """Load existing meta.json for a bill, or return empty dict."""
    meta_path = folder / "meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            return json.load(f)
    return {}


def save_meta(folder: Path, meta: dict):
    """Write meta.json for a bill."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)


def queue_bill_for_processing(folder: Path):
    """Write a needs_processing flag file."""
    (folder / "needs_processing").touch()


def run(dry_run: bool = False):
    if not API_KEY:
        print("ERROR: CONGRESS_API_KEY environment variable not set.")
        sys.exit(1)

    print(f"Fetching bills for Congress {TARGET_CONGRESS}...")
    queued = 0
    skipped_unchanged = 0
    skipped_no_committee = 0
    skipped_no_text = 0
    offset = 0
    max_pages = 20

    for page in range(max_pages):
        bills = get_bills_list(TARGET_CONGRESS, offset)
        if not bills:
            break

        for bill in bills:
            congress = bill.get("congress")
            bill_type = bill.get("type", "").lower()
            number = str(bill.get("number", ""))
            title = bill.get("title", "Untitled")
            update_date = bill.get("updateDate", "")

            folder_name = bill_folder_name(congress, bill_type, number)
            folder = DATA_DIR / folder_name
            existing_meta = load_existing_meta(folder)

            # SMART UPDATE FILTERING: Skip if unchanged and already processed
            if (existing_meta.get("update_date") == update_date and
                existing_meta.get("simplified_complete")):
                skipped_unchanged += 1
                continue

            # Check if this bill has actually cleared committee
            print(f"  Checking actions for {bill_type.upper()}.{number}: {title[:50]}...")
            actions = get_bill_actions(congress, bill_type, number)
            cleared, stage_label = bill_has_cleared_committee(actions)

            if not cleared:
                skipped_no_committee += 1
                continue

            # Get the text URL
            text_url = get_bill_text_url(congress, bill_type, number)
            if not text_url:
                print(f"    No text available yet, skipping.")
                skipped_no_text += 1
                continue

            # ENRICHMENT: Fetch additional data from Congress.gov API
            print(f"    Fetching enrichment data...")

            # Get bill detail for sponsor info
            detail = get_bill_detail(congress, bill_type, number)
            sponsors = detail.get("sponsors", [])
            sponsor = sponsors[0] if sponsors else {}
            introduced_date = detail.get("introducedDate", "")
            time.sleep(0.3)

            # Get subjects and policy area
            subject_data = get_bill_subjects(congress, bill_type, number)
            time.sleep(0.3)

            # Get CRS summary
            crs_summary = get_bill_summaries(congress, bill_type, number)
            time.sleep(0.3)

            # Get titles including short title
            title_data = get_bill_titles(congress, bill_type, number)
            time.sleep(0.3)

            # Get cosponsor count
            cosponsor_count = get_bill_cosponsors_count(congress, bill_type, number)
            time.sleep(0.3)

            # Build sponsor name from available fields
            sponsor_name = sponsor.get("fullName", "")
            if not sponsor_name:
                first = sponsor.get("firstName", "")
                last = sponsor.get("lastName", "")
                sponsor_name = f"{first} {last}".strip()

            print(f"  QUEUED: {bill_type.upper()}.{number} - {title[:50]}")
            print(f"    Stage: {stage_label[:60]}")
            if subject_data["policy_area"]:
                print(f"    Policy Area: {subject_data['policy_area']}")

            if not dry_run:
                folder.mkdir(parents=True, exist_ok=True)
                meta = {
                    "bill_id": folder_name,
                    "congress": congress,
                    "bill_type": bill_type,
                    "bill_number": number,
                    "title": title,
                    "short_title": title_data.get("short_title", ""),
                    "introduced_date": introduced_date,
                    "update_date": update_date,
                    "stage_label": stage_label,
                    "text_url": text_url,
                    # Sponsor info
                    "sponsor_name": sponsor_name,
                    "sponsor_party": sponsor.get("party", ""),
                    "sponsor_state": sponsor.get("state", ""),
                    # Enrichment data
                    "policy_area": subject_data.get("policy_area", ""),
                    "subjects": subject_data.get("subjects", []),
                    "crs_summary": crs_summary,
                    "cosponsor_count": cosponsor_count,
                    # Processing state
                    "simplified_complete": False,
                    "queued_at": datetime.now(timezone.utc).isoformat(),
                }
                save_meta(folder, meta)
                queue_bill_for_processing(folder)

            queued += 1
            time.sleep(0.5)

        offset += PAGE_SIZE
        if len(bills) < PAGE_SIZE:
            break
        time.sleep(1)

    print(f"\nDone.")
    print(f"  Queued: {queued}")
    print(f"  Skipped (unchanged): {skipped_unchanged}")
    print(f"  Skipped (no committee action): {skipped_no_committee}")
    print(f"  Skipped (no text): {skipped_no_text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be queued without writing files")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
