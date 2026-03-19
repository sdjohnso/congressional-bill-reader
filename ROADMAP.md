# Congressional Bill Reader - Roadmap

## Phase 1: First Working Deployment

Everything required to push the repo, connect to Cloudflare, and go live.

### 1.1 Smart Update Filtering
- [ ] Modify `fetch_bills.py` to compare `bill.updateDate` against stored `meta.update_date`
- [ ] Skip bills where dates match AND `simplified_complete` is true
- [ ] This prevents unnecessary API calls for unchanged bills

### 1.2 API Enrichment
- [ ] Add subjects endpoint fetch (legislativeSubjects, policyArea)
- [ ] Add summaries endpoint fetch (CRS summary for Claude context)
- [ ] Add titles endpoint fetch (short_title)
- [ ] Add cosponsors endpoint fetch (count only, not individual names)
- [ ] Store enriched data in meta.json

### 1.3 Process Bill Updates
- [ ] Update Claude prompt to generate plain_keywords (8-12 search terms)
- [ ] Use CRS summary as context when generating plain_summary
- [ ] Include all new fields in simplified.json output

### 1.4 Build Index Updates
- [ ] Include search-relevant fields in index.json
- [ ] Prepare subjects array as searchable string

### 1.5 Frontend Search
- [ ] Add Fuse.js from CDN
- [ ] Create search input above bill list
- [ ] Configure field weights for fuzzy search
- [ ] Filter bill cards in real-time

### 1.6 Health Monitoring
- [ ] Create scripts/monitor.py
- [ ] Check last run timestamp
- [ ] Count bills in index
- [ ] Detect stale needs_processing flags (>48 hours)
- [ ] Optional Cloudflare analytics

### 1.7 GitHub Actions Verification
- [ ] Validate workflow YAML syntax
- [ ] Confirm file paths match directory structure
- [ ] Test workflow locally if possible

### 1.8 Site Verification
- [ ] Confirm index.html fetches from correct relative paths
- [ ] Test bill card rendering
- [ ] Test reader view loading

### 1.9 Documentation
- [ ] Create SETUP.md with exact manual deployment steps
- [ ] Secrets configuration
- [ ] Cloudflare Pages connection

---

## Phase 2: Future Enhancements

Does not block launch. To be implemented after successful deployment.

### 2.1 Section-Level Table of Contents
- Add collapsible TOC in reader view
- Jump to section on click
- Highlight current section during TTS

### 2.2 Shareable Deep Links
- Generate URLs with word offsets
- Resume TTS at specific position
- Show specific section on load

### 2.3 Bill Stage Progress Tracker
- Visual timeline of bill progression
- Committee, floor vote, presidential action stages
- Current position indicator

### 2.4 Diff View for Updated Bills
- Track version history
- Highlight changes between versions
- Side-by-side comparison

### 2.5 Expanded Filtering
- All introduced bills (not just committee-cleared)
- Filter by chamber, sponsor party, policy area
- Date range filtering
