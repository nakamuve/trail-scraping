#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import numpy as np
from pathlib import Path
import json
import time
import logging
import os
import threading
from typing import Union

# Rate limiter for request throttling
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


def create_session():
    session = requests.Session()
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
    })
    return session


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)


def json_in(file_path):
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            logging.info(f"Successfully loaded data from {file_path}")
            return data
    except FileNotFoundError:
        logging.warning(f"File not found: {file_path}, returning empty dict")
        return {}
    except json.JSONDecodeError:
        logging.error(f"JSON decode error on file: {file_path}, returning empty dict")
        return {}

def json_out(obj, file_path):
    with open(file_path, 'w') as file:
        json.dump(obj, file, indent=4, sort_keys=True)
        logging.info(f"Successfully saved data to {file_path}")


def time2float(time_str: str) -> float:
    """
    PURPOSE:
    To convert time as string to time as float.
    
    ARGUMENTS:
    :param time_str: Time formatted as HH:MM:SS
    
    RETURNS: 
    :return: None
    
    EXAMPLE:
    >>> time2float('0:15:00')
    0.25
    """
    return float(np.sum([int(v) / 60 ** p for p, v in enumerate(time_str.split(':'))]))


def fmt(info: Union[dict, bool, None] = None, *args) -> None:
    """
    PURPOSE:
    To format and print scraped data as markdown table 
    Special behaviour is fmt(false) which prints headers to the table
    
    ARGUMENTS:
    :param info: A dictionary containing the scraped data
    :param args: An array of strings that query the scraped data
    
    RETURNS: 
    :return: None
    
    EXAMPLE: 
    >>> fmt(False)
    |        KEY |   N_R |  CAT |      DST |     TIME | NAME  | URL
    """
    # Columns to format
    spacing = [
        ('KEY', 10, str.rjust),
        ('N_R', 5, str.rjust),
        ('CAT', 4, str.rjust),
        ('DST', 8, str.rjust),
        ('TIME', 8, str.rjust),
        ('NAME', 50, str.ljust),
        ('URL', 55, str.ljust),
        ('STATUS', 3, str.ljust),
    ]

    # Add empty formatters when too many args are given
    spacing += [(0, lambda x, y: x)] * (len(args) - len(spacing))

    if info is False:  # Print the spacers names as headers
        args = [k for k, _, _ in spacing]
    elif info is not None:  # Search the arg value in the info if possible
        args = [a if a not in info else info[a] for a in args]
        
        # Handle Results as list of dictionaries
        new_args = []
        for arg in args:
            if arg == info.get('Results', []) and isinstance(arg, list) and any(isinstance(r, dict) for r in arg):
                # List of dictionaries (new format for Results)
                times = [r["time"] for r in arg if isinstance(r, dict) and r["time"] > 0]
                if times:
                    new_args.append(f'{np.mean(times):.1f} hrs')
                else:
                    new_args.append(arg)
            elif isinstance(arg, list) and not any(isinstance(r, dict) for r in arg):
                # List of numbers (old format for Results)
                valid_times = np.array(arg)[np.array(arg) > 0]
                if len(valid_times) > 0:
                    new_args.append(f'{valid_times.mean():.1f} hrs')
                else:
                    new_args.append(arg)
            else:
                new_args.append(arg)
        
        args = new_args

    # Apply the formatter to the args
    args = [str(a)[:sp] for a, (_, sp, _) in zip(args, spacing)]

    # Print the line, separated by pipes
    print('|', ' | '.join([mt(a, sp) for a, (_, sp, mt) in zip(args, spacing)]), '|')


def get_meta_info(request_response: requests.Response) -> dict:
    """   
    PURPOSE
    Extract metadata from the HTML content of a race event web page. 
    Identify and retrieve specific pieces of information such as the
    race title, category, and various other statistical details.

    ARGUMENTS
    request_response (requests.Response): The HTTP response object 

    RETURNS
    dict: Extracted metadata from the race event page. 
    
    EXAMPLE
    >>> print(get_meta_info(requests.get(https://utmb.world/utmb-index/races/12345..2024)))
    """
    # Some class names we will be looking for:
    title_classname = "font-24 font-d-34 futura-bold race-header_rh_race_title__COtYd"
    category_classname = "race-header_rh_category_logo_container__wTAh5"
    meta_classname = "col-12 col-md-6 col-lg-4 race-header_rh_stat_wrapper__1aSTO"

    # Get the page
    soup = BeautifulSoup(request_response.content, "html.parser")

    # Get the race title
    race_title = soup.find("h1", class_=title_classname).text

    # Get the race category
    race_category = '-'
    race_category_container = soup.find("div", class_=category_classname)
    if race_category_container is not None:
        race_category = race_category_container.find('img')["alt"]

    # Get race meta info
    meta_info_fields = soup.find_all("div", class_=meta_classname)
    meta_info = {inf.find("p").text: inf.find_all("span")[-1].text for inf in meta_info_fields}
    meta_info['Race Category'] = race_category
    meta_info['Race Title'] = race_title
    return meta_info


def add_page(request_url: Union[str, bytes], info: dict, session, rate_limiter: RateLimiter) -> int:
    """
    PURPOSE
    The add_page function fetches and parses a web page containing race event results, 
    extracts relevant information, and updates a provided dictionary with this information. 
    It handles different scenarios such as no results, missing pages, and paginated data.

    ARGUMENTS
    request_url (str | bytes): The URL of the web page to be requested and parsed. This URL points to a specific race event page.
    info (dict): A dictionary to be updated with the extracted metadata and results. This dictionary will be populated with information such as race title, category, results, number of results, and breakdowns by country, sex, and age.
    session (requests.Session): The HTTP session with retry configuration.
    rate_limiter (RateLimiter): The rate limiter for request throttling.
    
    RETURNS
    int: A status code indicating the outcome of the function:
    200: Successfully fetched and processed the page.
    201: No more results are available on the page.
    204: The page exists but contains no results.
    404: The requested page does not exist.
    
    EXAMPLE:
    # URL of the race event page
    >>> meta_info = {}
    >>> status = add_page("https://utmb.world/utmb-index/races/12345..2024?page=1", meta_info)
    Page processed successfully.
    >>> print(meta_info)
    {
        'Race Title': 'Example Race Title',
        ...
        'Age': {'Age Group1': count1, 'Age Group2': count2, ...}
    }
    """
    
    # Where to find page components
    row_classname = "my-table_cell__z__zN"
    n_results_classname = "font-16 font-d-18 font-oxanium-bold display-list-result_hit_qty__DPf3k"

    logging.info(f"Requesting page: {request_url}")

    # Request the page with retries and rate limiting
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            rate_limiter.acquire()
            response = session.get(request_url, timeout=15)
            break
        except requests.RequestException as e:
            retry_count += 1
            if retry_count >= max_retries:
                logging.error(f"Request failed after {max_retries} retries: {e}")
                return 404
            backoff = 2 ** retry_count
            logging.warning(f"Retrying in {backoff}s ({max_retries - retry_count} left): {e}")
            time.sleep(backoff)

    # No page exists for this year
    if response.status_code == 404:
        logging.warning(f"Page not found (404): {request_url}")
        return 404

    soup = BeautifulSoup(response.content, "html.parser")
    if not any(info):
        n_results_str = soup.find_all("h2", class_=n_results_classname)[0].text

        # No results available
        if n_results_str == 'No results':
            logging.info(f"No results available for {request_url}")
            return 204

        info.update(get_meta_info(response))
        info['Results'] = []
        info['N Results'] = int(n_results_str.split(' ')[0])
        info['Country'] = {}
        info['Sex'] = {}
        info['Age'] = {}
        logging.info(f"Found {info['N Results']} results for race: {info.get('Race Title', 'Unknown')}")

    # Get all results from this page
    rows = soup.find_all("div", class_="my-table_row__nlm_j")

    # We have exhausted the search for results for this race
    if not any(rows):
        logging.info(f"No more results on page {request_url}")
        return 201

    # Extract the information of each row
    logging.info(f"Processing {len(rows)} results from {request_url}")
    for row in rows:
        row_cells = row.find_all("div", class_=row_classname)
        rank, time, name, country, sex, age, _ = [i.text for i in row_cells]
        
        # Try to extract runner ID from the row
        runner_id = ""
        # Check if there's a link element that might contain the runner ID
        runner_links = row.find_all("a")
        if runner_links:
            for link in runner_links:
                href = link.get('href', '')
                # Extract runner ID from URL if present (assuming format contains 'runner' followed by ID)
                if 'runner' in href:
                    runner_id = href.split('/')[-1]  # Extract the last part of the URL which should be the ID
                    break
        
        # Calculate finish time
        finish_time = 0 if rank == 'DNF' else np.round(time2float(time), 4)
        
        # Store result as dictionary with time, name, runner ID, nationality and gender
        result = {
            'time': finish_time,
        #    'name': name.strip(),
            'runner_id': runner_id,
            'nationality': country.strip(),
            'gender': sex.strip()
        }
        
        info['Results'].append(result)
        
        # Update statistics
        for field, value in (('Country', country), ('Sex', sex), ('Age', age)):
            if value not in info[field]:
                info[field][value] = 0
            info[field][value] += 1
    # Continue to the next page
    return 200


def main():
    """Process UTMB race results grouped by year using per-year UID files"""
    root = Path(__file__).parent
    uids_dir = root / 'result' / 'race-uids'
    data_dir = root / 'result' / 'race-data'
    data_dir.mkdir(parents=True, exist_ok=True)

    uid_files = sorted(uids_dir.glob('utmb-uids-*.json'))
    if not uid_files:
        logging.error("No UTMB UID files found in result/race-uids/")
        return

    # Print the header of our report
    fmt(False)

    session = create_session()
    rate_limiter = RateLimiter(rate_per_second=4)

    total_processed = 0
    total_results = 0
    started_time = time.time()

    for uid_file in uid_files:
        year = int(uid_file.stem.rsplit('-', 1)[-1])

        race_uids_data = json_in(uid_file)
        if not isinstance(race_uids_data, list) or not race_uids_data:
            logging.warning(f"No UIDs in {uid_file.name}, skipping")
            continue

        results_file = data_dir / f'utmb-race-data-{year}.json'
        utmb_results = json_in(results_file) or {}

        last_race_uid = 0
        if utmb_results:
            last_race_uid = max(int(k.split('.')[0]) for k in utmb_results)
            logging.info(f"Year {year}: {len(utmb_results)} existing results, last UID: {last_race_uid}")
        else:
            logging.info(f"Year {year}: no existing results, {len(race_uids_data)} UIDs to process")

        race_count = 0

        for race_uid in race_uids_data:
            race_uid = int(race_uid)
            utmb_key = f'{race_uid}.{year}'

            if race_uid <= last_race_uid or utmb_key in utmb_results:
                continue

            logging.info(f"Processing race {utmb_key}")
            meta_info, status, page_no = {}, 200, 1
            while status == 200:
                url = f"https://utmb.world/utmb-index/races/{race_uid}..{year}?page={page_no}"
                status = add_page(url, meta_info, session, rate_limiter)
                page_no += 1

            content = [''] * 5
            if meta_info and meta_info.get('Results') and len(meta_info['Results']) > 0:
                utmb_results[utmb_key] = meta_info
                content = 'N Results', 'Race Category', 'Distance', 'Results', 'Race Title'
                race_count += 1
                logging.info(f"Successfully processed race {utmb_key}: {meta_info.get('Race Title', 'Unknown')} with {len(meta_info['Results'])} results")
            else:
                race_count += 1
                if status == 404:
                    logging.info(f"Race {utmb_key} not found (404)")
                elif status == 204:
                    logging.info(f"Race {utmb_key} found but has no results")
                else:
                    logging.warning(f"Race {utmb_key} processed but no valid data extracted")

            url = f"https://utmb.world/utmb-index/races/{race_uid}..{year}?page=1"
            fmt(meta_info, utmb_key, *content, url, status)

        json_out(utmb_results, results_file)
        total_processed += race_count
        total_results += len(utmb_results)
        logging.info(f"Year {year}: processed {race_count} new races, total {len(utmb_results)}")

    elapsed = time.time() - started_time
    logging.info(f"Script completed in {elapsed/60:.2f} min. Total races processed: {total_processed}")
    logging.info(f"Total races in dataset: {total_results}")


if __name__ == "__main__":
    main()
