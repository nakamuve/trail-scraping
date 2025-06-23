#!/usr/bin/env python3
"""
This script parses the HTML output from a curl command to itra.run/Races/RaceResults
and formats the data in a format compatible with UTMB race results.

Usage:
   curl -s -L -H "User-Agent: Mozilla/5.0..." "https://itra.run/Races/RaceResults/10" | python3 itra-curl-parser.py

Or to save to a file:
   curl -s -L -H "User-Agent: Mozilla/5.0..." "https://itra.run/Races/RaceResults/10" | python3 itra-curl-parser.py > race_10_results.json
"""

import sys
import json
from bs4 import BeautifulSoup
import numpy as np
import re
from typing import Dict, List, Any, Optional

def time2float(time_str: str) -> float:
    """Convert time string (HH:MM:SS) to float hours"""
    try:
        parts = time_str.split(':')
        if len(parts) == 3:  # HH:MM:SS
            hours, minutes, seconds = map(int, parts)
            return hours + minutes/60 + seconds/3600
        elif len(parts) == 2:  # MM:SS
            minutes, seconds = map(int, parts)
            return minutes/60 + seconds/3600
        else:
            return 0
    except (ValueError, AttributeError, TypeError):
        return 0

def parse_html(html_content: str) -> Dict[str, Any]:
    """Parse HTML content and extract race results"""
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Initialize race info dictionary
    race_info = {
        "Race Title": "Unknown ITRA Race",
        "Race Category": "Unknown",
        "Distance": "Unknown",
        "Elevation Gain": "Unknown",
        "Results": [],
        "Country": {},
        "Sex": {},
        "Age": {}
    }
    
    # Try to extract race title
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
    
    # Find the results table
    results_table = soup.find("table", id="RunnerRaceResults")
    
    if not results_table:
        return race_info
    
    # Extract rows (skip the header row)
    rows = results_table.find_all("tr")
    if len(rows) <= 1:  # Only header row or no rows
        return race_info
    
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
                nat_cell = cells[6] if has_subscription_cell or len(cells) >= 7 else cells[5]
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
                    nationality = nat_parts[-1]  # Take the last part which should be the code
            
            # Clean up age value - ensure it's numeric
            if age and age != "Unknown":
                age_match = re.search(r'(\d+)', age)
                if age_match:
                    age = age_match.group(1)
                else:
                    age = "Unknown"
            
            # Ensure gender is M or F format, not a country code
            if gender not in ["M", "F", "m", "f", "Male", "Female"]:
                # If gender doesn't match expected values, try to correct it
                if "F" in gender or "f" in gender or "woman" in gender.lower() or "female" in gender.lower():
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
                'time': finish_time,
                'name': runner_name,
                'runner_id': runner_id,
                'nationality': nationality.strip(),
                'gender': gender,
                'rank': rank
            }
            
            race_info["Results"].append(result)
            
            # Update statistics
            for field, value in [('Country', nationality.strip()), ('Sex', gender), ('Age', age)]:
                if value and value != "Unknown":
                    if value not in race_info[field]:
                        race_info[field][value] = 0
                    race_info[field][value] += 1
            
        except Exception as e:
            sys.stderr.write(f"Error processing row: {str(e)}\n")
            continue
    
    # Try to extract distance from HTML if available
    distance_patterns = [
        r'(\d+(?:\.\d+)?\s*(?:km|kilometers|miles|mi))',
        r'distance[:\s]+(\d+(?:\.\d+)?\s*(?:km|kilometers|miles|mi))',
        r'length[:\s]+(\d+(?:\.\d+)?\s*(?:km|kilometers|miles|mi))'
    ]
    
    for pattern in distance_patterns:
        distance_matches = re.findall(pattern, soup.text, re.IGNORECASE)
        if distance_matches:
            race_info["Distance"] = distance_matches[0]
            break
    
    # Determine race category based on distance if available
    if race_info["Distance"] != "Unknown":
        distance_text = race_info["Distance"].lower()
        distance_value = 0
        try:
            # Extract numeric part
            distance_match = re.search(r'(\d+(?:\.\d+)?)', distance_text)
            if distance_match:
                distance_value = float(distance_match.group(1))
                
                # Determine category based on distance range
                if "km" in distance_text:
                    if distance_value < 45:
                        race_info["Race Category"] = "Trail"
                    elif distance_value < 80:
                        race_info["Race Category"] = "50K"
                    elif distance_value < 110:
                        race_info["Race Category"] = "100K"
                    else:
                        race_info["Race Category"] = "Ultra"
                elif "mi" in distance_text:
                    # Convert miles to km for categorization
                    km_distance = distance_value * 1.60934
                    if km_distance < 45:
                        race_info["Race Category"] = "Trail"
                    elif km_distance < 80:
                        race_info["Race Category"] = "50K"
                    elif km_distance < 110:
                        race_info["Race Category"] = "100K"
                    elif distance_value >= 100:
                        race_info["Race Category"] = "100M"
                    else:
                        race_info["Race Category"] = "Ultra"
        except (ValueError, TypeError) as e:
            sys.stderr.write(f"Could not parse distance: {e}\n")
    
    return race_info

def format_results_table(race_info: Dict[str, Any], max_results: Optional[int] = None) -> str:
    """Format race results as a markdown table"""
    output = []
    
    # Add race info header
    output.append(f"# {race_info['Race Title']}")
    output.append(f"Category: {race_info['Race Category']}")
    output.append(f"Distance: {race_info['Distance']}")
    output.append(f"Total Runners: {race_info['N Results']}")
    output.append("")
    
    # Add results table header
    output.append("| Rank | Runner | Time | Nationality | Gender |")
    output.append("|------|--------|------|------------|--------|")
    
    # Add results rows
    results = race_info['Results']
    if max_results:
        results = results[:max_results]
    
    for result in results:
        # Format time as HH:MM:SS
        hours = int(result['time'])
        minutes = int((result['time'] - hours) * 60)
        seconds = int(((result['time'] - hours) * 60 - minutes) * 60)
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if result['time'] > 0 else "DNF"
        
        output.append(f"| {result['rank']} | {result['name']} | {time_str} | {result['nationality']} | {result['gender']} |")
    
    return "\n".join(output)

def main():
    # Read HTML from stdin
    html_content = sys.stdin.read()
    
    # Parse HTML and extract race data
    race_info = parse_html(html_content)
    
    # Print results as JSON
    json_result = json.dumps(race_info, indent=2)
    print(json_result)
    
    # Uncomment to print as markdown table instead
    # markdown_table = format_results_table(race_info, max_results=20)
    # print(markdown_table)

if __name__ == "__main__":
    main()
