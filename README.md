# Congressional Bill Reader

An automated pipeline that fetches US federal bills that have cleared committee,
simplifies them to approximately a sixth-grade reading level using AI, and
publishes them to a static site with built-in text-to-speech and fuzzy search.

## How it works

1. A scheduled GitHub Action runs twice daily (7am and 7pm Eastern)
2. It polls the Congress.gov API for bills that have advanced past committee
3. New or updated bills are processed through the Anthropic API in chunks
4. Output is stored as structured JSON with search-ready metadata
5. Cloudflare Pages serves the static site with Fuse.js client-side search

## Features

- Plain language simplification at sixth-grade reading level
- Text-to-speech with section highlighting
- Fuzzy search by topic, keyword, sponsor, or bill number
- Sponsor and policy area metadata
- No server required (fully static)

## Repo structure

```
/
├── .github/workflows/
│   └── fetch_and_process.yml   # Scheduled pipeline
├── scripts/
│   ├── fetch_bills.py          # Polls Congress.gov API + enrichment
│   ├── process_bill.py         # Simplifies via Anthropic API
│   ├── build_index.py          # Builds search index
│   ├── monitor.py              # Health check script
│   └── utils.py                # Shared helpers
├── data/bills/{congress}-{type}-{number}/
│   ├── meta.json               # Bill metadata, enrichment data
│   ├── original.txt            # Raw bill text
│   └── simplified.json         # Simplified output with search fields
├── site/
│   ├── public/index.json       # Master bill index for search
│   └── src/
│       ├── index.html          # Static reader site
│       └── bills/              # Copied bill JSON files
└── CLAUDE.md                   # Full project documentation
```

## Data schema

Each simplified.json includes:

```json
{
  "bill_id": "119-s-1247",
  "title": "Full official title",
  "short_title": "BITCOIN Act",
  "congress": 119,
  "bill_number": "S.1247",
  "introduced_date": "2025-03-11",
  "stage": "reported_by_committee",
  "stage_label": "Passed Committee",
  "version_hash": "abc123...",
  "last_updated": "2025-03-15T12:00:00Z",
  "plain_summary": "2-3 sentence plain language summary",
  "policy_area": "Government Operations",
  "subjects": ["Digital assets", "Federal budgets"],
  "sponsor_name": "Cynthia Lummis",
  "sponsor_party": "R",
  "sponsor_state": "WY",
  "cosponsor_count": 12,
  "crs_summary_available": true,
  "plain_keywords": ["cryptocurrency", "bitcoin", "government savings"],
  "sections": [
    {
      "id": "s1",
      "slug": "short-title",
      "title": "Section 1 Short Title",
      "word_offset": 0,
      "char_offset": 0,
      "text": "Simplified section text..."
    }
  ]
}
```

The word_offset and char_offset fields enable future deep linking and TTS timestamps.

## Setup

See [SETUP.md](SETUP.md) for detailed deployment instructions.

### Quick start

1. Create GitHub repo and push this directory
2. Add secrets: `CONGRESS_API_KEY`, `ANTHROPIC_API_KEY`
3. Connect to Cloudflare Pages (build output: `site/src`)
4. Run the GitHub Action manually

### Local development

```bash
pip install -r requirements.txt
python scripts/fetch_bills.py --dry-run
python scripts/monitor.py
```

## Cost estimate

- Typical bill (50-100 pages): $0.10 to $0.50
- Monthly during active session: $10 to $30
- Largest bill ever (5,593 pages): $15 to $25

## Future features

Planned enhancements (no data changes needed):
- Table of contents with section jump links
- Section-level share button with word offset
- TTS playback resume at shared timestamp
- Bill stage timeline / progress tracker
- Diff view for updated bills
