#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import numpy as np
from pathlib import Path
import json
import time
import logging
import re
import os
import threading
from itra_fetch_race_details import fetch_race_details

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def json_in(file_path):
    """Load JSON from file or return empty dict if file doesn't exist"""
    try:
        with open(file_path, "r") as file:
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
    """Save object as JSON to file"""
    with open(file_path, "w") as file:
        json.dump(obj, file, indent=4, sort_keys=True)
        logging.info(f"Successfully saved data to {file_path}")


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


def time2float(time_str):
    """Convert time string (HH:MM:SS) to float hours"""
    try:
        if isinstance(time_str, str) and ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 3:
                return float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
            elif len(parts) == 2:
                return float(parts[0]) + float(parts[1]) / 60
        return 0
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


def fmt(info=None, *args):
    """Format and print data as a markdown table"""
    headers = [
        "Race ID",
        "N Results",
        "Race Category",
        "Distance",
        "Race Date",
        "Results",
        "Race Title",
        "City / Country",
        "URL",
        "Status",
    ]

    if info is False:
        # Print header row
        print("|", " | ".join(headers), "|")
        print(
            "|",
            " | ".join(["---"] * len(headers)),
            "|",
        )
        return  # Don't print separator as data

    if not info:
        # Print None info
        formatted = []
        for i, arg in enumerate(args[:10]):
            if arg:
                formatted.append(str(arg))
            else:
                formatted.append("")
        print("|", " | ".join(formatted), "|")
        return

    formatted = []
    formatted.append(str(args[0]) if args else "N/A")

    content_keys = [
        "N Results",
        "Race Category",
        "Distance",
        "Race Date",
        "Results",
        "Race Title",
        "City / Country",
    ]

    for i, key in enumerate(content_keys):
        if i + 1 < len(args):
            formatted.append(args[i + 1])
        elif info.get(key):
            value = info[key]
            if isinstance(value, list):
                formatted.append(f"{len(value)} items")
            elif isinstance(value, dict):
                formatted.append(f"{len(value)} items")
            else:
                formatted.append(str(value))
        else:
            formatted.append("")

    # Add URL and status
    if len(args) > 7:
        formatted.append(args[7])
    else:
        formatted.append("")
    if len(args) > 8:
        formatted.append(str(args[8]))
    else:
        formatted.append("")

    print("|", " | ".join(formatted), "|")


def scrape_itra_race(race_id, session, rate_limiter):
    """Scrape race data from ITRA website"""
    url = f"https://itra.run/Races/RaceResults/{race_id}"

    logging.info(f"Requesting ITRA race {race_id} from {url}")

    try:
        # First fetch the race details page to get better distance and elevation data
        detail_data = fetch_race_details(race_id)

        # Then fetch the race results page
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            try:
                rate_limiter.acquire()
                response = session.get(url, timeout=15)
                break
            except requests.RequestException as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logging.error(f"Request failed after {max_retries} retries: {e}")
                    return {}, 404
                backoff = 2 ** retry_count
                logging.warning(f"Retrying in {backoff}s ({max_retries - retry_count} left): {e}")
                time.sleep(backoff)

        if response.status_code != 200:
            logging.warning(
                f"Failed to fetch race {race_id}, status code: {response.status_code}"
            )
            return {}, response.status_code

        # Parse the HTML content
        soup = BeautifulSoup(response.text, "html.parser")

        # Initialize race info dictionary
        race_info = {
            "Race Title": "Unknown",
            "Race Category": "Unknown",
            "Distance": detail_data["Distance"]
            if detail_data["Distance"] != "Unknown"
            else "Unknown",
            "Elevation Gain": detail_data["Elevation Gain"]
            if detail_data["Elevation Gain"] != "Unknown"
            else "Unknown",
            "Race Date": detail_data["Race Date"]
            if "Race Date" in detail_data and detail_data["Race Date"] != "Unknown"
            else "Unknown",
            "City / Country": detail_data["Location"]
            if "Location" in detail_data and detail_data["Location"] != "Unknown"
            else "Unknown",
            "Results": [],
            "Country": {},
            "Sex": {},
            "Age": {},
        }

        # Extract race title - looking for a header element
        title_elements = soup.find_all(["h1", "h2", "title"])
        for element in title_elements:
            if element.name == "title":
                title_text = element.text.strip()
                if " - ITRA" in title_text:
                    race_info["Race Title"] = title_text.split(" - ITRA")[0].strip()
                    break
            elif element.name == "h1":
                race_info["Race Title"] = element.text.strip()
                break

        # Try to find race details - distance, elevation gain
        # Look for a structured data element that may contain race details
        # Only if not already found from details page
        if (
            race_info["Distance"] == "Unknown"
            or race_info["Elevation Gain"] == "Unknown"
        ):
            race_details_divs = soup.select(
                "div.race-details, div.event-details, div.race-info"
            )
            if race_details_divs:
                for div in race_details_divs:
                    div_text = div.text.strip()

                    # Extract distance if not found from details page
                    if race_info["Distance"] == "Unknown":
                        distance_match = re.search(
                            r"(\d+(?:\.\d+)?\s*(?:km|mi))", div_text, re.IGNORECASE
                        )
                        if distance_match:
                            race_info["Distance"] = distance_match.group(1)

                    # Extract elevation gain if not found from details page
                    if race_info["Elevation Gain"] == "Unknown":
                        elevation_match = re.search(
                            r"(\d+(?:\.\d+)?\s*(?:d\+|m\+|d\s\+|m\s\+|meters|\+))",
                            div_text,
                            re.IGNORECASE,
                        )
                        if elevation_match:
                            race_info["Elevation Gain"] = elevation_match.group(1)

        # If structured elements not found, try general approach
        if (
            race_info["Distance"] == "Unknown"
            or race_info["Elevation Gain"] == "Unknown"
        ):
            for div in soup.find_all("div"):
                div_text = div.text.strip() if hasattr(div, "text") else ""
                if (
                    "km" in div_text.lower()
                    and len(div_text) < 30
                    and race_info["Distance"] == "Unknown"
                ):
                    race_info["Distance"] = div_text
                elif (
                    any(
                        x in div_text.lower() for x in ["d+", "m+", "elevation", "gain"]
                    )
                    and len(div_text) < 30
                    and race_info["Elevation Gain"] == "Unknown"
                ):
                    race_info["Elevation Gain"] = div_text

        # Try to determine race category based on distance
        if race_info["Distance"] != "Unknown":
            distance_text = race_info["Distance"].lower()
            distance_value = 0
            try:
                # Extract numeric part
                distance_match = re.search(r"(\d+(?:\.\d+)?)", distance_text)
                if distance_match:
                    distance_value = float(distance_match.group(1))

                    # First determine base category
                    base_category = ""
                    if "km" in distance_text:
                        if distance_value < 45:
                            base_category = "Trail"
                        elif distance_value < 80:
                            base_category = "50K"
                        elif distance_value < 110:
                            base_category = "100K"
                        else:
                            base_category = "Ultra"
                    elif "mi" in distance_text:
                        # Convert miles to km for categorization
                        km_distance = distance_value * 1.60934
                        if km_distance < 45:
                            base_category = "Trail"
                        elif km_distance < 80:
                            base_category = "50K"
                        elif km_distance < 110:
                            base_category = "100K"
                        elif distance_value >= 100:
                            base_category = "100M"
                        else:
                            base_category = "Ultra"

                    # Now include the actual distance in the category
                    race_info["Race Category"] = (
                        f"{base_category} ({race_info['Distance']})"
                    )
                else:
                    race_info["Race Category"] = "Unknown"
            except (ValueError, TypeError) as e:
                logging.warning(f"Could not parse distance: {e}")

        # Find the results table
        results_table = soup.find("table", id="RunnerRaceResults")

        if not results_table:
            logging.warning(f"No results table found for race {race_id}")
            return race_info, 204

        # Extract rows (skip the header row)
        rows = results_table.find_all("tr")
        if len(rows) <= 1:  # Only header row or no rows
            logging.warning(f"No result rows found for race {race_id}")
            return race_info, 204

        # Set number of results
        race_info["N Results"] = len(rows) - 1  # Subtract header row

        # Process each result row
        for row in rows[1:]:  # Skip header row
            try:
                cells = row.find_all("td")

                if len(cells) < 6:
                    continue

                # Extract data from cells
                rank = cells[0].text.strip() if cells[0].text else ""

                # Runner info from cell 1
                runner_cell = cells[1]
                runner_name = "Unknown"
                runner_id = ""

                # Check for link in runner cell
                runner_link = runner_cell.find("a")
                if runner_link:
                    runner_name = runner_link.text.strip()
                    href = runner_link.get("href", "")
                    if href:
                        # Extract runner ID from URL
                        parts = href.strip("/").split("/")
                        if len(parts) > 0:
                            runner_id = parts[-1]
                else:
                    runner_name = runner_cell.text.strip()

                # Get other data from cells - account for different column positions
                time_text = cells[2].text.strip() if len(cells) > 2 else ""

                # Check if this is the first row with subscription promotion
                has_subscription_cell = False
                for cell in cells:
                    if "Subscribe" in cell.text:
                        has_subscription_cell = True
                        break

                # Determine column indices based on row structure
                if has_subscription_cell or len(cells) >= 7:
                    # First row with subscription cell
                    age = cells[4].text.strip() if len(cells) > 4 else "Unknown"
                    gender = cells[5].text.strip() if len(cells) > 5 else "Unknown"
                    nationality = cells[6].text.strip() if len(cells) > 6 else "Unknown"
                else:
                    # Subsequent rows without subscription cell
                    age = cells[3].text.strip() if len(cells) > 3 else "Unknown"
                    gender = cells[4].text.strip() if len(cells) > 4 else "Unknown"
                    nationality = cells[5].text.strip() if len(cells) > 5 else "Unknown"

                # Extract nationality from flag image or text
                if nationality == "Unknown" and len(cells) > 5:
                    # Try to find nationality from the flag image
                    nat_cell = (
                        cells[6]
                        if has_subscription_cell or len(cells) >= 7
                        else cells[5]
                    )
                    flag_img = nat_cell.find("img")
                    if flag_img:
                        src = flag_img.get("src", "")
                        if "CountryFlags" in src:
                            # Extract country code from flag image path
                            country_code = src.split("/")[-1].split(".")[0].upper()
                            if country_code == "NL":
                                nationality = "NED"
                            elif country_code == "DE":
                                nationality = "GER"
                            elif country_code == "GB" or country_code == "UK":
                                nationality = "GBR"
                            elif country_code == "US":
                                nationality = "USA"
                            else:
                                # Use the text if available, otherwise use the code
                                if nat_cell.text.strip():
                                    nationality = nat_cell.text.strip()
                                else:
                                    nationality = country_code

                # Clean up nationality - extract just the country code if it includes a flag
                if nationality != "Unknown":
                    # If nationality contains text with country code at the end (like " NED" or " GER")
                    nat_parts = nationality.strip().split()
                    if nat_parts:
                        nationality = nat_parts[
                            -1
                        ]  # Take the last part which should be the code

                # Clean up age value - ensure it's numeric
                if age and age != "Unknown":
                    age_match = re.search(r"(\d+)", age)
                    if age_match:
                        age = age_match.group(1)
                    else:
                        age = "Unknown"

                # Ensure gender is M or F format, not a country code
                if gender not in ["M", "F", "m", "f", "Male", "Female"]:
                    # If gender doesn't match expected values, try to correct it
                    # Female runners are less common, so we check for that first
                    if (
                        "F" in gender
                        or "f" in gender
                        or "woman" in gender.lower()
                        or "female" in gender.lower()
                    ):
                        gender = "F"
                    else:
                        gender = "M"  # Default to male if unclear

                # Normalize gender to either "M" or "F"
                if gender.lower() in ["male", "m"]:
                    gender = "M"
                elif gender.lower() in ["female", "f"]:
                    gender = "F"

                # Calculate finish time
                finish_time = 0
                if time_text and time_text.lower() not in ["dnf", "dns", "dq", ""]:
                    finish_time = time2float(time_text)

                # Store result
                result = {
                    "time": finish_time,
                    #'name': runner_name,
                    "runner_id": runner_id,
                    "nationality": nationality.strip(),
                    "gender": gender,
                    #'rank': rank
                }

                race_info["Results"].append(result)

                # Update statistics
                for field, value in [
                    ("Country", nationality.strip()),
                    ("Sex", gender),
                    ("Age", age),
                ]:
                    if value and value != "Unknown":
                        if value not in race_info[field]:
                            race_info[field][value] = 0
                        race_info[field][value] += 1

            except Exception as e:
                logging.error(f"Error processing row: {str(e)}")
                continue

        return race_info, 200

    except requests.exceptions.RequestException as e:
        logging.error(f"Request error: {str(e)}")
        return {}, 404
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return {}, 500


def main():
    """Process ITRA race results grouped by year using per-year UID files"""
    root = Path(__file__).parent
    uids_dir = root / 'result' / 'race-uids'
    data_dir = root / 'result' / 'race-data'
    data_dir.mkdir(parents=True, exist_ok=True)

    uid_files = sorted(uids_dir.glob('itra-uids-*.json'))
    if not uid_files:
        logging.error("No ITRA UID files found in result/race-uids/")
        return

    session = create_session()
    rate_limiter = RateLimiter(rate_per_second=4)

    # Print header for report
    fmt(False)

    total_processed = 0
    total_results = 0
    started_time = time.time()

    for uid_file in uid_files:
        year = int(uid_file.stem.rsplit('-', 1)[-1])

        race_uids_data = json_in(uid_file)
        if not isinstance(race_uids_data, list) or not race_uids_data:
            logging.warning(f"No UIDs in {uid_file.name}, skipping")
            continue

        race_uids = sorted(int(uid) for uid in race_uids_data if str(uid).strip().isdigit())

        results_file = data_dir / f'itra-race-data-{year}.json'
        itra_results = json_in(results_file) or {}

        last_race_uid = max((int(k) for k in itra_results), default=-1)
        logging.info(f"Year {year}: {len(itra_results)} existing results, {len(race_uids)} UIDs")

        race_count = 0

        for race_uid in race_uids:
            itra_key = str(race_uid)

            if race_uid <= last_race_uid or itra_key in itra_results:
                continue

            logging.info(f"Processing race {itra_key} ({year})")
            try:
                race_info, status = scrape_itra_race(race_uid, session, rate_limiter)

                if race_info and race_info.get("Results"):
                    itra_results[itra_key] = race_info
                    content = [
                        "N Results",
                        "Race Category",
                        "Distance",
                        "Race Date",
                        "Results",
                        "Race Title",
                        "City / Country",
                    ]
                    race_count += 1
                    logging.info(
                        f"Successfully processed race {itra_key}: {race_info.get('Race Title', 'Unknown')}"
                    )
                else:
                    content = [""] * 7
                    race_count += 1
                    logging.warning(f"No valid data found for race {itra_key}")

                fmt(
                    race_info,
                    itra_key,
                    *[race_info.get(c, "") for c in content],
                    f"https://itra.run/Races/RaceResults/{race_uid}",
                    status,
                )

                if race_count > 0 and race_count % 500 == 0:
                    json_out(itra_results, results_file)
                    elapsed = time.time() - started_time
                    logging.info(
                        f"Running for {elapsed / 60:.2f} min, {race_count} races in year {year}"
                    )

            except Exception as e:
                logging.error(f"Error processing race {itra_key}: {str(e)}")
                continue

        json_out(itra_results, results_file)
        total_processed += race_count
        total_results += len(itra_results)
        logging.info(f"Year {year}: processed {race_count} new races, total {len(itra_results)}")

    elapsed = time.time() - started_time
    logging.info(f"Script completed in {elapsed / 60:.2f} min. Total races processed: {total_processed}")
    logging.info(f"Total races in dataset: {total_results}")


if __name__ == "__main__":
    main()
