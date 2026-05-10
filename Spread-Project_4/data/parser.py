"""
data/parser.py — XLSX sheet parsers and low-level utilities.
"""
from pathlib import Path

import pandas as pd

from .constants import MONTH_CODES


def _f4(v):
    """Round to 4 decimal places; return None on bad input."""
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _symbol_expiry(symbol: str):
    """Convert e.g. 'LEM26' → sortable int YYYYMM. Returns None if unparseable."""
    if len(symbol) < 4:
        return None
    month_code  = symbol[2]
    year_suffix = symbol[3:]
    month = MONTH_CODES.get(month_code)
    if not month:
        return None
    try:
        return (2000 + int(year_suffix)) * 100 + month
    except ValueError:
        return None


def parse_spread_sheet(xl: pd.ExcelFile, sheet_name: str) -> dict:
    """
    Parse a wide-format spread sheet.

    Layout:
      Row 0  — series names  ("LEJ - LEM (16 Years)", …)
      Row 1  — column headers (Date, Close, Open, High, Low, Spread Year, …)
      Rows 2+ — data, newest-first.  Stride = 7 columns per block.

    Returns {series_prefix: DataFrame[date, close, open, high, low]}.
    """
    raw  = xl.parse(sheet_name, header=None)
    row0 = raw.iloc[0]
    row1 = raw.iloc[1]

    block_starts = [
        i for i, v in enumerate(row1)
        if str(v).strip().lower() == "date"
    ]

    result = {}
    for start in block_starts:
        name_cell = row0.iloc[start]
        if pd.isna(name_cell) or str(name_cell).strip() == "":
            continue
        name  = str(name_cell).strip().replace(" (16 Years)", "")
        block = raw.iloc[2:, start:start + 6].copy()
        block.columns = ["date", "close", "open", "high", "low", "spread_year"]
        block["date"]  = pd.to_datetime(block["date"],  errors="coerce")
        block["close"] = pd.to_numeric(block["close"], errors="coerce").replace(0, float("nan"))
        block["open"]  = pd.to_numeric(block["open"],  errors="coerce")
        block["high"]  = pd.to_numeric(block["high"],  errors="coerce")
        block["low"]   = pd.to_numeric(block["low"],   errors="coerce")
        block = (
            block.dropna(subset=["date", "close"])
                 .sort_values("date")
                 .reset_index(drop=True)
        )
        result[name] = block

    return result


def merge_spread_archive(xl_data: dict, archive_csv: Path) -> dict:
    """
    Merge parse_spread_sheet() output with a long-format archive CSV.

    The archive covers history up to the trim date; xl_data covers the trim
    date onward (currently just the reference row, growing daily).  Both may
    contain the trim date — the XLSX value wins (keep='last' after ascending
    sort puts XLSX rows last because they were appended after the archive rows).
    """
    if not archive_csv.exists():
        return xl_data

    archive = pd.read_csv(archive_csv, parse_dates=["date"])
    archive_by_series = {
        name: grp.drop(columns=["series"]).reset_index(drop=True)
        for name, grp in archive.groupby("series")
    }

    merged = {}
    for series in set(xl_data) | set(archive_by_series):
        frames = [f for f in (archive_by_series.get(series), xl_data.get(series)) if f is not None and len(f) > 0]
        if not frames:
            continue
        combined = pd.concat(frames, ignore_index=True)
        merged[series] = (
            combined.sort_values("date")
                    .drop_duplicates(subset=["date"], keep="last")
                    .reset_index(drop=True)
        )
    return merged


def merge_raw_archive(xl_data: dict, archive_csv: Path) -> dict:
    """
    Merge parse_raw_sheet() output with a long-format archive CSV.

    Same strategy as merge_spread_archive: archive rows first, XLSX rows last,
    dedup by date so XLSX wins on any overlap.
    """
    if not archive_csv.exists():
        return xl_data

    archive = pd.read_csv(archive_csv, parse_dates=["date"])
    archive_by_contract = {
        name: grp.drop(columns=["contract"]).reset_index(drop=True)
        for name, grp in archive.groupby("contract")
    }

    merged = {}
    for contract in set(xl_data) | set(archive_by_contract):
        frames = [f for f in (archive_by_contract.get(contract), xl_data.get(contract)) if f is not None and len(f) > 0]
        if not frames:
            continue
        combined = pd.concat(frames, ignore_index=True)
        merged[contract] = (
            combined.sort_values("date")
                    .drop_duplicates(subset=["date"], keep="last")
                    .reset_index(drop=True)
        )
    return merged


def parse_raw_sheet(xl: pd.ExcelFile, sheet_name: str) -> dict:
    """
    Parse a wide-format raw contract sheet.

    Layout:
      Row 0  — contract name in col 1 of each block
      Row 1  — column headers (Date, Close, Open, High, Low, Change, Volume, OpenInterest, Symbol)
      Rows 2+ — data, newest-first.  Stride = 10 columns per block.

    Returns {symbol: DataFrame[date, close, open, high, low, volume, oi]}.
    """
    raw  = xl.parse(sheet_name, header=None)
    row1 = raw.iloc[1]

    block_starts = [
        i for i, v in enumerate(row1)
        if str(v).strip().lower() == "date"
    ]

    result = {}
    for start in block_starts:
        block = raw.iloc[2:, start:start + 9].copy()
        block.columns = ["date", "close", "open", "high", "low", "change", "volume", "oi", "symbol"]
        block["date"]   = pd.to_datetime(block["date"],   errors="coerce")
        block["close"]  = pd.to_numeric(block["close"],  errors="coerce").replace(0, float("nan"))
        block["volume"] = pd.to_numeric(block["volume"], errors="coerce")
        block["oi"]     = pd.to_numeric(block["oi"],     errors="coerce")
        block = (
            block.dropna(subset=["date", "close"])
                 .sort_values("date")
                 .reset_index(drop=True)
        )
        if len(block) == 0:
            continue
        sym_col = block["symbol"].dropna()
        if len(sym_col) == 0:
            continue
        # Use last (most recent) symbol — the Symbol column changes as contracts roll;
        # iloc[-1] after ascending sort gives the current active contract symbol.
        symbol = str(sym_col.iloc[-1]).strip()
        result[symbol] = block

    return result
