"""
process_bill.py
For each bill folder that has a needs_processing flag, fetches the full text,
sends it to the Anthropic API in chunks, and writes a structured simplified.json
with one object per section. Offsets are computed at write time so future
deep-link and TTS timestamp features work without reprocessing.

Also generates plain_keywords for search and uses CRS summary as context.

Usage:
    python scripts/process_bill.py           # Process all queued bills
    python scripts/process_bill.py --bill-id 119-s-1247  # Process one specific bill
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
from utils import hash_text, chunk_text, compute_offsets, slugify

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATA_DIR = Path(__file__).parent.parent / "data" / "bills"
MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """You are a plain language editor. Your job is to take sections of US congressional bill text
and rewrite them so that any person with a sixth-grade reading level can understand them.

Rules you must follow:
- Use simple everyday words. Replace legal and technical terms with plain explanations.
- Write in complete sentences and short paragraphs.
- Do not use bullet points, numbered lists, dashes as dividers, asterisks, or any special characters.
- Do not use bold, italic, or any markdown formatting.
- If a term must be kept because there is no plain equivalent, explain it in parentheses the first time it appears.
- Preserve the section structure exactly. Each section becomes its own output block.
- Keep the tone neutral and factual. Do not editorialize or express opinions about the bill.
- Do not summarize so aggressively that important details are lost. Explain, do not just name things.
- Numbers, dates, and dollar amounts should be written out in plain words where possible.

Output format (strict JSON, no markdown fences, no preamble):
{
  "sections": [
    {
      "id": "s1",
      "slug": "section-1-short-title",
      "title": "Section 1  Short Title",
      "text": "Simplified plain language text of this section..."
    }
  ],
  "plain_summary": "A 2 to 3 sentence plain language summary of this entire chunk of the bill."
}

If you receive chunk N of M in the prompt, only output sections from that chunk.
The plain_summary should cover only the content in the current chunk, not the whole bill."""


def fetch_text(url: str) -> str:
    """Download bill text from the given URL."""
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    text = resp.text
    if text.strip().startswith("<"):
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
    return text


def call_anthropic(client: anthropic.Anthropic, chunk: str, chunk_num: int, total_chunks: int, bill_title: str) -> dict:
    """
    Send one chunk of bill text to Claude and return the parsed JSON response.
    Retries up to 3 times on failure.
    """
    user_message = f"""Please simplify the following section of the US congressional bill titled:
"{bill_title}"

This is chunk {chunk_num} of {total_chunks}.

--- BEGIN BILL TEXT ---
{chunk}
--- END BILL TEXT ---

Return only valid JSON with no markdown fences, preamble, or explanation. Follow the output format in your instructions exactly."""

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r'^```json\s*', '', raw)
            raw = re.sub(r'^```\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"    JSON parse error on attempt {attempt + 1}: {e}")
            if attempt == 2:
                raise
            time.sleep(5)
        except anthropic.RateLimitError:
            print("    Rate limited, waiting 30 seconds...")
            time.sleep(30)
        except Exception as e:
            print(f"    API error on attempt {attempt + 1}: {e}")
            if attempt == 2:
                raise
            time.sleep(10)
    return {}


def generate_bill_summary(client: anthropic.Anthropic, section_summaries: list[str], bill_title: str, crs_summary: str = "") -> str:
    """Generate a single plain-language summary of the whole bill from chunk summaries.

    Uses CRS summary as additional context when available.
    """
    combined = "\n\n".join(section_summaries)

    crs_context = ""
    if crs_summary:
        crs_context = f"""

For additional context, here is a summary from the Congressional Research Service (do not copy this directly, use it to inform your plain-language version):
{crs_summary[:2000]}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": f"""Below are plain-language summaries of each section of the US congressional bill titled:
"{bill_title}"

{combined}{crs_context}

Write a single plain-language summary of the whole bill in 3 to 5 sentences. Use sixth-grade reading level.
Do not use any special characters, bullet points, or formatting. Return only the summary text, nothing else."""
        }]
    )
    return response.content[0].text.strip()


def generate_plain_keywords(client: anthropic.Anthropic, bill_title: str, plain_summary: str, subjects: list[str]) -> list[str]:
    """Generate 8-12 plain-language search keywords for a bill.

    These are the words a regular person might type when searching,
    not legal terms or formal CRS subject headings.
    """
    subjects_str = ", ".join(subjects[:10]) if subjects else "none"

    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": f"""Generate 8 to 12 plain-language search keywords for this US congressional bill.

Bill title: {bill_title}
Summary: {plain_summary}
Formal subjects: {subjects_str}

These keywords should be the words a regular person would type into a search box when looking for this bill.
NOT legal terms. NOT formal subject headings. The kinds of words someone uses when they do not already know what a bill is called.

For example, for a bill about cryptocurrency reserves, good keywords would be:
cryptocurrency, digital money, bitcoin, government savings, national reserve

Return ONLY a JSON array of strings, no other text:
["keyword1", "keyword2", "keyword3", ...]"""
        }]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        keywords = json.loads(raw)
        if isinstance(keywords, list):
            return [str(k) for k in keywords[:12]]
    except json.JSONDecodeError:
        pass

    return []


def process_bill(folder: Path, client: anthropic.Anthropic):
    """Process a single bill folder: fetch text, chunk, simplify, write output."""
    meta_path = folder / "meta.json"
    if not meta_path.exists():
        print(f"  No meta.json found in {folder.name}, skipping.")
        return

    with open(meta_path) as f:
        meta = json.load(f)

    bill_title = meta.get("title", "Untitled Bill")
    text_url = meta.get("text_url", "")
    bill_id = meta.get("bill_id", folder.name)
    crs_summary = meta.get("crs_summary", "")
    subjects = meta.get("subjects", [])

    print(f"  Fetching text for {bill_id}...")
    try:
        raw_text = fetch_text(text_url)
    except Exception as e:
        print(f"  ERROR fetching text: {e}")
        return

    with open(folder / "original.txt", "w", encoding="utf-8") as f:
        f.write(raw_text)

    text_hash = hash_text(raw_text)

    if meta.get("version_hash") == text_hash and meta.get("simplified_complete"):
        print(f"  {bill_id} text unchanged, skipping.")
        (folder / "needs_processing").unlink(missing_ok=True)
        return

    print(f"  Chunking text ({len(raw_text.split())} words)...")
    chunks = chunk_text(raw_text, max_words=14000, overlap_words=150)
    print(f"  Processing {len(chunks)} chunk(s) through Claude...")

    all_sections = []
    chunk_summaries = []
    section_counter = 1

    for i, chunk in enumerate(chunks, 1):
        print(f"    Chunk {i}/{len(chunks)}...")
        try:
            result = call_anthropic(client, chunk, i, len(chunks), bill_title)
        except Exception as e:
            print(f"    FAILED on chunk {i}: {e}")
            return

        sections = result.get("sections", [])
        chunk_summary = result.get("plain_summary", "")
        if chunk_summary:
            chunk_summaries.append(chunk_summary)

        for section in sections:
            section["id"] = f"s{section_counter}"
            if not section.get("slug"):
                section["slug"] = slugify(section.get("title", f"section-{section_counter}"))
            section_counter += 1
            all_sections.append(section)

        if i < len(chunks):
            time.sleep(2)

    all_sections = compute_offsets(all_sections)

    # Generate whole-bill summary with CRS context
    print("  Generating whole-bill summary...")
    try:
        whole_summary = generate_bill_summary(client, chunk_summaries, bill_title, crs_summary)
    except Exception as e:
        print(f"  Could not generate summary: {e}")
        whole_summary = " ".join(chunk_summaries[:2])

    # Generate plain-language search keywords
    print("  Generating search keywords...")
    try:
        plain_keywords = generate_plain_keywords(client, bill_title, whole_summary, subjects)
    except Exception as e:
        print(f"  Could not generate keywords: {e}")
        plain_keywords = []

    # Build the final output document with all enriched fields
    simplified = {
        "bill_id": bill_id,
        "title": bill_title,
        "short_title": meta.get("short_title", ""),
        "congress": meta.get("congress"),
        "bill_number": f"{meta.get('bill_type', '').upper()}.{meta.get('bill_number', '')}",
        "introduced_date": meta.get("introduced_date", ""),
        "stage": meta.get("stage", "reported_by_committee"),
        "stage_label": meta.get("stage_label", "Passed Committee"),
        "version_hash": text_hash,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "plain_summary": whole_summary,
        # Search/enrichment fields
        "policy_area": meta.get("policy_area", ""),
        "subjects": subjects,
        "sponsor_name": meta.get("sponsor_name", ""),
        "sponsor_party": meta.get("sponsor_party", ""),
        "sponsor_state": meta.get("sponsor_state", ""),
        "cosponsor_count": meta.get("cosponsor_count", 0),
        "crs_summary_available": bool(crs_summary),
        "plain_keywords": plain_keywords,
        # Section content
        "sections": all_sections,
    }

    with open(folder / "simplified.json", "w", encoding="utf-8") as f:
        json.dump(simplified, f, indent=2, ensure_ascii=False)

    # Update meta
    meta["version_hash"] = text_hash
    meta["simplified_complete"] = True
    meta["last_processed"] = datetime.now(timezone.utc).isoformat()
    meta["section_count"] = len(all_sections)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    (folder / "needs_processing").unlink(missing_ok=True)

    print(f"  Done. {len(all_sections)} sections, {len(plain_keywords)} keywords written to simplified.json.")


def run(specific_bill_id: str | None = None):
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if specific_bill_id:
        folders = [DATA_DIR / specific_bill_id]
    else:
        folders = [f for f in DATA_DIR.iterdir() if f.is_dir() and (f / "needs_processing").exists()]

    if not folders:
        print("No bills queued for processing.")
        return

    print(f"Processing {len(folders)} bill(s)...")
    for folder in folders:
        print(f"\n--- {folder.name} ---")
        process_bill(folder, client)

    print("\nAll done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bill-id", help="Process a specific bill ID (e.g. 119-s-1247)")
    args = parser.parse_args()
    run(specific_bill_id=args.bill_id)
