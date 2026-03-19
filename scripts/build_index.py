"""
build_index.py
Walks all bill folders and builds a single index.json that the frontend
reads to populate the bill listing page. Includes all search-relevant fields
for Fuse.js client-side search. Runs after process_bill.py.

Usage:
    python scripts/build_index.py
"""

import json
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "data" / "bills"
OUTPUT_PATH = Path(__file__).parent.parent / "site" / "public" / "index.json"


def build_index():
    bills = []

    for folder in sorted(DATA_DIR.iterdir()):
        if not folder.is_dir():
            continue
        simplified_path = folder / "simplified.json"
        if not simplified_path.exists():
            continue

        try:
            with open(simplified_path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"WARNING: Skipping {folder.name} - malformed JSON: {e}")
            continue

        # Get subjects as a searchable string for Fuse.js
        subjects = data.get("subjects", [])
        subjects_str = ", ".join(subjects) if subjects else ""

        # Include all fields needed for display and search
        # (full section text is NOT included - loaded per-bill when user opens reader)
        bills.append({
            # Display fields
            "bill_id": data.get("bill_id"),
            "title": data.get("title"),
            "short_title": data.get("short_title", ""),
            "congress": data.get("congress"),
            "bill_number": data.get("bill_number"),
            "introduced_date": data.get("introduced_date"),
            "stage": data.get("stage"),
            "stage_label": data.get("stage_label"),
            "last_updated": data.get("last_updated"),
            "plain_summary": data.get("plain_summary"),
            "section_count": len(data.get("sections", [])),
            # Search/enrichment fields for Fuse.js
            "policy_area": data.get("policy_area", ""),
            "subjects": subjects,
            "subjects_str": subjects_str,  # Pre-joined for search
            "sponsor_name": data.get("sponsor_name", ""),
            "sponsor_party": data.get("sponsor_party", ""),
            "sponsor_state": data.get("sponsor_state", ""),
            "cosponsor_count": data.get("cosponsor_count", 0),
            "plain_keywords": data.get("plain_keywords", []),
            "plain_keywords_str": ", ".join(data.get("plain_keywords", [])),  # Pre-joined for search
        })

    # Sort newest first
    bills.sort(key=lambda b: b.get("last_updated", ""), reverse=True)

    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bill_count": len(bills),
        "bills": bills,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(index, f, indent=2)

    print(f"Index built: {len(bills)} bill(s) written to {OUTPUT_PATH}")


if __name__ == "__main__":
    build_index()
