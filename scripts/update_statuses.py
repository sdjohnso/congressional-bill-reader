"""
update_statuses.py
Refreshes the legislative status of all existing bills by querying the
Congress.gov Actions API. Updates meta.json, simplified.json, and the
site copy without re-running Claude simplification.

Runs as part of the twice-daily pipeline to keep statuses current.

Usage:
    python scripts/update_statuses.py            # Update all bills
    python scripts/update_statuses.py --dry-run   # Show what would change
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
from utils import derive_bill_status

API_KEY = os.environ.get("CONGRESS_API_KEY", "")
BASE_URL = "https://api.congress.gov/v3"
DATA_DIR = Path(__file__).parent.parent / "data" / "bills"
SITE_DIR = Path(__file__).parent.parent / "site" / "src" / "bills"

# Status labels for display (matches frontend formatStatus)
STATUS_LABELS = {
    "introduced": "Introduced",
    "referred_to_committee": "In Committee",
    "committee_reported": "Passed Committee",
    "passed_house": "Passed House",
    "passed_senate": "Passed Senate",
    "resolving_differences": "In Conference",
    "to_president": "To President",
    "signed_into_law": "Signed Into Law",
    "vetoed": "Vetoed",
}


def fetch_actions(congress: int, bill_type: str, bill_number: str) -> list[dict]:
    """Fetch all actions for a bill from Congress.gov API."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type}/{bill_number}/actions"
    params = {"api_key": API_KEY, "format": "json", "limit": 250}

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            return data.get("actions", [])
        except requests.RequestException as e:
            if attempt == 2:
                print(f"  Failed after 3 attempts: {e}")
                return []
            time.sleep(2)
    return []


def load_json(path: Path) -> dict | None:
    """Load a JSON file, return None if missing."""
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    """Write JSON with consistent formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_bill_status(bill_dir: Path, dry_run: bool = False) -> dict | None:
    """
    Fetch fresh actions for a bill and update status fields in
    meta.json and simplified.json. Returns change summary or None.
    """
    meta_path = bill_dir / "meta.json"
    simplified_path = bill_dir / "simplified.json"

    meta = load_json(meta_path)
    if not meta:
        return None

    congress = meta.get("congress")
    bill_type = meta.get("bill_type", "")
    bill_number = meta.get("bill_number", "")
    bill_id = meta.get("bill_id", bill_dir.name)

    if not all([congress, bill_type, bill_number]):
        return None

    old_status = meta.get("current_status", "unknown")

    # Fetch fresh actions from Congress.gov
    actions = fetch_actions(congress, bill_type, bill_number)
    if not actions:
        return None

    # Derive current status from actions
    status_info = derive_bill_status(actions)
    new_status = status_info["current_status"]

    # Check if anything changed
    changed = new_status != old_status

    if dry_run:
        if changed:
            return {"bill_id": bill_id, "old": old_status, "new": new_status}
        return None

    # Update meta.json with all status fields
    meta["current_status"] = status_info["current_status"]
    meta["status_date"] = status_info["status_date"]
    meta["last_action_date"] = status_info["last_action_date"]
    meta["last_action_text"] = status_info["last_action_text"]
    meta["passed_house"] = status_info["passed_house"]
    meta["passed_house_date"] = status_info["passed_house_date"]
    meta["passed_senate"] = status_info["passed_senate"]
    meta["passed_senate_date"] = status_info["passed_senate_date"]
    meta["became_law"] = status_info["became_law"]
    meta["became_law_date"] = status_info["became_law_date"]
    meta["vetoed"] = status_info["vetoed"]
    meta["vetoed_date"] = status_info["vetoed_date"]
    save_json(meta_path, meta)

    # Update simplified.json if it exists
    simplified = load_json(simplified_path)
    if simplified:
        simplified["stage"] = status_info["current_status"]
        simplified["stage_label"] = STATUS_LABELS.get(
            status_info["current_status"], status_info["current_status"]
        )
        simplified["current_status"] = status_info["current_status"]
        simplified["status_date"] = status_info["status_date"]
        simplified["last_action_date"] = status_info["last_action_date"]
        simplified["last_action_text"] = status_info["last_action_text"]
        simplified["passed_house"] = status_info["passed_house"]
        simplified["passed_senate"] = status_info["passed_senate"]
        simplified["became_law"] = status_info["became_law"]
        simplified["vetoed"] = status_info["vetoed"]
        save_json(simplified_path, simplified)

        # Also update the site copy
        site_copy = SITE_DIR / bill_dir.name / "simplified.json"
        if site_copy.exists():
            save_json(site_copy, simplified)

    if changed:
        return {"bill_id": bill_id, "old": old_status, "new": new_status}
    return None


def main():
    parser = argparse.ArgumentParser(description="Update bill statuses from Congress.gov")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: CONGRESS_API_KEY not set")
        sys.exit(1)

    bill_dirs = sorted(DATA_DIR.iterdir()) if DATA_DIR.exists() else []
    bill_dirs = [d for d in bill_dirs if d.is_dir() and (d / "meta.json").exists()]

    print(f"Updating statuses for {len(bill_dirs)} bills...")
    if args.dry_run:
        print("(DRY RUN - no files will be modified)\n")

    changes = []
    errors = 0

    for i, bill_dir in enumerate(bill_dirs, 1):
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(bill_dirs)}")

        try:
            result = update_bill_status(bill_dir, dry_run=args.dry_run)
            if result:
                changes.append(result)
                label = STATUS_LABELS.get(result["new"], result["new"])
                print(f"  CHANGED: {result['bill_id']}: {result['old']} -> {result['new']} ({label})")
        except Exception as e:
            errors += 1
            print(f"  ERROR: {bill_dir.name}: {e}")

        # Rate limiting - Congress.gov allows ~1000 requests/hour
        time.sleep(0.4)

    print(f"\nDone. {len(changes)} status changes, {errors} errors out of {len(bill_dirs)} bills.")

    if changes:
        from collections import Counter
        new_counts = Counter(c["new"] for c in changes)
        print("\nStatus changes summary:")
        for status, count in new_counts.most_common():
            label = STATUS_LABELS.get(status, status)
            print(f"  {count:>4} bills moved to: {label}")


if __name__ == "__main__":
    main()
