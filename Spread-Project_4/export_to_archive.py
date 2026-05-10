"""
export_to_archive.py — One-time script to export all XLSX historical data to CSV.

Run ONCE from the project root BEFORE trimming the XLSX:
    python export_to_archive.py

Writes 6 CSV files to data/archive/:
    fat_spreads.csv      — LE spread price history  (series, date, close, open, high, low, spread_year)
    feeder_spreads.csv   — GF spread price history
    fats_raw.csv         — LE individual contract OHLCV (contract, date, close, open, high, low, change, volume, oi, symbol)
    feeders_raw.csv      — GF individual contract OHLCV
    spread_calcs.csv     — Excel-side spread analytics (series, date, zscore_full, roc_5d, roc_10d, ...)
    contract_calcs.csv   — Excel-side contract analytics (contract, date, change_ref, oi_change, ...)

Format notes:
  - All CSVs are long format with an identifier column (series or contract) as the first column.
  - 'series'   = e.g. "LEJ-LEM"   (spread identifier, no spaces around dash in calcs sheets)
  - 'contract' = e.g. "LEM26"     (active contract symbol)
  - Zero-price close values are NaN (parser applies .replace(0, nan) for price sheets).
  - spread_year column is preserved exactly — required for NaN-break injection in build_store().
  - Spread Calcs / Contract Calcs store dates as Excel serial integers; converted via origin 1899-12-30.
"""
from pathlib import Path

import pandas as pd

from config import XLSX_PATH
from data.parser import parse_raw_sheet, parse_spread_sheet

ARCHIVE_DIR = Path(__file__).parent / "data" / "archive"


def _export_spread_sheet(xl: pd.ExcelFile, sheet_name: str, out_path: Path) -> None:
    data = parse_spread_sheet(xl, sheet_name)
    if not data:
        print(f"  WARNING: no data parsed from sheet '{sheet_name}'")
        return

    frames = []
    for series_name, df in data.items():
        df = df.copy()
        df.insert(0, "series", series_name)
        frames.append(df)

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["series", "date"])
        .reset_index(drop=True)
    )
    combined.to_csv(out_path, index=False)

    min_date = combined["date"].min().date()
    max_date = combined["date"].max().date()
    n_series = combined["series"].nunique()
    print(f"  {out_path.name}: {len(combined):,} rows  |  {n_series} series  |  {min_date} -> {max_date}")


def _export_raw_sheet(xl: pd.ExcelFile, sheet_name: str, out_path: Path) -> None:
    data = parse_raw_sheet(xl, sheet_name)
    if not data:
        print(f"  WARNING: no data parsed from sheet '{sheet_name}'")
        return

    frames = []
    for contract, df in data.items():
        df = df.copy()
        df.insert(0, "contract", contract)
        frames.append(df)

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["contract", "date"])
        .reset_index(drop=True)
    )
    combined.to_csv(out_path, index=False)

    min_date = combined["date"].min().date()
    max_date = combined["date"].max().date()
    n_contracts = combined["contract"].nunique()
    print(f"  {out_path.name}: {len(combined):,} rows  |  {n_contracts} contracts  |  {min_date} -> {max_date}")


def _export_calcs_sheet(
    xl: pd.ExcelFile,
    sheet_name: str,
    id_col_name: str,
    data_cols: list,
    out_path: Path,
) -> None:
    """
    Parse a wide-block calcs sheet (Spread Calcs or Contract Calcs).

    Layout mirrors the raw/spread sheets:
      Row 0  — identifier (spread or contract name) in first col of each block
      Row 1  — column headers; first header in each block is "Date"
      Rows 2+ — data, newest-first; dates stored as Excel serial integers

    date conversion: serial days since 1899-12-30 (Excel epoch).
    """
    raw = xl.parse(sheet_name, header=None)
    row0 = raw.iloc[0]
    row1 = raw.iloc[1]

    block_starts = [
        i for i, v in enumerate(row1)
        if str(v).strip().lower() == "date"
    ]

    frames = []
    n_cols = len(data_cols)
    for start in block_starts:
        name_cell = row0.iloc[start]
        if pd.isna(name_cell) or str(name_cell).strip() == "":
            continue
        name = str(name_cell).strip()

        block = raw.iloc[2:, start : start + n_cols].copy()
        block.columns = data_cols

        # Dates arrive as Excel serial floats in these sheets.
        # Guard: serial <= 0 means a blank/zero cell — mask to NaN before converting.
        numeric_dates = pd.to_numeric(block["date"], errors="coerce")
        numeric_dates = numeric_dates.where(numeric_dates > 0)
        block["date"] = pd.to_datetime(
            numeric_dates, unit="D", origin="1899-12-30", errors="coerce"
        ).dt.normalize()  # strip time component → midnight

        for col in data_cols[1:]:
            block[col] = pd.to_numeric(block[col], errors="coerce")

        block = (
            block.dropna(subset=["date"])
                 .sort_values("date")
                 .reset_index(drop=True)
        )
        if len(block) == 0:
            continue

        block.insert(0, id_col_name, name)
        frames.append(block)

    if not frames:
        print(f"  WARNING: no data parsed from sheet '{sheet_name}'")
        return

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values([id_col_name, "date"])
        .reset_index(drop=True)
    )
    combined.to_csv(out_path, index=False)

    min_date = combined["date"].min().date()
    max_date = combined["date"].max().date()
    n_ids = combined[id_col_name].nunique()
    label = "series" if id_col_name == "series" else "contracts"
    print(f"  {out_path.name}: {len(combined):,} rows  |  {n_ids} {label}  |  {min_date} -> {max_date}")


SPREAD_CALCS_COLS = [
    "date", "zscore_full", "roc_5d", "roc_10d",
    "bb_upper_20", "bb_lower_20", "bb_pctb", "bb_width",
    "rsi_14", "vol_20d",
]

CONTRACT_CALCS_COLS = [
    "date", "change_ref", "oi_change", "oi_5d_avg", "vwap_20d", "vol_20d",
]


def main() -> None:
    if not XLSX_PATH.exists():
        print(f"ERROR: XLSX not found at {XLSX_PATH}")
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading: {XLSX_PATH.name}")
    xl = pd.ExcelFile(XLSX_PATH, engine="openpyxl")
    print(f"Sheets:  {xl.sheet_names}\n")
    print(f"Writing to {ARCHIVE_DIR}\n")

    _export_spread_sheet(xl, "Fat Spreads",       ARCHIVE_DIR / "fat_spreads.csv")
    _export_spread_sheet(xl, "Feeder Spreads",    ARCHIVE_DIR / "feeder_spreads.csv")
    _export_raw_sheet(   xl, "Fats Raw Data",     ARCHIVE_DIR / "fats_raw.csv")
    _export_raw_sheet(   xl, "Feeders Raw Data",  ARCHIVE_DIR / "feeders_raw.csv")
    _export_calcs_sheet( xl, "Spread Calcs",   "series",   SPREAD_CALCS_COLS,   ARCHIVE_DIR / "spread_calcs.csv")
    _export_calcs_sheet( xl, "Contract Calcs", "contract", CONTRACT_CALCS_COLS, ARCHIVE_DIR / "contract_calcs.csv")

    print("\nVerify the row counts and date ranges above.")
    print("Each 'max_date' should be 2026-05-08 (last market close).")
    print("Do NOT trim the XLSX until you have confirmed these look correct.")


if __name__ == "__main__":
    main()
