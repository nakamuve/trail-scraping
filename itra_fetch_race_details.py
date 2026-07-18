#!/usr/bin/env python3
import curl_cffi.requests
from bs4 import BeautifulSoup
import logging
import re
import time


def fetch_race_details(race_id, session=None):
    """Fetch additional race details from the RaceDetails page"""
    url = f"https://itra.run/Races/RaceDetails/{race_id}"

    if session is None:
        session = curl_cffi.requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        })

    logging.info(f"Requesting ITRA race details {race_id} from {url}")

    # Define patterns for extraction
    distance_patterns = [
        r"fa-route[^>]*>.*?Distance:\s*<[^>]*>(\d+(?:\.\d+)?)",  # Match HTML format with icon class
        r"<svg[^>]*fa-route[^>]*>.*?Distance:\s*<span[^>]*>(\d+(?:\.\d+)?)</span>",  # Specific SVG icon format
        r"Distance:\s*<span[^>]*>(\d+(?:\.\d+)?)</span>",  # Specific span format
        r"Distance[:\s]+(\d+(?:\.\d+)?\s*(?:km|kilometers|miles|mi))",  # Text format with units
        r"Length[:\s]+(\d+(?:\.\d+)?\s*(?:km|kilometers|miles|mi))",  # Alternative text format
        r"(\d+(?:\.\d+)?\s*(?:km|kilometers|miles|mi))",  # Generic distance with units
    ]

    elevation_patterns = [
        r"fa-mountain[^>]*>.*?Elevation Gain:\s*<[^>]*>([+]?\d+(?:\.\d+)?)",  # Match HTML format with icon
        r"<svg[^>]*fa-mountain[^>]*>.*?Elevation Gain:\s*<span[^>]*>([+]?\d+)</span>",  # Specific SVG icon format
        r"Elevation Gain:\s*<span[^>]*>([+]?\d+)</span>",  # Specific span format
        r"(?:Elevation|Altitude)[:\s]+(?:Gain|D\+)[:\s]+(\d+(?:\.\d+)?\s*(?:m|meters))",  # Text format with units
        r"D\+[:\s]+(\d+(?:\.\d+)?\s*(?:m|meters))",  # Alternative notation
        r"Elevation[:\s]+(\d+(?:\.\d+)?\s*(?:m|meters))",  # Simple elevation mention
        r"Gain[:\s]+(\d+(?:\.\d+)?\s*(?:m|meters))",  # Simple gain mention
        r"(\d+(?:\.\d+)?\s*(?:m|meters)\s*D\+)",  # Format with D+ after value
        r"[+](\d+(?:\.\d+)?)",  # Just +NNNN format
        r"D[+]\s*(\d+(?:\.\d+)?)",  # D+ format
    ]

    # Define patterns for race date extraction
    date_patterns = [
        r"fa-calendar[^>]*>.*?Race Date:\s*<[^>]*>([^<]+)",  # Match HTML format with calendar icon
        r"<svg[^>]*fa-calendar[^>]*>.*?Race Date:\s*<span[^>]*>([^<]+)</span>",  # Specific SVG icon format
        r"Race Date:\s*<span[^>]*>([^<]+)</span>",  # Specific span format
        r"Race Date[:\s]+(\d{4}/\d{1,2}/\d{1,2})",  # Text format YYYY/MM/DD
        r"Race Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})",  # Text format MM/DD/YYYY
        r"Race Date[:\s]+(\d{1,2}-\d{1,2}-\d{4})",  # Text format MM-DD-YYYY
        r"Date[:\s]+(\d{4}/\d{1,2}/\d{1,2})",  # Simple date format YYYY/MM/DD
        r"Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})",  # Simple date format MM/DD/YYYY
        r"Date[:\s]+(\d{1,2}-\d{1,2}-\d{4})",  # Simple date format MM-DD-YYYY
    ]

    # Define patterns for location extraction
    location_patterns = [
        r'src="/images/CountryFlags/[^"]*"[^>]*>\s*&nbsp;\s*([^<\n]+)',  # Specific country flag path with &nbsp;
        r'src="/images/CountryFlags/[^"]*"[^>]*>\s*([^<\n]+)',  # Specific country flag path
        r'<img[^>]*src="/images/CountryFlags/[^"]*"[^>]*>[^<]*([^<\n]+)',  # Alternative img tag format
    ]

    try:
        for attempt in range(4):
            response = session.get(url, timeout=30, impersonate='chrome123')

            if response.status_code == 200:
                break

            if response.status_code in (202, 429) and attempt < 3:
                wait = (attempt + 1) * 15  # 15s, 30s, 45s
                logging.warning(
                    f"RATE LIMITED on race details {race_id} (status={response.status_code}). "
                    f"Waiting {wait}s before retry ({attempt+1}/3)."
                )
                time.sleep(wait)
                continue

            logging.warning(
                f"Failed to fetch race details {race_id}, status code: {response.status_code}"
            )
            return {
                "Distance": "Unknown",
                "Elevation Gain": "Unknown",
                "Race Date": "Unknown",
                "Location": "Unknown",
            }

        if response.status_code != 200:
            return {
                "Distance": "Unknown",
                "Elevation Gain": "Unknown",
                "Race Date": "Unknown",
                "Location": "Unknown",
            }

        # Parse the HTML content
        soup = BeautifulSoup(response.text, "html.parser")

        # Initialize results dictionary
        details = {
            "Distance": "Unknown",
            "Elevation Gain": "Unknown",
            "Race Date": "Unknown",
            "Location": "Unknown",
        }

        # Try direct extraction from structured HTML first (based on the example HTML provided)
        distance_elements = soup.select("svg.fa-route, i.fa-route")
        for element in distance_elements:
            parent_div = element.parent
            if parent_div:
                # Look for the bold span that would contain the distance value
                bold_span = parent_div.select_one("span[style*='font-weight:bold']")
                if bold_span and bold_span.text.strip():
                    # Extract the numeric value
                    details["Distance"] = bold_span.text.strip()
                    break

        elevation_elements = soup.select("svg.fa-mountain, i.fa-mountain")
        for element in elevation_elements:
            parent_div = element.parent
            if parent_div and "Elevation Gain" in parent_div.text:
                # Look for the bold span that would contain the elevation value
                bold_span = parent_div.select_one("span[style*='font-weight:bold']")
                if bold_span and bold_span.text.strip():
                    # Extract the numeric value
                    details["Elevation Gain"] = bold_span.text.strip()
                    break

        # Extract race date from calendar icon element
        date_elements = soup.select("svg.fa-calendar, i.fa-calendar")
        for element in date_elements:
            parent_div = element.parent
            if parent_div and "Race Date" in parent_div.text:
                # Look for the bold span that would contain the date value
                bold_span = parent_div.select_one("span[style*='font-weight:bold']")
                if bold_span and bold_span.text.strip():
                    # Extract the date value
                    details["Race Date"] = bold_span.text.strip()
                    break

                # Extract location from event-title section or country flag images
        event_title_section = soup.select_one(".event-title")
        if event_title_section:
            # Look for country flag images followed by location text
            flag_imgs = event_title_section.select("img[src*='CountryFlags']")
            for img in flag_imgs:
                # Get the text immediately following the image
                next_text = img.next_sibling
                if next_text and isinstance(next_text, str):
                    # Clean up the location text
                    location_text = next_text.strip().replace("&nbsp;", " ").strip()
                    if location_text and location_text not in ["", " "]:
                        details["Location"] = location_text
                        break
                # Also check parent element for location text
                parent = img.parent
                if parent:
                    parent_text = parent.get_text().strip()
                    # Look for location pattern in parent text - but exclude footer/legal text
                    if not any(
                        term in parent_text.lower()
                        for term in [
                            "rights reserved",
                            "privacy policy",
                            "terms and conditions",
                            "copyright",
                        ]
                    ):
                        for pattern in location_patterns:
                            location_match = re.search(
                                pattern, str(parent_text), re.IGNORECASE
                            )
                            if location_match:
                                details["Location"] = location_match.group(1).strip()
                                break
                    if details["Location"] != "Unknown":
                        break

        # Fall back to text pattern matching if direct HTML extraction failed
        if (
            details["Distance"] == "Unknown"
            or details["Elevation Gain"] == "Unknown"
            or details["Race Date"] == "Unknown"
            or details["Location"] == "Unknown"
        ):
            # Look for race details in various elements - but exclude footer/legal sections
            race_info_elements = soup.select(
                ".race-info, .event-info, .race-details, div.container"
            )
            for element in race_info_elements:
                element_text = element.get_text()
                # Skip elements that contain legal/footer text
                if any(
                    term in element_text.lower()
                    for term in [
                        "rights reserved",
                        "privacy policy",
                        "terms and conditions",
                        "copyright",
                    ]
                ):
                    continue

                # Extract distance
                for pattern in distance_patterns:
                    distance_matches = re.findall(pattern, str(element), re.IGNORECASE)
                    if distance_matches:
                        details["Distance"] = distance_matches[0].strip()
                        break

                # Extract elevation gain
                for pattern in elevation_patterns:
                    elevation_matches = re.findall(pattern, str(element), re.IGNORECASE)
                    if elevation_matches:
                        details["Elevation Gain"] = elevation_matches[0].strip()
                        break

                # Extract race date
                for pattern in date_patterns:
                    date_matches = re.findall(pattern, str(element), re.IGNORECASE)
                    if date_matches:
                        details["Race Date"] = date_matches[0].strip()
                        break

                for pattern in location_patterns:
                    location_matches = re.findall(pattern, str(element), re.IGNORECASE)
                    if location_matches:
                        details["Location"] = location_matches[0].strip()
                        break

                # If not found in dedicated race info elements, try to find in any div
        if (
            details["Distance"] == "Unknown"
            or details["Elevation Gain"] == "Unknown"
            or details["Race Date"] == "Unknown"
            or details["Location"] == "Unknown"
        ):
            for div in soup.find_all("div"):
                div_text = div.text.strip()

                # Skip very long texts and footer/legal text
                if len(div_text) > 200 or any(
                    term in div_text.lower()
                    for term in [
                        "rights reserved",
                        "privacy policy",
                        "terms and conditions",
                        "copyright",
                    ]
                ):
                    continue

                # Look for distance
                if details["Distance"] == "Unknown":
                    for pattern in distance_patterns:
                        matches = re.findall(pattern, div_text, re.IGNORECASE)
                        if matches:
                            details["Distance"] = matches[0].strip()
                            break

                # Look for elevation gain
                if details["Elevation Gain"] == "Unknown":
                    for pattern in elevation_patterns:
                        matches = re.findall(pattern, div_text, re.IGNORECASE)
                        if matches:
                            details["Elevation Gain"] = matches[0].strip()
                            break

                # Look for race date
                if details["Race Date"] == "Unknown":
                    for pattern in date_patterns:
                        matches = re.findall(pattern, div_text, re.IGNORECASE)
                        if matches:
                            details["Race Date"] = matches[0].strip()
                            break

                # Look for location
                if details["Location"] == "Unknown":
                    for pattern in location_patterns:
                        matches = re.findall(pattern, str(div), re.IGNORECASE)
                        if matches:
                            potential_location = matches[0].strip()
                            # Additional check to ensure it's not footer text
                            if not any(
                                term in potential_location.lower()
                                for term in [
                                    "rights reserved",
                                    "privacy policy",
                                    "terms and conditions",
                                    "copyright",
                                ]
                            ):
                                details["Location"] = potential_location
                                break

        # If still not found, look for simple distance, elevation or date mentions
        if details["Distance"] == "Unknown":
            for div in soup.find_all(["div", "p", "span", "li"]):
                div_text = div.text.strip()
                if len(div_text) < 30 and (
                    "km" in div_text.lower() or "mi" in div_text.lower()
                ):
                    distance_match = re.search(
                        r"(\d+(?:\.\d+)?\s*(?:km|kilometers|miles|mi))",
                        div_text,
                        re.IGNORECASE,
                    )
                    if distance_match:
                        details["Distance"] = distance_match.group(1).strip()
                        break

        if details["Elevation Gain"] == "Unknown":
            for div in soup.find_all(["div", "p", "span", "li"]):
                div_text = div.text.strip()
                if len(div_text) < 50 and (
                    "d+" in div_text.lower()
                    or "m+" in div_text.lower()
                    or "gain" in div_text.lower()
                ):
                    elevation_match = re.search(
                        r"(\d+(?:\.\d+)?\s*(?:m|meters|d\+|m\+))",
                        div_text,
                        re.IGNORECASE,
                    )
                    if elevation_match:
                        details["Elevation Gain"] = elevation_match.group(1).strip()
                        break

        if details["Race Date"] == "Unknown":
            for div in soup.find_all(["div", "p", "span", "li"]):
                div_text = div.text.strip()
                if len(div_text) < 30 and (
                    "date" in div_text.lower() or "calendar" in div_text.lower()
                ):
                    # Try different date formats
                    date_match = re.search(
                        r"(\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-\d{1,2}-\d{4})",
                        div_text,
                    )
                    if date_match:
                        details["Race Date"] = date_match.group(1).strip()
                        break

        # If location still not found, look for simple location mentions
        if details["Location"] == "Unknown":
            for div in soup.find_all(["div", "p", "span", "li"]):
                div_text = div.text.strip()
                # Skip footer/legal text
                if any(
                    term in div_text.lower()
                    for term in [
                        "rights reserved",
                        "privacy policy",
                        "terms and conditions",
                        "copyright",
                    ]
                ):
                    continue

                # Look for location patterns in short text elements
                if len(div_text) < 100:
                    # Check if it contains country/city pattern
                    location_match = re.search(
                        r"([A-Z][a-zA-Z\s]+,\s*[A-Z][a-zA-Z\s]+)", div_text
                    )
                    if location_match and "," in location_match.group(1):
                        # Make sure it's not a date or other non-location text
                        potential_location = location_match.group(1).strip()
                        if not re.search(
                            r"\d{4}|\d{1,2}/\d{1,2}|\d{1,2}-\d{1,2}", potential_location
                        ):
                            details["Location"] = potential_location
                            break

        # If still not found, look for simple distance, elevation or date mentions
        if details["Distance"] == "Unknown":
            for div in soup.find_all(["div", "p", "span", "li"]):
                div_text = div.text.strip()
                if len(div_text) < 30 and (
                    "km" in div_text.lower() or "mi" in div_text.lower()
                ):
                    distance_match = re.search(
                        r"(\d+(?:\.\d+)?\s*(?:km|kilometers|miles|mi))",
                        div_text,
                        re.IGNORECASE,
                    )
                    if distance_match:
                        details["Distance"] = distance_match.group(1).strip()
                        break

        if details["Elevation Gain"] == "Unknown":
            for div in soup.find_all(["div", "p", "span", "li"]):
                div_text = div.text.strip()
                if len(div_text) < 50 and (
                    "d+" in div_text.lower()
                    or "m+" in div_text.lower()
                    or "gain" in div_text.lower()
                ):
                    elevation_match = re.search(
                        r"(\d+(?:\.\d+)?\s*(?:m|meters|d\+|m\+))",
                        div_text,
                        re.IGNORECASE,
                    )
                    if elevation_match:
                        details["Elevation Gain"] = elevation_match.group(1).strip()
                        break

        if details["Race Date"] == "Unknown":
            for div in soup.find_all(["div", "p", "span", "li"]):
                div_text = div.text.strip()
                if len(div_text) < 30 and (
                    "date" in div_text.lower() or "calendar" in div_text.lower()
                ):
                    # Try different date formats
                    date_match = re.search(
                        r"(\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-\d{1,2}-\d{4})",
                        div_text,
                    )
                    if date_match:
                        details["Race Date"] = date_match.group(1).strip()
                        break

                # If location still not found, look for simple location mentions
        if details["Location"] == "Unknown":
            for div in soup.find_all(["div", "p", "span", "li"]):
                div_text = div.text.strip()
                # Skip footer/legal text
                if any(
                    term in div_text.lower()
                    for term in [
                        "rights reserved",
                        "privacy policy",
                        "terms and conditions",
                        "copyright",
                    ]
                ):
                    continue

                # Look for location patterns in short text elements
                if len(div_text) < 100:
                    # Check if it contains country/city pattern
                    location_match = re.search(
                        r"([A-Z][a-zA-Z\s]{2,}(?:,\s*[A-Z][a-zA-Z\s]{2,})*)", div_text
                    )
                    if location_match:
                        potential_location = location_match.group(1).strip()
                        # Make sure it's not a date, number, or other non-location text
                        if (
                            not re.search(
                                r"\d{4}|\d{1,2}/\d{1,2}|\d{1,2}-\d{1,2}|\b\d+\.\d+\b",
                                potential_location,
                            )
                            and len(potential_location) > 2
                            and not potential_location.lower()
                            in ["km", "mi", "miles", "meters", "gain", "elevation"]
                        ):
                            details["Location"] = potential_location
                            break

        # Post-process the extracted data to add units if missing
        if details["Distance"] != "Unknown":
            # If we have a plain number without units, add "km"
            if re.match(r"^\d+(?:\.\d+)?$", details["Distance"]):
                details["Distance"] += " Km"
            # Clean up any + prefix in the distance
            details["Distance"] = details["Distance"].replace("+", "")

        if details["Elevation Gain"] != "Unknown":
            # If the elevation gain starts with + or is just a number, add "m"
            if re.match(r"^[+]?\d+(?:\.\d+)?$", details["Elevation Gain"]):
                details["Elevation Gain"] = f"{details['Elevation Gain']} m"
            # Make sure we're keeping the + if it exists
            if details["Elevation Gain"].startswith("+"):
                # Already has a plus sign, keep it
                pass
            elif re.match(r"^\d+", details["Elevation Gain"]):
                # Numeric without plus, add the plus sign to match format
                details["Elevation Gain"] = "+" + details["Elevation Gain"]

                # Post-process location to only return country name
        if details["Location"] != "Unknown":
            location = details["Location"].strip()

            # Clean up common HTML entities and whitespace
            location = location.replace("&nbsp;", " ").replace("&amp;", "&")
            location = re.sub(r"\s+", " ", location).strip()

            # Additional validation - if location is too short or contains numbers, mark as unknown
            if len(location) < 2:
                details["Location"] = "Unknown"
            else:
                # If location contains multiple commas, extract the country (typically the last meaningful part)
                if "," in location:
                    parts = [part.strip() for part in location.split(",")]
                    # Filter out empty parts and find the country (usually the last part that looks like a country)
                    valid_parts = [
                        part for part in parts if part and len(part.strip()) > 1
                    ]

                    if valid_parts:
                        # Take the last part as it's typically the country
                        country_candidate = valid_parts[-1].strip()

                        # Clean up any trailing punctuation
                        country_candidate = re.sub(
                            r"[.,;:!?]+$", "", country_candidate
                        ).strip()

                        # If it still contains periods or numbers, it might be an address component
                        if "." in country_candidate or re.search(
                            r"\d+", country_candidate
                        ):
                            # Look for a better country candidate in earlier parts
                            for part in reversed(valid_parts[:-1]):
                                clean_part = re.sub(r"[.,;:!?]+$", "", part.strip())
                                if (
                                    len(clean_part) > 2
                                    and not re.search(r"\d+", clean_part)
                                    and "." not in clean_part
                                    and not any(
                                        word.lower() in clean_part.lower()
                                        for word in [
                                            "area",
                                            "gate",
                                            "stadium",
                                            "street",
                                            "road",
                                            "avenue",
                                            "no.",
                                        ]
                                    )
                                ):
                                    country_candidate = clean_part
                                    break

                        details["Location"] = country_candidate.title()
                    else:
                        details["Location"] = "Unknown"
                else:
                    # If no comma, treat the whole string as location, but clean it up
                    location = re.sub(r"[.,;:!?]+$", "", location).strip()
                    if not re.search(r"\d+", location) and "." not in location:
                        details["Location"] = location.title()
                    else:
                        details["Location"] = "Unknown"

        return details

    except Exception as e:
        logging.error(f"Error fetching race details {race_id}: {str(e)}")
        return {
            "Distance": "Unknown",
            "Elevation Gain": "Unknown",
            "Race Date": "Unknown",
            "Location": "Unknown",
        }


if __name__ == "__main__":
    # Set up logging for standalone testing
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # Test with a race ID
    race_id = 27687
    details = fetch_race_details(race_id)
    print(f"Race {race_id} details:")
    print(f"Distance: {details['Distance']}")
    print(f"Elevation Gain: {details['Elevation Gain']}")
    print(f"Race Date: {details['Race Date']}")
    print(f"Location: {details['Location']}")
