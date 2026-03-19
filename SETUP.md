# Congressional Bill Reader - Setup Guide

This document contains the exact steps to deploy the Congressional Bill Reader.

## Prerequisites

- GitHub account
- Cloudflare account (free tier works)
- Congress.gov API key (free from api.congress.gov)
- Anthropic API key (from console.anthropic.com)

## Step 1: Create GitHub Repository

1. Create a new repository on GitHub
2. Clone this directory and push to the new repo:
   ```bash
   cd congressional-bill-reader
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/congressional-bill-reader.git
   git push -u origin main
   ```

## Step 2: Add Repository Secrets

Go to your GitHub repository > Settings > Secrets and Variables > Actions.

Add these two secrets:

| Secret Name | Value |
|-------------|-------|
| `CONGRESS_API_KEY` | Your Congress.gov API key |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

## Step 3: Connect to Cloudflare Pages

1. Log in to Cloudflare Dashboard
2. Go to Workers & Pages > Create application > Pages
3. Connect to Git and select your repository
4. Configure the build settings:
   - **Project name**: `congressional-bill-reader` (or your preference)
   - **Production branch**: `main`
   - **Build command**: (leave blank - the GitHub Action handles this)
   - **Build output directory**: `site/src`
5. Click "Save and Deploy"

The first deployment will show an empty site. That's expected - there are no bills yet.

## Step 4: Run the Pipeline

1. Go to your GitHub repository > Actions
2. Click "Fetch and Process Bills" in the left sidebar
3. Click "Run workflow" > "Run workflow"

The first run will:
- Fetch bills that have cleared committee
- Process them through Claude for simplification
- Build the search index
- Commit the output files to the repo

This commit will trigger a new Cloudflare Pages deployment.

## Step 5: Verify Deployment

After the Action completes (10-30 minutes depending on bill count):

1. Check that `site/src/bills/` contains subdirectories with `simplified.json` files
2. Check that `site/src/index.json` exists and contains bills
3. Visit your Cloudflare Pages URL (e.g., `congressional-bill-reader.pages.dev`)
4. Verify the site loads and bills are displayed
5. Test the search functionality

## Local Development

For local testing, create a `.env` file in the project root:

```
CONGRESS_API_KEY=your_congress_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key

# Optional - for monitor.py Cloudflare analytics
CLOUDFLARE_API_TOKEN=your_cloudflare_token
CLOUDFLARE_ACCOUNT_ID=your_account_id
```

Install dependencies:
```bash
pip install -r requirements.txt
```

Test the pipeline locally:
```bash
python scripts/fetch_bills.py --dry-run  # See what would be fetched
python scripts/fetch_bills.py            # Actually fetch and queue bills
python scripts/process_bill.py           # Process queued bills
python scripts/build_index.py            # Rebuild the index
```

Run the health check:
```bash
python scripts/monitor.py
```

## Ongoing Maintenance

- The pipeline runs automatically twice daily (7am and 7pm Eastern)
- Run `python scripts/monitor.py` monthly to check pipeline health
- Check for stale `needs_processing` flags which indicate failures
- API costs are approximately $10-30/month during active sessions

## Troubleshooting

**No bills appearing:**
- Check that CONGRESS_API_KEY is set correctly
- Run `python scripts/fetch_bills.py --dry-run` to see if bills are found

**Processing failures:**
- Check GitHub Actions logs for errors
- Look for stale `needs_processing` flags with `python scripts/monitor.py`

**Site not updating:**
- Verify Cloudflare Pages is connected to the correct branch
- Check that the GitHub Action completed successfully
- Verify files are in `site/src/` after the Action runs
