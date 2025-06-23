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
    --workers WORKERS: Number of worker threads (default: 5)
    --debug: Enable debug logging

Final result:
Once the script completes, all existing race UIDs are grouped by year and
stored to 'result/race-uids/itra-uids-{year}.json'. If a file for a given year
already exists, the newly found race UIDs are merged into it.

Gamalan, May 2025
"""

from scrapling.fetchers import Fetcher, AsyncFetcher, StealthyFetcher, PlayWrightFetcher
import requests
from tqdm import tqdm
from pathlib import Path
import json
import re
import concurrent.futures
import time
import threading
import random
import argparse
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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

# Create a session with retry capabilities
def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Add browser-like headers to avoid 403 errors
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    })
    
    return session


def check_race_uid(race_uid, save_dir, session, debug=False):
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
    #fetcher = PlayWrightFetcher()
    #fetcher.configure(auto_match=True,keep_comments=False,keep_cdata=False)
    if debug:
        logging.debug(f"UID {race_uid}: Checking at {url}")
        
    try:
        # Add a small random delay to avoid overwhelming the server
        time.sleep(random.uniform(0.1, 0.3))
        
        response = session.get(url)
        
        if debug:
            logging.debug(f"UID {race_uid}: Got response status {response.status_code}")
            
        # Use a lock when writing to the file
        with file_lock:
            if response.status_code == 200:
                year = extract_year(response.text)
                if year is None:
                    if debug:
                        logging.debug(f"UID {race_uid}: Could not extract year, skipping")
                    return None
                json_out({'status': 200, 'url': url, 'year': year}, race_file)
                if debug:
                    logging.debug(f"UID {race_uid}: Found race for year {year}, saving")
                return (race_uid, year)
            else:
                # Remove empty file if race doesn't exist
                if race_file.is_file():
                    if debug:
                        logging.debug(f"UID {race_uid}: Race not found, removing empty file")
                    race_file.unlink()
                return None
                
    except requests.RequestException as e:
        # Log the error but continue to the next UID
        logging.warning(f"Error checking race UID {race_uid}: {e}")
        time.sleep(1)  # Backoff on error
        
        # Remove empty file if there was an error
        with file_lock:
            if race_file.is_file():
                if debug:
                    logging.debug(f"UID {race_uid}: Error occurred, removing empty file")
                race_file.unlink()
        return None


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Check existence of ITRA race UIDs')
    parser.add_argument('--start', type=int, default=0, help='Start UID (default: 0)')
    parser.add_argument('--end', type=int, default=150000, help='End UID (default: 150000)')
    parser.add_argument('--workers', type=int, default=5, help='Number of worker threads (default: 5)')
    parser.add_argument('--batch-size', type=int, default=500, help='Batch size (default: 500)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
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
    
    logging.info(f"Starting ITRA race check from UID {args.start} to {args.end} with {args.workers} workers")
    
    # Create a list to store existing races
    existing_races = []

    # Process race UIDs in batches to better control the workload
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
                executor.submit(check_race_uid, race_uid, save_dir, session, args.debug): race_uid
                for race_uid in range(batch_start, batch_end)
            }
            
            # Process results as they complete
            for future in tqdm(
                concurrent.futures.as_completed(future_to_uid), 
                total=batch_end - batch_start,
                desc=f"Batch {batch_start}-{batch_end}"
            ):
                race_uid = future.result()
                if race_uid is not None:
                    existing_races.append(race_uid)
            
            # Give the server a small break between batches
            time.sleep(10*60)

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
        output_file = output_dir / f'itra-uids-{year}.json'
        existing = json_load(output_file)
        combined = sorted(set(existing + races_by_year[year]))
        json_out(combined, output_file)
        total_new += len(races_by_year[year])
        total_all += len(combined)
        logging.info(f"Year {year}: {len(races_by_year[year])} new races, total {len(combined)}")

    logging.info(f"Found {total_new} new races across {len(races_by_year)} years. Total: {total_all} races.")
    logging.info(f"Results saved to {output_dir}/")


if __name__ == "__main__":
    main()
