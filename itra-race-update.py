#!/usr/bin/env python3
import json
from pathlib import Path
from itra_fetch_race_details import fetch_race_details
import logging
import time

def update_race_locations():
    """Update existing race data with location information"""
    root = Path.cwd()
    results_file = root / 'itra-race-data-raw.json'
    
    # Load existing results
    with open(results_file, 'r') as f:
        itra_results = json.load(f)
    
    updated_count = 0
    total_processed = 0
    save_interval = 500  # Save every 50 updates
    
    logging.info(f"Starting to update locations for {len(itra_results)} races")
    
    for race_id, race_data in itra_results.items():
        total_processed += 1
        
        # Skip if location already exists and is not "Unknown"
        if race_data.get("City / Country", "Unknown") != "Unknown":
            if total_processed % 100 == 0:  # Log progress every 100 races
                logging.info(f"Progress: {total_processed}/{len(itra_results)} races processed, {updated_count} updated")
            continue
            
        logging.info(f"Updating location for race {race_id} ({total_processed}/{len(itra_results)})")
        
        try:
            # Fetch race details to get location
            detail_data = fetch_race_details(int(race_id))
            
            if detail_data.get("Location", "Unknown") != "Unknown":
                race_data["City / Country"] = detail_data["Location"]
                updated_count += 1
                logging.info(f"Updated race {race_id} with location: {detail_data['Location']}")
            
            # Save periodically to avoid losing progress
            if updated_count > 0 and updated_count % save_interval == 0:
                with open(results_file, 'w') as f:
                    json.dump(itra_results, f, indent=4, sort_keys=True)
                logging.info(f"Saved progress: {updated_count} races updated so far")
            
            # Add small delay to avoid rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            logging.error(f"Error updating race {race_id}: {str(e)}")
            continue
    
    # Save final results
    with open(results_file, 'w') as f:
        json.dump(itra_results, f, indent=4, sort_keys=True)
    
    logging.info(f"Completed! Updated {updated_count} races with location data out of {total_processed} total races")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    update_race_locations()