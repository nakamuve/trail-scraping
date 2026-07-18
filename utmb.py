"""
This script checks for the existence of UTMB.world race UIDs within a UID range
(default: 0 - 200_000) and time range (2014-2025). It's not meant to be run as 
a notebook.

For example:
    https://utmb.world/utmb-index/races/1..2014      -->  404 Does not exist
    https://utmb.world/utmb-index/races/10439..2023  -->  201 Does exist

Scraping all possible races:
The script checks each race UID across multiple years, using proper synchronization
to avoid race conditions and implements rate limiting to prevent getting blocked.

Parallelization:
The script uses concurrent.futures with appropriate synchronization to safely
process multiple race UIDs in parallel.

Command-line usage:
    python utmb.py [--start START_UID] [--end END_UID] [--workers WORKERS] [--year-start YEAR_START] [--year-end YEAR_END] [--debug]
    
    --start START_UID: Start UID (default: 0)
    --end END_UID: End UID (default: 200000)
    --workers WORKERS: Number of worker threads (default: 5)
    --year-start YEAR_START: Start year to check (default: 2003)
    --year-end YEAR_END: End year to check (default: 2025)
    --debug: Enable debug logging

Final result:
Once the script completes, all existing race UIDs are grouped by year and
stored to 'result/race-uids/utmb-uids-{year}.json'. If a file for a given year
already exists, the newly found race UIDs are merged into it.

MGPoirot, May 2024
Gamalan, May 2025
"""

import curl_cffi.requests
from tqdm import tqdm
from pathlib import Path
import json
import concurrent.futures
import time
import os
import threading
import argparse
import logging


class RateLimiter:
    """Simple token-bucket rate limiter for thread-safe request throttling"""
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


# Lock for file operations to prevent race conditions
file_lock = threading.Lock()


# Rate-limit retry backoff schedule (seconds)
_RATE_LIMIT_BACKOFFS = [15, 30, 60]


def _is_server_busy(status_code):
    """Check if status indicates server overload / rate limiting."""
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


def check_race_uid(race_uid, save_dir, years, session, rate_limiter, debug=False):
    """Check if a specific race UID exists in any of the given years"""
    race_file = save_dir / f'utmb_race_{race_uid}.json'

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

    race_exists = False
    found_year = None

    for year in range(*years):
        url = f'https://utmb.world/utmb-index/races/{race_uid}..{year}'

        if debug:
            logging.debug(f"UID {race_uid}: Checking for year {year} at {url}")

        # Retry loop with backoff for server-busy / rate-limited responses
        for attempt in range(1 + len(_RATE_LIMIT_BACKOFFS)):
            try:
                # Throttle request rate globally across all threads
                rate_limiter.acquire()

                response = session.get(url, timeout=15, impersonate='chrome123')

                if debug:
                    logging.debug(
                        f"UID {race_uid}, year {year}: "
                        f"Got response status {response.status_code}"
                    )

                if response.status_code == 404:
                    # Year doesn't exist, try next year
                    break

                if _is_server_busy(response.status_code) and attempt < len(_RATE_LIMIT_BACKOFFS):
                    wait = _RATE_LIMIT_BACKOFFS[attempt]
                    logging.warning(
                        f"UID {race_uid}, year {year}: got {response.status_code}, "
                        f"backing off {wait}s ({attempt+1}/{len(_RATE_LIMIT_BACKOFFS)})"
                    )
                    time.sleep(wait)
                    continue

                # Any non-404, non-busy status (including 200, 201, 301, 403)
                race_exists = True
                found_year = year
                if debug:
                    logging.debug(f"UID {race_uid}: Found race for year {year}")
                break

            except Exception as e:
                if attempt >= len(_RATE_LIMIT_BACKOFFS):
                    logging.warning(
                        f"Error checking race UID {race_uid} for year {year}: {e}"
                    )
                    break
                wait = _RATE_LIMIT_BACKOFFS[attempt]
                logging.warning(
                    f"Retrying UID {race_uid}, year {year} in {wait}s "
                    f"({len(_RATE_LIMIT_BACKOFFS) - attempt} retries left): {e}"
                )
                time.sleep(wait)
                continue

        if race_exists:
            break

    # Use a lock when writing to the file
    with file_lock:
        if race_exists:
            json_out({'Status': 200, 'year': found_year}, race_file)
            return (race_uid, found_year)
        else:
            # Remove empty file if race doesn't exist in any year
            if race_file.is_file():
                if debug:
                    logging.debug(
                        f"UID {race_uid}: Race not found in any year, "
                        f"removing empty file"
                    )
                race_file.unlink()
            return None


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Check existence of UTMB race UIDs')
    parser.add_argument('--start', type=int, default=0,
                        help='Start UID (default: 0)')
    parser.add_argument('--end', type=int, default=150000)
    parser.add_argument('--workers', type=int, default=os.cpu_count() or 4)
    parser.add_argument('--year-start', type=int, default=2003)
    parser.add_argument('--year-end', type=int, default=2025)
    parser.add_argument('--batch-size', type=int, default=200)
    parser.add_argument('--rate', type=float, default=2)
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
    save_dir = root / 'utmb_race_details'
    save_dir.mkdir(exist_ok=True)
    years = args.year_start, args.year_end

    logging.info(
        f"Starting UTMB race check from UID {args.start} to {args.end} "
        f"with {args.workers} workers, max {args.rate} req/s"
    )
    logging.info(f"Checking years from {args.year_start} to {args.year_end}")

    # Create a list to store existing races
    existing_races = []

    # Global rate limiter shared across all threads
    rate_limiter = RateLimiter(rate_per_second=args.rate)

    # Process race UIDs in batches to give the server recovery time
    batch_size = args.batch_size

    # Process race UIDs concurrently with batching
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for batch_start in range(args.start, args.end, batch_size):
            batch_end = min(batch_start + batch_size, args.end)

            logging.info(f"Processing batch {batch_start}-{batch_end}")

            # Create a shared session for this batch
            session = create_session()

            # Submit tasks for this batch
            future_to_uid = {
                executor.submit(
                    check_race_uid, race_uid, save_dir, years,
                    session, rate_limiter, args.debug
                ): race_uid
                for race_uid in range(batch_start, batch_end)
            }

            # Process results as they complete
            for future in tqdm(
                concurrent.futures.as_completed(future_to_uid),
                total=batch_end - batch_start,
                desc=f"Batch {batch_start}-{batch_end}"
            ):
                result = future.result()
                if result is not None:
                    existing_races.append(result)

            # Give the server a break between batches
            logging.info(
                f"Batch {batch_start}-{batch_end} complete, "
                f"cooling down for 5 minutes..."
            )
            time.sleep(5 * 60)

    # Output directory for per-year race UID files
    output_dir = root / 'result' / 'race-uids'
    output_dir.mkdir(parents=True, exist_ok=True)

    # Group new races by year
    races_by_year: dict[int, list[int]] = {}
    for race_uid, year in existing_races:
        races_by_year.setdefault(year, []).append(race_uid)

    total_new = 0
    total_all = 0
    for year in sorted(races_by_year):
        output_file = output_dir / f'utmb-uids-{year}.json'
        existing = json_load(output_file)
        combined = sorted(set(existing + races_by_year[year]))
        json_out(combined, output_file)
        total_new += len(races_by_year[year])
        total_all += len(combined)
        logging.info(
            f"Year {year}: {len(races_by_year[year])} new races, "
            f"total {len(combined)}"
        )

    logging.info(
        f"Found {total_new} new races across {len(races_by_year)} years. "
        f"Total: {total_all} races."
    )
    logging.info(f"Results saved to {output_dir}/")


if __name__ == "__main__":
    main()
