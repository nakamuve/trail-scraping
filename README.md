# Trail Race Data Scraping Tool

A comprehensive tool for scraping and analyzing trail running race data from various platforms including ITRA (International Trail Running Association) and UTMB.world.

## Project Overview

This project provides tools to:
- Systematically scrape trail race information from ITRA and UTMB.world
- Extract race details such as distance, elevation gain, dates, etc.
- Organize and store race data in structured JSON format
- Support for comprehensive analysis of trail running events

## Features

- **Race ID Discovery**: Efficiently enumerate and validate race IDs from both ITRA and UTMB platforms
- **Detailed Race Information**: Extract comprehensive details about each race
- **Parallelized Fetching**: Use multi-threading for efficient data collection with rate limiting
- **Stealthy Scraping**: Implements proper request techniques to avoid rate limiting
- **Data Storage**: Organized storage of race details in JSON format

## Requirements

- Python >= 3.13
- uv (Python package manager)

## Dependencies

- beautifulsoup4 >= 4.13.4
- numpy >= 2.2.5
- requests >= 2.32.3
- scrapling >= 0.2.99
- tqdm >= 4.67.1

## Installation

This project uses `uv` for Python environment and package management.

```bash
# Install uv if not already installed
curl -sSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/username/trail-scraping.git
cd trail-scraping

# Create virtual environment and install dependencies with uv
uv sync

# Activate the virtual environment
source .venv/bin/activate  # On Unix/Linux
# OR
.venv\Scripts\activate  # On Windows
```

## Usage

### ITRA Race Scraping

```bash
python itra.py [--start START_UID] [--end END_UID] [--workers WORKERS] [--debug]
```

Options:
- `--start START_UID`: Start UID (default: 0)
- `--end END_UID`: End UID (default: 150000)
- `--workers WORKERS`: Number of worker threads (default: 5)
- `--debug`: Enable debug logging

### UTMB Race Scraping

```bash
python utmb.py [--start START_UID] [--end END_UID] [--workers WORKERS] [--year-start YEAR_START] [--year-end YEAR_END] [--debug]
```

Options:
- `--start START_UID`: Start UID (default: 0)
- `--end END_UID`: End UID (default: 200000)
- `--workers WORKERS`: Number of worker threads (default: 5)
- `--year-start YEAR_START`: Start year to check (default: 2003)
- `--year-end YEAR_END`: End year to check (default: 2025)
- `--debug`: Enable debug logging

## Project Structure

- `itra.py`: Script for scraping ITRA race data
- `utmb.py`: Script for scraping UTMB race data
- `itra-race-result.py`: Process and analyze ITRA race results
- `utmb-race-result.py`: Process and analyze UTMB race results
- `scripts-used-in-utmb-data-collection.ipynb`: Jupyter notebook with examples and documentation

## Data Storage

- `itra-race-uids.json`: List of valid ITRA race UIDs
- `utmb-race-uids.json`: List of valid UTMB race UIDs
- `itra_race_details/`: Directory containing detailed ITRA race information
- `utmb_race_details/`: Directory containing detailed UTMB race information

## Development

This project uses `uv` for Python environment management which provides faster dependency resolution and installation compared to traditional pip.

```bash
# Update dependencies
uv pip install -e .

# Run tests
python -m unittest discover
```

## License

MIT

## Contributing

[Add Contribution Guidelines]

## Author

Gamalan, May 2025