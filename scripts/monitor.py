"""
monitor.py
Health check script for the Congressional Bill Reader pipeline.
Run approximately monthly to verify the pipeline is working correctly.

Checks:
- Last successful run (most recent bill's last_updated field)
- Total bill count in the index
- Stale needs_processing flags (older than 48 hours = possible failure)
- Optional Cloudflare Pages analytics (if tokens available)

Usage:
    python scripts/monitor.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data" / "bills"
INDEX_PATH = Path(__file__).parent.parent / "site" / "public" / "index.json"
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")


def get_index_stats() -> dict:
    """Read the index.json and return bill count and last update info."""
    if not INDEX_PATH.exists():
        return {"exists": False, "bill_count": 0, "generated_at": None, "most_recent_bill": None}

    with open(INDEX_PATH) as f:
        index = json.load(f)

    bills = index.get("bills", [])
    most_recent = None

    if bills:
        # Bills are sorted newest first
        most_recent = {
            "bill_id": bills[0].get("bill_id"),
            "title": bills[0].get("short_title") or bills[0].get("title", "")[:60],
            "last_updated": bills[0].get("last_updated"),
        }

    return {
        "exists": True,
        "bill_count": len(bills),
        "generated_at": index.get("generated_at"),
        "most_recent_bill": most_recent,
    }


def get_stale_processing_flags() -> list[dict]:
    """Find any needs_processing flags older than 48 hours (indicates failure)."""
    stale = []
    threshold = datetime.now(timezone.utc) - timedelta(hours=48)

    if not DATA_DIR.exists():
        return stale

    for folder in DATA_DIR.iterdir():
        if not folder.is_dir():
            continue

        flag_path = folder / "needs_processing"
        if not flag_path.exists():
            continue

        # Get the modification time of the flag file
        mtime = datetime.fromtimestamp(flag_path.stat().st_mtime, tz=timezone.utc)
        if mtime < threshold:
            meta_path = folder / "meta.json"
            title = "Unknown"
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                    title = meta.get("title", "Unknown")[:50]

            stale.append({
                "bill_id": folder.name,
                "title": title,
                "flag_age_hours": int((datetime.now(timezone.utc) - mtime).total_seconds() / 3600),
            })

    return stale


def get_cloudflare_analytics() -> dict | None:
    """Fetch basic Cloudflare Pages analytics if tokens are available."""
    if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ACCOUNT_ID:
        return None

    # Get list of Pages projects to find ours
    try:
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        }

        # List Pages projects
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/pages/projects"
        resp = requests.get(url, headers=headers, timeout=30)

        if resp.status_code != 200:
            return {"error": f"API returned {resp.status_code}"}

        data = resp.json()
        projects = data.get("result", [])

        if not projects:
            return {"error": "No Pages projects found"}

        # Find our project (assume first one or one matching bill-reader)
        project = None
        for p in projects:
            if "bill" in p.get("name", "").lower():
                project = p
                break
        if not project:
            project = projects[0]

        return {
            "project_name": project.get("name"),
            "subdomain": project.get("subdomain"),
            "production_branch": project.get("production_branch"),
            "latest_deployment": project.get("latest_deployment", {}).get("created_on"),
        }

    except Exception as e:
        return {"error": str(e)}


def format_datetime(iso_str: str | None) -> str:
    """Format an ISO datetime string for display."""
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso_str


def run():
    print("=" * 60)
    print("Congressional Bill Reader - Health Check")
    print("=" * 60)
    print()

    # Index stats
    print("INDEX STATUS")
    print("-" * 40)
    stats = get_index_stats()

    if not stats["exists"]:
        print("  Index file: NOT FOUND")
        print("  This suggests the pipeline has not run yet.")
    else:
        print(f"  Index file: OK")
        print(f"  Total bills: {stats['bill_count']}")
        print(f"  Index generated: {format_datetime(stats['generated_at'])}")

        if stats["most_recent_bill"]:
            recent = stats["most_recent_bill"]
            print(f"  Most recent bill: {recent['bill_id']}")
            print(f"    Title: {recent['title']}")
            print(f"    Updated: {format_datetime(recent['last_updated'])}")

    print()

    # Stale processing flags
    print("PROCESSING FLAGS")
    print("-" * 40)
    stale = get_stale_processing_flags()

    if not stale:
        print("  No stale processing flags (good)")
    else:
        print(f"  WARNING: {len(stale)} stale flag(s) found (>48 hours old)")
        print("  This indicates a processing failure that needs investigation.")
        for item in stale:
            print(f"    - {item['bill_id']}: {item['title']} ({item['flag_age_hours']} hours)")

    print()

    # Cloudflare analytics (optional)
    print("CLOUDFLARE PAGES")
    print("-" * 40)

    if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ACCOUNT_ID:
        print("  Cloudflare tokens not configured (optional)")
        print("  Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in .env for analytics")
    else:
        cf = get_cloudflare_analytics()
        if cf and "error" in cf:
            print(f"  Error: {cf['error']}")
        elif cf:
            print(f"  Project: {cf.get('project_name', 'Unknown')}")
            print(f"  Subdomain: {cf.get('subdomain', 'Unknown')}")
            print(f"  Branch: {cf.get('production_branch', 'main')}")
            print(f"  Latest deploy: {format_datetime(cf.get('latest_deployment'))}")

    print()
    print("=" * 60)
    print("Health check complete.")

    # Exit with error code if there are issues
    if stale:
        sys.exit(1)


if __name__ == "__main__":
    run()
