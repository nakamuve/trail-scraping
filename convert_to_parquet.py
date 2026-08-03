#!/usr/bin/env python3
"""Convert ITRA race data from nested JSON to flattened Parquet.

Reads result/race-data/itra-race-data-{year}.json and writes one row per
runner result to an output directory as Parquet files.

Usage:
    uv run convert_to_parquet.py                    # all years
    uv run convert_to_parquet.py --years 2024       # single year
    uv run convert_to_parquet.py --years 2023 2024  # multiple years
    uv run convert_to_parquet.py --limit 1000       # cap rows per year (test)
    uv run convert_to_parquet.py --out data-parquet # custom output dir
"""

import argparse
import json
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


SCHEMA = pa.schema([
    pa.field("race_id", pa.string()),
    pa.field("year", pa.int32()),
    pa.field("race_title", pa.string()),
    pa.field("race_category", pa.string()),
    pa.field("distance", pa.string()),
    pa.field("elevation_gain", pa.string()),
    pa.field("race_date", pa.string()),
    pa.field("city_country", pa.string()),
    pa.field("n_results", pa.int64()),
    pa.field("rank", pa.int64()),
    pa.field("runner_id", pa.string()),
    pa.field("gender", pa.string()),
    pa.field("nationality", pa.string()),
    pa.field("time", pa.float64()),
])


def flatten_year(data: dict, year: int, limit: int | None = None) -> list[dict]:
    """Flatten one year's race data into per-runner rows."""
    rows: list[dict] = []
    for race_id, race in data.items():
        # Race-level metadata (may be missing in some records)
        title = race.get("Race Title") or ""
        category = race.get("Race Category") or ""
        distance = race.get("Distance") or ""
        elevation = race.get("Elevation Gain") or ""
        race_date = race.get("Race Date") or ""
        city_country = race.get("City / Country") or ""
        n_results = race.get("N Results") or 0

        results = race.get("Results") or []
        for rank, result in enumerate(results, start=1):
            # time can be a non-numeric string in rare cases; default to 0
            try:
                time_val = float(result.get("time") or 0.0)
            except (TypeError, ValueError):
                time_val = 0.0
            rows.append({
                "race_id": str(race_id),
                "year": year,
                "race_title": title,
                "race_category": category,
                "distance": distance,
                "elevation_gain": elevation,
                "race_date": race_date,
                "city_country": city_country,
                "n_results": n_results,
                "rank": rank,
                "runner_id": str(result.get("runner_id") or ""),
                "gender": result.get("gender") or "",
                "nationality": result.get("nationality") or "",
                "time": time_val,
            })
            if limit is not None and len(rows) >= limit:
                return rows
    return rows


def main():
    parser = argparse.ArgumentParser(description="Convert ITRA JSON to Parquet")
    parser.add_argument("--years", type=int, nargs="*", default=None,
                        help="Years to convert (default: all found)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap total rows per year (for testing)")
    parser.add_argument("--out", type=str, default="result/race-data-parquet",
                        help="Output directory")
    args = parser.parse_args()

    root = Path(__file__).parent
    data_dir = root / "result" / "race-data"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(data_dir.glob("itra-race-data-*.json"))
    if not files:
        print("No itra-race-data-*.json files found")
        sys.exit(1)

    # Filter by requested years
    if args.years:
        wanted = {str(y) for y in args.years}
        files = [f for f in files if f.stem.rsplit("-", 1)[-1] in wanted]
        if not files:
            print(f"No files match years {args.years}")
            sys.exit(1)

    total_rows = 0
    total_bytes = 0
    started = time.time()

    for f in files:
        try:
            year = int(f.stem.rsplit("-", 1)[-1])
            with open(f) as fh:
                data = json.load(fh)
        except (ValueError, OSError, json.JSONDecodeError) as e:
            print(f"{f.name}: SKIPPED ({e})")
            continue

        rows = flatten_year(data, year, args.limit)
        if not rows:
            print(f"{year}: no rows (file may be empty)")
            continue

        table = pa.Table.from_pylist(rows, schema=SCHEMA)
        out_file = out_dir / f"itra-race-data-{year}.parquet"
        pq.write_table(table, out_file, compression="snappy")

        mb_in = f.stat().st_size / 1e6
        mb_out = out_file.stat().st_size / 1e6
        total_rows += len(rows)
        total_bytes += out_file.stat().st_size
        print(
            f"{year}: {len(rows):>8,} rows | "
            f"json {mb_in:7.1f} MB -> parquet {mb_out:6.1f} MB "
            f"({mb_out/max(mb_in,0.001)*100:5.1f}%)"
        )

    elapsed = time.time() - started
    print(f"\nDone: {total_rows:,} rows in {elapsed:.1f}s")
    print(f"Total parquet size: {total_bytes/1e6:.1f} MB -> {out_dir}")


if __name__ == "__main__":
    main()
