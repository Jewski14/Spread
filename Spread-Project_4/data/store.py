"""
data/store.py — In-memory data store and all public query functions.
Lightweight per-request math on top of the pre-built cache.
"""
import json
from datetime import datetime, timedelta

import config
from .constants import SPREADS, SPREAD_META, MONTH_NAMES
from .analytics import build_store
from .parser import _f4, _symbol_expiry
from .advanced_analytics import compute_composite_score
from .contract_calendar import get_roll_window_flags, get_days_to_expiry

# Single in-process store — populated by load() at startup.
_store: dict = {}


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def load() -> None:
    """Load cache into memory, building it from XLSX if the cache is absent."""
    global _store
    if config.CACHE_PATH.exists():
        try:
            with open(config.CACHE_PATH, encoding="utf-8") as fh:
                _store = json.load(fh)
            return
        except (json.JSONDecodeError, KeyError):
            print("Cache corrupt or stale — rebuilding…")

    _store = build_store()
    config.CACHE_PATH.parent.mkdir(exist_ok=True)
    with open(config.CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(_store, fh)


def rebuild() -> None:
    """Delete the cache and rebuild it from XLSX."""
    if config.CACHE_PATH.exists():
        config.CACHE_PATH.unlink()
    load()


# ── Public query API ──────────────────────────────────────────────────────────

def get_all_spread_chips() -> list[dict]:
    """Return all spreads with current value, percentile, and signal data for Monitor table."""
    result = []
    for s in SPREADS:
        sid = s["id"]
        if s["phase2"]:
            result.append({**s, "close": None, "percentile": None, "date": None,
                           "composite_score": None, "zscore_full": None,
                           "roll_yield": None, "roll_yield_rank": None,
                           "roll_warning": False, "change": None})
            continue
        date_str, close = _current(sid)
        pct = _percentile(sid, close, date_str) if close is not None else None

        spread_data = _store.get("spreads", {}).get(sid, {}) or {}
        lc = spread_data.get("latest_calcs") or {}

        roc_vol_norm = None
        if lc.get('roc_5d') is not None and lc.get('vol_20d') and lc['vol_20d'] != 0:
            roc_vol_norm = lc['roc_5d'] / lc['vol_20d']
        composite = compute_composite_score(
            zscore=lc.get('zscore_full'),
            percentile=pct,
            roc_5d_vol_norm=roc_vol_norm,
        )

        series = _store.get("spreads", {}).get(sid, {}).get("series", [])
        change = None
        if len(series) >= 2 and series[-1][1] is not None and series[-2][1] is not None:
            change = round(series[-1][1] - series[-2][1], 4)

        result.append({
            **s,
            "close":           close,
            "percentile":      pct,
            "date":            date_str,
            "composite_score": composite,
            "zscore_full":     lc.get('zscore_full'),
            "roll_yield":      spread_data.get("roll_yield"),
            "roll_yield_rank": spread_data.get("roll_yield_rank"),
            "roll_warning":    spread_data.get("roll_warning", False),
            "change":          change,
        })
    return result


def get_curve_data() -> tuple[list, list]:
    """Return sorted LE and GF forward-curve contract lists for the monitor view."""
    le_contracts = _store.get("contracts", {}).get("LE", {})
    gf_contracts = _store.get("contracts", {}).get("GF", {})
    return _build_curve(le_contracts), _build_curve(gf_contracts)


def get_spread_research(spread_id: str) -> dict | None:
    """Return the full research payload for a given spread."""
    spread_data = _store.get("spreads", {}).get(spread_id)
    meta        = SPREAD_META.get(spread_id)
    if not spread_data or not meta:
        return None

    date_str, close    = _current(spread_id)
    pct                = _percentile(spread_id, close, date_str)
    dev, seas_mean     = _seasonal_dev(spread_id, close, date_str)
    hi52, lo52         = _range52w(spread_id)

    # Recompute composite with live percentile
    lc = spread_data.get("latest_calcs", {})
    roc_vol_norm = None
    if lc.get('roc_5d') is not None and lc.get('vol_20d') and lc['vol_20d'] != 0:
        roc_vol_norm = lc['roc_5d'] / lc['vol_20d']
    composite_live = compute_composite_score(
        zscore=lc.get('zscore_full'),
        percentile=pct,
        roc_5d_vol_norm=roc_vol_norm,
    )

    # Days to expiry for near/deferred legs
    parts     = spread_id.split('-', 1)
    near_sym  = parts[0] if len(parts) == 2 else None
    def_sym   = parts[1] if len(parts) == 2 else None
    product   = (near_sym[:2].upper() if near_sym else None)
    near_dte  = _find_leg_dte(product, near_sym[2] if near_sym else None)
    deferred_dte = _find_leg_dte(product, def_sym[2] if def_sym else None)

    return {
        # original fields
        "id":            spread_id,
        "meta":          meta,
        "current":       {"date": date_str, "close": close},
        "percentile":    pct,
        "seasonal_dev":  dev,
        "seasonal_mean": seas_mean,
        "range16y":      spread_data.get("range16y"),
        "range52w":      {"high": hi52, "low": lo52},
        "series":        spread_data.get("series"),
        "seasonal":      spread_data.get("seasonal"),
        "prior_years":   spread_data.get("prior_years"),
        # new cached fields (computed once at build time)
        "latest_calcs":          spread_data.get("latest_calcs"),
        "rolling_zscore_500d":   spread_data.get("rolling_zscore_500d"),
        "seasonal_rank":         spread_data.get("seasonal_rank"),
        "spread_vwap_20d":       spread_data.get("spread_vwap_20d"),
        "ou_halflife":           spread_data.get("ou_halflife"),
        "adf":                   spread_data.get("adf"),
        "regime_conditional":    spread_data.get("regime_conditional"),
        "skew_kurt":             spread_data.get("skew_kurt"),
        "var":                   spread_data.get("var"),
        "max_drawdown":          spread_data.get("max_drawdown"),
        "beta_to_front":         spread_data.get("beta_to_front"),
        "composite_score":       composite_live,
        "shadow_convenience_yield": spread_data.get("shadow_convenience_yield"),
        "roll_yield":            spread_data.get("roll_yield"),
        "roll_yield_rank":       spread_data.get("roll_yield_rank"),
        "oi_signature":          spread_data.get("oi_signature"),
        "kink_z":                spread_data.get("kink_z"),
        "edge_stats":            spread_data.get("edge_stats"),
        "momentum_regime":       spread_data.get("momentum_regime"),
        "carry_momo_quad":       spread_data.get("carry_momo_quad"),
        "roll_pressure_score":   spread_data.get("roll_pressure_score"),
        "roll_warning":          spread_data.get("roll_warning"),
        "seasonal_sigma":        spread_data.get("seasonal_sigma"),
        "calcs_series":          spread_data.get("calcs_series"),
        "near_dte":              near_dte,
        "deferred_dte":          deferred_dte,
    }


# ── Per-request lightweight calculations ─────────────────────────────────────

def _find_leg_dte(product: str | None, month_code: str | None) -> int | None:
    """Find smallest positive DTE for the active contract matching product + month_code."""
    if not product or not month_code:
        return None
    contracts = _store.get("contracts", {}).get(product.upper(), {})
    best = None
    for sym, info in contracts.items():
        if len(sym) >= 3 and sym[2].upper() == month_code.upper():
            dte = get_days_to_expiry(sym)
            if dte is not None and dte >= 0:
                if best is None or dte < best:
                    best = dte
    return best


def _current(spread_id: str) -> tuple:
    rows = _store.get("spreads", {}).get(spread_id, {})
    if not rows:
        return None, None
    series = rows.get("series", [])
    if not series:
        return None, None
    last = series[-1]
    return last[0], last[1]


def _percentile(spread_id: str, value, date_str: str):
    """0–100 percentile rank vs same calendar-day closes in prior years."""
    if value is None or date_str is None:
        return None
    rows = _store.get("spreads", {}).get(spread_id, {}).get("series", [])
    if not rows:
        return None
    target = datetime.strptime(date_str, "%Y-%m-%d")
    target_doy = target.timetuple().tm_yday
    
    comparisons = []
    for ds, c in rows:
        if c is None:
            continue
        d = datetime.strptime(ds, "%Y-%m-%d")
        if d.year >= target.year:
            continue
        doy = d.timetuple().tm_yday
        # Handle year-end boundaries (e.g. Dec 31 vs Jan 2)
        doy_diff = min(abs(doy - target_doy), 365 - abs(doy - target_doy))
        if doy_diff <= 3:
            comparisons.append(c)
            
    if len(comparisons) < 5:
        return None
    below = sum(1 for c in comparisons if c < value)
    return round(100 * below / len(comparisons))


def _seasonal_dev(spread_id: str, value, date_str: str) -> tuple:
    """Return (deviation_from_mean, seasonal_mean) for today's DOY."""
    if value is None or date_str is None:
        return None, None
    seasonal = _store.get("spreads", {}).get(spread_id, {}).get("seasonal", {})
    doy      = str(datetime.strptime(date_str, "%Y-%m-%d").timetuple().tm_yday)
    entry    = seasonal.get(doy)
    if not entry:
        return None, None
    mean = entry[0]
    return round(value - mean, 4), round(mean, 4)


def _range52w(spread_id: str) -> tuple:
    """Return (high, low) for the trailing 52 weeks."""
    rows   = _store.get("spreads", {}).get(spread_id, {}).get("series", [])
    if not rows:
        return None, None
    cutoff = datetime.now() - timedelta(weeks=52)
    recent = [
        c for ds, c in rows
        if c is not None and datetime.strptime(ds, "%Y-%m-%d") >= cutoff
    ]
    if not recent:
        return None, None
    return _f4(max(recent)), _f4(min(recent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_md(date_str: str) -> tuple:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d.month, d.day)


def _parse_year(date_str: str) -> int:
    return int(date_str[:4])


def get_portfolio_analytics() -> dict:
    """Return portfolio-level correlation matrix and PCA results."""
    return _store.get("portfolio", {})


def get_cot_status() -> dict:
    """Return current COT positioning statistics."""
    return _store.get("cot", {"available": False})


def get_roll_window_status() -> dict:
    """Return today's GSCI/BCOM roll window flags (always fresh from today's date)."""
    return get_roll_window_flags()


def get_contract_details(product: str, symbol: str) -> dict | None:
    """Return full contract dict including new OI/VWAP/expiry fields."""
    return _store.get("contracts", {}).get(product.upper(), {}).get(symbol)


def _build_curve(contracts: dict) -> list:
    rows = []
    for symbol, info in contracts.items():
        expiry = _symbol_expiry(symbol)
        if expiry is None:
            continue
        month_code = symbol[2] if len(symbol) >= 3 else "?"
        rows.append({
            "symbol": symbol,
            "expiry": expiry,
            "month":  MONTH_NAMES.get(month_code, month_code),
            "close":  info.get("close"),
            "change": info.get("change"),
            "volume": info.get("volume"),
            "oi":     info.get("oi"),
            "date":   info.get("date"),
        })
    rows.sort(key=lambda r: r["expiry"])
    for r in rows:
        del r["expiry"]
    return rows
