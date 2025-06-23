#!/usr/bin/env python3
# Test ITRA race scraping with a specific race ID
import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))

# Import functions from itra_race_result (replaced hyphen with underscore for import)
from importlib.machinery import SourceFileLoader
itra_module = SourceFileLoader("itra_race_result", "itra-race-result.py").load_module()
scrape_itra_race = itra_module.scrape_itra_race
fmt = itra_module.fmt
json_out = itra_module.json_out

def main():
    # Test with race ID 10 
    race_id = 10
    race_info, status = scrape_itra_race(race_id)
    
    # Print formatted results
    print(f"\n=== Race {race_id} ===")
    fmt(False)  # Print headers
    fmt(race_info, race_id, 'N Results', 'Race Category', 'Race Date', 'Distance', 'Results', 'Race Title', f"https://itra.run/Races/RaceResults/{race_id}", status)
    
    # Print sample of results
    print("\nResults sample (first 3 entries):")
    for i, result in enumerate(race_info.get("Results", [])[:3]):
        print(f"  Runner {i+1}: Time: {result.get('time')} hrs, Name: {result.get('name')}, Nationality: {result.get('nationality')}")
    
    # Print more detailed race info
    print("\nRace Details:")
    print(f"  Race Title: {race_info.get('Race Title')}")
    print(f"  Race Category: {race_info.get('Race Category')}")
    print(f"  Race Date: {race_info.get('Race Date')}")
    print(f"  Distance: {race_info.get('Distance')}")
    print(f"  Elevation Gain: {race_info.get('Elevation Gain')}")
    
    # Save to file for examination
    json_out(race_info, Path.cwd() / f"itra_race_{race_id}_results.json")
    print(f"\nFull results saved to itra_race_{race_id}_results.json")

if __name__ == "__main__":
    main()
