"""
data/cot_manager.py — Reads optional COT (Commitment of Traders) data from
the Excel workbook and computes positioning percentile ranks.

Expected COT sheet layout (user manually maintains this sheet):
  Row 0: headers — Date | LE_MM_Long | LE_MM_Short | GF_MM_Long | GF_MM_Short
  Rows 1+: weekly data, any date order (will be sorted ascending internally)

If the COT sheet does not exist in the workbook, all functions return
{"available": False, ...} and the rest of the pipeline continues normally.
"""
import pandas as pd
import numpy as np


COT_SHEET_NAME = 'COT'


def parse_cot_sheet(xl: pd.ExcelFile) -> pd.DataFrame | None:
    """
    Parse the COT sheet from an open ExcelFile.
    Returns a clean DataFrame indexed by date, or None if the sheet is absent
    or malformed.

    Required columns (case-insensitive):
        Date, LE_MM_Long, LE_MM_Short, GF_MM_Long, GF_MM_Short
    """
    if COT_SHEET_NAME not in xl.sheet_names:
        return None
    try:
        df = xl.parse(COT_SHEET_NAME, header=0)
        df.columns = [str(c).strip().lower() for c in df.columns]
        required = ['date', 'le_mm_long', 'le_mm_short', 'gf_mm_long', 'gf_mm_short']
        if not all(c in df.columns for c in required):
            return None
        df['date']       = pd.to_datetime(df['date'], errors='coerce')
        df['le_mm_long']  = pd.to_numeric(df['le_mm_long'],  errors='coerce')
        df['le_mm_short'] = pd.to_numeric(df['le_mm_short'], errors='coerce')
        df['gf_mm_long']  = pd.to_numeric(df['gf_mm_long'],  errors='coerce')
        df['gf_mm_short'] = pd.to_numeric(df['gf_mm_short'], errors='coerce')
        df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
        df['le_mm_net'] = df['le_mm_long'] - df['le_mm_short']
        df['gf_mm_net'] = df['gf_mm_long'] - df['gf_mm_short']
        return df if len(df) >= 2 else None
    except Exception:
        return None


def _percentile_rank(series: pd.Series, current_val: float) -> float:
    """0-100 percentile rank of current_val vs all prior values in series."""
    prior = series.iloc[:-1].dropna()
    if len(prior) == 0:
        return 50.0
    below = (prior < current_val).sum()
    return round(100 * below / len(prior))


def compute_cot_stats(cot_df: pd.DataFrame | None) -> dict:
    """
    Compute COT positioning statistics from the parsed COT DataFrame.

    Returns:
        {
            "available": bool,
            "latest_date": str|None,
            "le_mm_net": float|None,
            "le_mm_net_percentile": float|None,  # 0-100 vs own history
            "le_mm_net_change_4w": float|None,   # 4-week change (5 rows in weekly data)
            "gf_mm_net": float|None,
            "gf_mm_net_percentile": float|None,
            "gf_mm_net_change_4w": float|None
        }
    """
    if cot_df is None or len(cot_df) == 0:
        return {"available": False, "latest_date": None,
                "le_mm_net": None, "le_mm_net_percentile": None, "le_mm_net_change_4w": None,
                "gf_mm_net": None, "gf_mm_net_percentile": None, "gf_mm_net_change_4w": None}

    le_net = cot_df['le_mm_net']
    gf_net = cot_df['gf_mm_net']

    le_current = float(le_net.iloc[-1])
    gf_current = float(gf_net.iloc[-1])
    le_change  = float(le_net.iloc[-1] - le_net.iloc[-5]) if len(le_net) >= 5 else None
    gf_change  = float(gf_net.iloc[-1] - gf_net.iloc[-5]) if len(gf_net) >= 5 else None

    return {
        "available":             True,
        "latest_date":           cot_df['date'].iloc[-1].strftime('%Y-%m-%d'),
        "le_mm_net":             round(le_current, 0),
        "le_mm_net_percentile":  _percentile_rank(le_net, le_current),
        "le_mm_net_change_4w":   round(le_change, 0) if le_change is not None else None,
        "gf_mm_net":             round(gf_current, 0),
        "gf_mm_net_percentile":  _percentile_rank(gf_net, gf_current),
        "gf_mm_net_change_4w":   round(gf_change, 0) if gf_change is not None else None,
    }
