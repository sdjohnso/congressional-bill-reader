# Congressional Bill Reader

## 1. Project Overview

Congressional Bill Reader is a fully automated pipeline that polls the Congress.gov API for US federal bills that have cleared committee, simplifies them to approximately a sixth-grade reading level using the Anthropic API, stores the output as structured JSON, and serves everything as a free public static site via Cloudflare Pages.

**How it works:**
- GitHub Actions runs the pipeline twice daily (7am and 7pm Eastern)
- `fetch_bills.py` polls Congress.gov for bills that have advanced past committee
- `process_bill.py` sends bill text to Claude for simplification
- `build_index.py` rebuilds the master index with search fields
- The Action commits processed files back to the repo, triggering Cloudflare Pages deployment
- Static site serves from `site/src/` with client-side Fuse.js search

**Deployment stack:** GitHub Actions + Cloudflare Pages (no server, no database, no cost beyond API fees)

---

## 2. Architecture and Data Flow

### Four-Script Pipeline

1. **fetch_bills.py** - Polls Congress.gov API, checks for bills with committee action, writes `needs_processing` flags. Also fetches subjects, summaries, titles, and cosponsor data.

2. **process_bill.py** - Picks up flagged bills, chunks text at section boundaries (~14,000 words with 150-word overlap), calls Claude for simplification, generates `plain_keywords`, writes structured `simplified.json` files.

3. **build_index.py** - Walks all bill folders, builds `index.json` with search-ready fields for Fuse.js.

4. **GitHub Action** - Copies bill JSON files into `site/src/bills/` and commits everything.

### Directory Structure

```
/
├── .github/workflows/
│   └── fetch_and_process.yml
├── scripts/
│   ├── fetch_bills.py
│   ├── process_bill.py
│   ├── build_index.py
│   ├── monitor.py
│   └── utils.py
├── data/bills/{congress}-{type}-{number}/
│   ├── meta.json
│   ├── original.txt
│   └── simplified.json
├── site/
│   ├── public/index.json
│   └── src/
│       ├── index.html
│       └── bills/{bill_id}/simplified.json
└── CLAUDE.md
```

---

## 3. Smart Update Filtering

During active legislative sessions, Congress.gov may return hundreds of bills per run. The current pipeline checks every bill's action history on every run, costing one API request per bill.

**Optimization (implemented in fetch_bills.py):**
- Before making the actions API call, compare `bill.updateDate` from the list endpoint against `meta.get("update_date")` stored from the previous run
- If dates match AND `simplified_complete` is true, skip immediately without hitting the actions endpoint
- This dramatically reduces API calls for unchanged bills

---

## 4. Data Schema Contract

### Critical Fields (Never Remove)

The `word_offset` and `char_offset` fields on every section object in `simplified.json` are computed at write time and must never be removed or changed. These fields enable:
- Section-level deep links
- Shareable TTS timestamps
- Table of contents anchors

All without reprocessing any bill.

### simplified.json Schema

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
  "subjects": ["Taxation", "Digital assets", "Federal budgets"],
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
      "title": "Section 1  Short Title",
      "word_offset": 0,
      "char_offset": 0,
      "text": "Simplified section text..."
    }
  ]
}
```

### index.json Schema

Contains all fields from simplified.json EXCEPT full section text. Section text is loaded per-bill when a user opens the reader.

---

## 5. Search Architecture

### Why Client-Side Search

The stack is fully static JSON served from Cloudflare Pages with no server. The approach is:
- Bake a lightweight search index into `index.json` at build time
- Use Fuse.js on the frontend for fuzzy client-side search
- Fuse.js is a single small JavaScript file with no dependencies

### Search Fields and Weights

| Field | Weight | Source |
|-------|--------|--------|
| plain_keywords | 1.0 (highest) | Claude-generated during processing |
| short_title | 0.8 | Titles API endpoint |
| plain_summary | 0.8 | Claude-generated |
| subjects | 0.6 | Subjects API endpoint (CRS terms) |
| policy_area | 0.6 | Subjects API endpoint |
| title | 0.5 | Bill detail endpoint |
| sponsor_name | 0.3 | Bill detail endpoint |
| sponsor_state | 0.3 | Bill detail endpoint |
| bill_number | 0.3 | Bill detail endpoint |

### plain_keywords Field

During `process_bill.py`, after generating simplified sections, Claude produces 8-12 plain-language keywords describing what the bill does in words a regular person might search for. Not legal terms, not formal CRS subject headings. Examples for the BITCOIN Act: "cryptocurrency", "digital money", "government savings", "national reserve", "Bitcoin purchase".

### Congress.gov API Endpoints Used

| Endpoint | Data Retrieved |
|----------|----------------|
| `/bill/{congress}` | Bill list with updateDate |
| `/bill/{congress}/{type}/{number}` | Bill detail, sponsor info |
| `/bill/.../actions` | Committee clearance check |
| `/bill/.../subjects` | legislativeSubjects, policyArea |
| `/bill/.../summaries` | CRS summary text (for context) |
| `/bill/.../titles` | Short title, all official titles |
| `/bill/.../cosponsors` | Cosponsor count |
| `/bill/.../text` | Text version URL |

---

## 6. Local Monitoring

### scripts/monitor.py

Run `python scripts/monitor.py` to check pipeline health:

- **Last successful run**: Most recent commit timestamp and most recent bill's `last_updated`
- **Bill count**: Total bills in the index
- **Stale flags**: Any `needs_processing` flags older than 48 hours (indicates failure)
- **Cloudflare analytics** (optional): If `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are set

Output is clean plain-text suitable for terminal review.

---

## 7. Environment and Secrets

### GitHub Repository Secrets

Set in Settings > Secrets and Variables > Actions:

| Secret | Source |
|--------|--------|
| `CONGRESS_API_KEY` | api.congress.gov |
| `ANTHROPIC_API_KEY` | console.anthropic.com |

### Local Development (.env)

```
CONGRESS_API_KEY=your_key
ANTHROPIC_API_KEY=your_key
CLOUDFLARE_API_TOKEN=optional
CLOUDFLARE_ACCOUNT_ID=optional
```

---

## 8. Deployment Steps

1. Create GitHub repo and push this directory
2. Add `CONGRESS_API_KEY` and `ANTHROPIC_API_KEY` to repo secrets
3. Connect repo to Cloudflare Pages:
   - Build output directory: `site/src`
   - Build command: (leave blank - Action handles file copying)
4. Trigger GitHub Action manually from Actions tab
5. Verify `simplified.json` files appear in `site/src/bills/` and site loads

---

## 9. Current Build Status

| Component | Status |
|-----------|--------|
| Pipeline scripts | Complete |
| Smart update filtering | Complete |
| API enrichment (subjects, summaries, etc.) | Complete |
| Fuse.js search | Complete |
| monitor.py | Complete |
| GitHub Action YAML | Verified |
| First deployment | Not yet deployed |
