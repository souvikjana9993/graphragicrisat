"""
Batch fetch metadata from the ICRISAT EPrints JSON API.

Usage:
    python -m scraper.fetch_metadata --start 2 --end 200
    python -m scraper.fetch_metadata --start 2 --end 200 --resume  # resume from checkpoint
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/scrape.log", mode="a"),
    ],
)
log = logging.getLogger(__name__)

BASE_URL = "https://oar.icrisat.org/cgi/export/eprint/{id}/JSON/{id}.js"
DATA_DIR = Path("data/raw_metadata")
PROGRESS_FILE = Path("data/scrape_progress.json")
ERRORS_FILE = Path("data/scrape_errors.log")
DELAY_SECONDS = 1.5
TIMEOUT_SECONDS = 30
MAX_RETRIES = 3


def ensure_dirs():
    """Create output directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_progress() -> dict:
    """Load checkpoint file to resume from last successful ID."""
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"completed_ids": [], "failed_ids": [], "last_id": 0}


def save_progress(progress: dict):
    """Save checkpoint for resume capability."""
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def fetch_single(eprint_id: int) -> dict | None:
    """Fetch metadata JSON for a single eprint ID with retries."""
    url = BASE_URL.format(id=eprint_id)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT_SECONDS, headers={
                "User-Agent": "ICRISAT-GraphRAG-Scraper/1.0 (academic research)"
            })

            if resp.status_code == 404:
                log.warning(f"ID {eprint_id}: 404 Not Found — skipping")
                return None

            if resp.status_code != 200:
                log.warning(f"ID {eprint_id}: HTTP {resp.status_code} (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(DELAY_SECONDS * attempt)
                continue

            # EPrints JSON endpoint wraps response — try parsing
            text = resp.text.strip()
            # Sometimes EPrints wraps in a callback, strip it
            if text.startswith("(") or text.startswith("["):
                data = json.loads(text)
                if isinstance(data, list) and len(data) == 1:
                    data = data[0]
            else:
                data = json.loads(text)

            return data

        except requests.exceptions.Timeout:
            log.warning(f"ID {eprint_id}: Timeout (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(DELAY_SECONDS * attempt)
        except requests.exceptions.ConnectionError:
            log.warning(f"ID {eprint_id}: Connection error (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(DELAY_SECONDS * attempt * 2)
        except json.JSONDecodeError as e:
            log.error(f"ID {eprint_id}: JSON parse error — {e}")
            # Save raw response for debugging
            raw_path = DATA_DIR / f"{eprint_id}_raw.txt"
            raw_path.write_text(resp.text)
            return None

    log.error(f"ID {eprint_id}: Failed after {MAX_RETRIES} retries")
    return None


def extract_metadata(raw: dict, eprint_id: int) -> dict:
    """Extract and normalize the fields we care about from raw EPrints JSON."""
    # Authors
    authors = []
    for creator_field in ("creators", "icrisatcreators"):
        for c in raw.get(creator_field, []):
            name = c.get("name", {})
            authors.append({
                "given": (name.get("given") or "").strip(),
                "family": (name.get("family") or "").strip(),
            })

    # Keywords — may be semicolon or comma separated string
    raw_keywords = raw.get("keywords", "")
    if isinstance(raw_keywords, str):
        # Try semicolons first, then commas
        if ";" in raw_keywords:
            keywords = [k.strip() for k in raw_keywords.split(";") if k.strip()]
        else:
            keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]
    elif isinstance(raw_keywords, list):
        keywords = raw_keywords
    else:
        keywords = []

    # Subjects (crops)
    subjects = raw.get("subjects", [])
    if isinstance(subjects, str):
        subjects = [subjects]

    # Agrotags — parse structured tags
    agrotags_raw = raw.get("agrotags", "")
    agrotags = []
    geotags = []
    fishtags = []
    if isinstance(agrotags_raw, str):
        # Format: "<b>Agrotags</b> - genetics | drought | ... <br><b>Fishtags</b> - drying <br><b>Geopoliticaltags</b> - india | usa"
        import re
        agro_match = re.search(r'Agrotags</b>\s*-?\s*(.+?)(?:<br>|$)', agrotags_raw, re.IGNORECASE)
        fish_match = re.search(r'Fishtags</b>\s*-?\s*(.+?)(?:<br>|$)', agrotags_raw, re.IGNORECASE)
        geo_match = re.search(r'Geopoliticaltags</b>\s*-?\s*(.+?)(?:<br>|$)', agrotags_raw, re.IGNORECASE)

        if agro_match:
            agrotags = [t.strip() for t in agro_match.group(1).split("|") if t.strip()]
        if fish_match:
            fishtags = [t.strip() for t in fish_match.group(1).split("|") if t.strip()]
        if geo_match:
            geotags = [t.strip() for t in geo_match.group(1).split("|") if t.strip()]

    # PDF URLs
    pdf_urls = []
    for doc in raw.get("documents", []):
        for f in doc.get("files", []):
            if f.get("mime_type", "") == "application/pdf":
                uri = f.get("uri", "").replace("\\/", "/")
                pdf_urls.append({
                    "url": uri,
                    "filename": f.get("filename", ""),
                    "size": f.get("filesize", 0),
                })
        # Check security — is PDF public?
        security = doc.get("security", "public")
        for pdf in pdf_urls:
            pdf["restricted"] = security != "public"

    # Funders
    funders = raw.get("funders", "")
    if isinstance(funders, str) and funders and funders != "UNSPECIFIED":
        funder_list = [f.strip() for f in funders.split(",") if f.strip()]
    elif isinstance(funders, list):
        funder_list = funders
    else:
        funder_list = []

    return {
        "eprint_id": eprint_id,
        "title": raw.get("title", "").strip(),
        "abstract": raw.get("abstract", "").strip(),
        "authors": authors,
        "keywords": keywords,
        "subjects": subjects,
        "agrotags": agrotags,
        "fishtags": fishtags,
        "geotags": geotags,
        "publication": raw.get("publication", "").strip(),
        "date": raw.get("date", ""),
        "date_type": raw.get("date_type", ""),
        "type": raw.get("type", ""),
        "item_type": raw.get("item_type", raw.get("type", "")),
        "issn": raw.get("issn", ""),
        "doi": raw.get("doi", ""),
        "official_url": raw.get("official_url", ""),
        "uri": raw.get("uri", f"https://oar.icrisat.org/id/eprint/{eprint_id}"),
        "funders": funder_list,
        "pdf_urls": pdf_urls,
        "full_text_status": raw.get("full_text_status", ""),
        "ispublished": raw.get("ispublished", ""),
    }


def run(start_id: int, end_id: int, resume: bool = False):
    """Main scraping loop with checkpoint/resume."""
    ensure_dirs()
    progress = load_progress() if resume else {"completed_ids": [], "failed_ids": [], "last_id": 0}
    completed_set = set(progress["completed_ids"])

    total = end_id - start_id + 1
    scraped = 0
    skipped = 0
    failed = 0

    log.info(f"Starting scrape: IDs {start_id}–{end_id} ({total} IDs)")
    if resume and completed_set:
        log.info(f"Resuming — {len(completed_set)} already completed")

    for eprint_id in range(start_id, end_id + 1):
        # Skip already completed
        if eprint_id in completed_set:
            continue

        # Check if file already exists on disk
        output_file = DATA_DIR / f"{eprint_id}.json"
        if output_file.exists():
            completed_set.add(eprint_id)
            continue

        raw = fetch_single(eprint_id)

        if raw is None:
            failed += 1
            progress["failed_ids"].append(eprint_id)
        else:
            metadata = extract_metadata(raw, eprint_id)

            # Also save raw for debugging
            raw_file = DATA_DIR / f"{eprint_id}_raw.json"
            raw_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False))

            # Save cleaned metadata
            output_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

            scraped += 1
            completed_set.add(eprint_id)

            title_preview = metadata["title"][:60] + "..." if len(metadata["title"]) > 60 else metadata["title"]
            log.info(f"[{scraped}/{total}] ID {eprint_id}: {title_preview}")

        # Update checkpoint every 10 items
        if (scraped + failed) % 10 == 0:
            progress["completed_ids"] = sorted(completed_set)
            progress["last_id"] = eprint_id
            save_progress(progress)

        # Be polite
        time.sleep(DELAY_SECONDS)

    # Final checkpoint
    progress["completed_ids"] = sorted(completed_set)
    progress["last_id"] = end_id
    save_progress(progress)

    log.info(f"Done! Scraped: {scraped}, Skipped/404: {skipped}, Failed: {failed}")
    log.info(f"Total files in {DATA_DIR}: {len(list(DATA_DIR.glob('*.json')))}")


def main():
    parser = argparse.ArgumentParser(description="Fetch ICRISAT EPrints metadata")
    parser.add_argument("--start", type=int, default=2, help="Start eprint ID")
    parser.add_argument("--end", type=int, default=200, help="End eprint ID")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()
    run(args.start, args.end, args.resume)


if __name__ == "__main__":
    main()
