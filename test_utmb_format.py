#!/usr/bin/env python3

import json
from pathlib import Path

def display_race_info(race_data):
    """
    Display race information including runner details
    """
    for key, value in race_data.items():
        if key == "Results":
            print("\nResults sample (first 3 entries):")
            for i, result in enumerate(value[:3]):
                if isinstance(result, dict):
                    print(f"  Runner {i+1}: Time: {result.get('time')} hrs, Name: {result.get('name')}, ID: {result.get('runner_id')}")
                else:
                    print(f"  Runner {i+1}: Time: {result} hrs (old format)")
        else:
            print(f"{key}: {value}")

# Load the race data
data_path = Path.cwd() / 'utmb-race-data-raw.json'
with open(data_path, 'r') as file:
    all_races = json.load(file)

# Find a race with results
for race_key, race_data in all_races.items():
    if race_data and "Results" in race_data and race_data["Results"]:
        print(f"\n=== Race {race_key} ===")
        display_race_info(race_data)
        # Check if we have the new format (dictionaries) or old format (numbers)
        result_format = "new" if isinstance(race_data["Results"][0], dict) else "old"
        print(f"\nResult format: {result_format}")
        break
