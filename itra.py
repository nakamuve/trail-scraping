"""
This script checks for the existence of ITRA race UIDs within a UID range
(default: 0 - 150_000). It's not meant to be run as a notebook.

For example:
    https://itra.run/Races/RaceDetails/1     -->  404 Does not exist
    https://itra.run/Races/RaceDetails/10439 -->  200 Does exist

Scraping all possible races:
The script checks each race UID, using proper synchronization
to avoid race conditions and implements rate limiting to prevent getting blocked.

Parallelization:
The script uses concurrent.futures with appropriate synchronization to safely
process multiple race UIDs in parallel.

Command-line usage:
    python itra.py [--start START_UID] [--end END_UID] [--workers WORKERS] [--debug]
    
    --start START_UID: Start UID (default: 0)
    --end END_UID: End UID (default: 150000)
    --workers WORKERS: Number of worker threads (default: cpu_count)
    --rate RATE: Max requests/second (default: 4)
    --batch-size BATCH_SIZE: Batch size (default: 200)
    --debug: Enable debug logging

Final result:
Once the script completes, all existing race UIDs are grouped by year and
stored to 'result/race-uids/itra-uids-{year}.json'. If a file for a given year
already exists, the newly found race UIDs are merged into it.

Gamalan, May 2025
"""

import curl_cffi.requests
from tqdm import tqdm
from pathlib import Path
import json
import re
import concurrent.futures
import time
import os
import threading
import argparse
import logging


class RateLimiter:
    """Token-bucket rate limiter for thread-safe request throttling"""
    def __init__(self, rate_per_second):
        self.min_interval = 1.0 / rate_per_second if rate_per_second > 0 else 0
        self.lock = threading.Lock()
        self.last_request = 0.0

    def acquire(self):
        """Block until it's safe to make a request (thread-safe)"""
        if self.min_interval <= 0:
            return
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_request = time.time()


def json_out(obj: dict | list, target: str | Path):
    with open(target, 'w') as file:
        json.dump(obj, file, indent=4, sort_keys=True)


def json_load(source: str | Path):
    """Load JSON data from a file"""
    try:
        with open(source, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def extract_year(response_text):
    """Extract race year from ITRA race details page HTML"""
    m = re.search(r'Race\s*Date[:\s]+.*?(\d{4})', response_text, re.DOTALL | re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'[Dd]ate[:\s]+.*?(\d{4})[/-]\d{1,2}[/-]\d{1,2}', response_text)
    if m:
        return int(m.group(1))
    return None


# Lock for file operations to prevent race conditions
file_lock = threading.Lock()


# Rate-limit retry backoff schedule (seconds)
_RATE_LIMIT_BACKOFFS = [15, 30, 60]


def _is_rate_limited(status_code):
    """Check if status indicates rate limiting (AWS WAF returns 202)."""
    return status_code in (202, 429, 503)


# Create a session with TLS fingerprint impersonation
def create_session():
    session = curl_cffi.requests.Session()

    # Add browser-like headers to avoid 403 errors
    session.headers.update({
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/123.0.0.0 Safari/537.36'),
        'Accept': ('text/html,application/xhtml+xml,application/xml;'
                   'q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'),
        'Accept-Language': 'en-US,en;q=0.9',
    })

    return session


def check_race_uid(race_uid, save_dir, session, rate_limiter, debug=False):
    """Check if a specific race UID exists on ITRA site"""
    race_file = save_dir / f'itra_race_{race_uid}.json'

    # Use a lock to prevent race conditions when checking/creating files
    with file_lock:
        # Check if the file already exists - if so, skip this UID
        if race_file.is_file():
            # If file exists but is empty, it was started but not completed
            if race_file.stat().st_size == 0:
                if debug:
                    logging.debug(f"UID {race_uid}: Found empty file, continuing check")
                # We'll continue processing this UID
                pass
            else:
                if debug:
                    logging.debug(f"UID {race_uid}: File already exists with content, skipping")
                # File exists and has content, skip this UID
                return None

    url = f'https://itra.run/Races/RaceDetails/{race_uid}'

    if debug:
        logging.debug(f"UID {race_uid}: Checking at {url}")

    # Retry loop with backoff for rate-limited responses
    for attempt in range(1 + len(_RATE_LIMIT_BACKOFFS)):
        try:
            # Throttle request rate globally across all threads
            rate_limiter.acquire()

            response = session.get(url, timeout=15, impersonate='chrome123')

            if debug:
                logging.debug(
                    f"UID {race_uid}: Got response status {response.status_code}"
                )

            if _is_rate_limited(response.status_code) and attempt < len(_RATE_LIMIT_BACKOFFS):
                wait = _RATE_LIMIT_BACKOFFS[attempt]
                logging.warning(
                    f"UID {race_uid}: got {response.status_code}, "
                    f"backing off {wait}s ({attempt+1}/{len(_RATE_LIMIT_BACKOFFS)})"
                )
                time.sleep(wait)
                continue

            # Use a lock when writing to the file
            with file_lock:
                if response.status_code == 200:
                    year = extract_year(response.text)
                    if year is None:
                        if debug:
                            logging.debug(
                                f"UID {race_uid}: Could not extract year, skipping"
                            )
                        return None
                    json_out({'status': 200, 'url': url, 'year': year}, race_file)
                    if debug:
                        logging.debug(
                            f"UID {race_uid}: Found race for year {year}, saving"
                        )
                    return (race_uid, year)
                else:
                    # Race doesn't exist (404, 301, etc.)
                    if race_file.is_file():
                        if debug:
                            logging.debug(
                                f"UID {race_uid}: Race not found, "
                                f"removing empty file"
                            )
                        race_file.unlink()
                    return None

        except Exception as e:
            if attempt >= len(_RATE_LIMIT_BACKOFFS):
                logging.warning(
                    f"Error checking race UID {race_uid} after "
                    f"{len(_RATE_LIMIT_BACKOFFS) + 1} attempts: {e}"
                )
                # Remove empty file if there was an error
                with file_lock:
                    if race_file.is_file():
                        race_file.unlink()
                return None
            wait = _RATE_LIMIT_BACKOFFS[attempt]
            logging.warning(
                f"Retrying UID {race_uid} in {wait}s "
                f"({len(_RATE_LIMIT_BACKOFFS) - attempt} retries left): {e}"
            )
            time.sleep(wait)
            continue


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Check existence of ITRA race UIDs')
    parser.add_argument('--start', type=int, default=0,
                        help='Start UID (default: 0)')
    parser.add_argument('--end', type=int, default=200000)
    parser.add_argument('--workers', type=int, default=os.cpu_count() or 4)
    parser.add_argument('--rate', type=float, default=4,
                        help='Max requests/second (default: 4)')
    parser.add_argument('--batch-size', type=int, default=200)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Parameters
    root = Path(__file__).parent
    save_dir = root / 'itra_race_details'
    save_dir.mkdir(exist_ok=True)

    logging.info(
        f"Starting ITRA race check from UID {args.start} to {args.end} "
        f"with {args.workers} workers, max {args.rate} req/s"
    )

    output_dir = root / 'result' / 'race-uids'
    output_dir.mkdir(parents=True, exist_ok=True)

    # Global rate limiter shared across all threads
    rate_limiter = RateLimiter(rate_per_second=args.rate)
    batch_size = args.batch_size

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for batch_start in range(args.start, args.end, batch_size):
            batch_end = min(batch_start + batch_size, args.end)

            logging.info(f"Processing batch {batch_start}-{batch_end}")

            session = create_session()

            future_to_uid = {
                executor.submit(
                    check_race_uid, race_uid, save_dir,
                    session, rate_limiter, args.debug
                ): race_uid
                for race_uid in range(batch_start, batch_end)
            }

            batch_found: list[tuple[int, int]] = []
            for future in tqdm(
                concurrent.futures.as_completed(future_to_uid),
                total=batch_end - batch_start,
                desc=f"Batch {batch_start}-{batch_end}"
            ):
                result = future.result()
                if result is not None:
                    batch_found.append(result)

            # Merge batch results into per-year files immediately
            races_by_year: dict[int, list[int]] = {}
            for race_uid, year in batch_found:
                races_by_year.setdefault(year, []).append(race_uid)

            for year, uids in races_by_year.items():
                output_file = output_dir / f'itra-uids-{year}.json'
                existing = json_load(output_file)
                combined = sorted(set(existing + uids))
                json_out(combined, output_file)
                logging.info(f"  Year {year}: +{len(uids)} race(s) (total {len(combined)})")

            logging.info(
                f"Batch {batch_start}-{batch_end} done — "
                f"{len(batch_found)} races found, cooling down for 2 minutes..."
            )
            time.sleep(120)

    logging.info(f"All batches complete. Results in {output_dir}/")


if __name__ == "__main__":
    main()
