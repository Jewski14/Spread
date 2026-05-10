"""
data/analytics.py — Cache-building and per-series computation.
Called once at startup (or on /rebuild); results persisted to cache/stats.json.

Fast-path: if the latest date in the source workbook matches the latest date
in the JSON cache, the full rebuild is skipped and the cached data is returned
immediately.  This saves virtually all compute when nothing has changed.
"""
import json
import numpy as np
import pandas as pd

import config
from .constants import SPREADS, SPREAD_META, FLY_MAP
from .parser import _f4, parse_spread_sheet, parse_raw_sheet, merge_spread_archive, merge_raw_archive
from .contract_calendar import (
    get_days_to_expiry, get_roll_window_flags, days_between_contracts,
)
from .cot_manager import parse_cot_sheet, compute_cot_stats
from .advanced_analytics import (
    compute_rolling_zscore,
    compute_correlation_matrix,
    compute_seasonal_rank,
    compute_spread_vwap,
    compute_ou_halflife,
    compute_adf,
    compute_regime_conditional_stats,
    compute_skew_kurt,
    compute_var,
    compute_max_drawdown,
    compute_beta_to_front,
    classify_oi_signature,
    compute_composite_score,
    compute_kink_z,
    compute_curve_convexity,
    compute_roll_yield,
    compute_shadow_convenience_yield,
    compute_pca_on_spreads,
)


# ── Fast-path cache check ──────────────────────────────────────────────────────

def _latest_source_date() -> str | None:
    """
    Return the most-recent date (ISO string) from the Fat Spreads sheet.
    Reads only the single top-left data cell — very fast.
    """
    try:
        xl    = pd.ExcelFile(config.XLSX_PATH)
        names = xl.sheet_names
        sheet = next((n for n in names if 'fat spread' in n.lower()), None)
        if not sheet:
            return None
        raw   = xl.parse(sheet, header=None)
        xl.close()
        # Row index 2 = first data row (newest); col index 0 = Date
        date_val = pd.to_datetime(raw.iloc[2, 0], errors='coerce')
        return date_val.strftime('%Y-%m-%d') if not pd.isna(date_val) else None
    except Exception:
        return None


def _latest_cache_date() -> str | None:
    """Return the most-recent date stored in the JSON cache (series[-1][0])."""
    if not config.CACHE_PATH.exists():
        return None
    try:
        with open(config.CACHE_PATH, encoding='utf-8') as fh:
            cached = json.load(fh)
        for spread_data in cached.get('spreads', {}).values():
            if spread_data and spread_data.get('series'):
                # series is stored oldest-first; last element = newest date
                return spread_data['series'][-1][0]
        return None
    except Exception:
        return None


def is_cache_fresh() -> bool:
    """True when the source workbook's latest date matches the cache."""
    src  = _latest_source_date()
    cach = _latest_cache_date()
    return bool(src and cach and src == cach)


# ── Spread technical indicators (Python-computed) ─────────────────────────────

def _spread_indicators(df: pd.DataFrame) -> tuple[dict, list]:
    """
    Compute spread indicators from an oldest-first DataFrame.
    Returns (latest_calcs dict, calcs_series list-of-lists).

    latest_calcs keys: zscore_full, zscore_struct, roc_5d, roc_20d_vol_norm,
                       roc_60d_vol_norm, vol_20d
    calcs_series columns: [date, zscore_full]
    """
    c = df.set_index('date')['close']

    # Full-history Z-score
    mean_full = c.mean()
    std_full  = c.std(ddof=1)
    zscore_full = ((c - mean_full) / std_full) if std_full != 0 else pd.Series(np.nan, index=c.index)

    # 10-year structural Z-score
    zscore_struct = None
    if len(c) > 0:
        cutoff_10y = c.index[-1] - pd.DateOffset(years=10)
        c_10y = c[c.index >= cutoff_10y]
        std_10y = c_10y.std(ddof=1)
        if std_10y and std_10y != 0:
            zscore_struct = float((c.iloc[-1] - c_10y.mean()) / std_10y)

    roc_5d  = c.diff(5)
    roc_20d = c.diff(20)
    roc_60d = c.diff(60)
    vol20d  = c.diff().rolling(20).std(ddof=1)

    latest_calcs = {}
    calcs_series = []

    if len(c) > 0:
        v20 = vol20d.iloc[-1]
        def _vn(roc_val):
            return _f4(float(roc_val) / float(v20)) if (pd.notna(v20) and v20 != 0 and pd.notna(roc_val)) else None

        latest_calcs = {
            'zscore_full':       _f4(zscore_full.iloc[-1]),
            'zscore_struct':     _f4(zscore_struct),
            'roc_5d':            _f4(roc_5d.iloc[-1]),
            'roc_20d_vol_norm':  _vn(roc_20d.iloc[-1]),
            'roc_60d_vol_norm':  _vn(roc_60d.iloc[-1]),
            'vol_20d':           _f4(v20),
        }
        for dt, z in zscore_full.items():
            calcs_series.append([
                dt.strftime('%Y-%m-%d'),
                _f4(z) if pd.notna(z) else None,
            ])

    return latest_calcs, calcs_series


# ── Main store builder ────────────────────────────────────────────────────────

def build_store() -> dict:
    """
    Read the source workbook, compute all analytics, and return the store dict.

    Fast path: if the source's latest date matches the JSON cache, load and
    return the cache immediately without any re-computation.
    """
    if not config.XLSX_PATH.exists():
        raise FileNotFoundError(
            f"Data file not found: {config.XLSX_PATH}\n"
            "Ensure 'Copy of Cattle_Spreads.xlsx' is in the project root."
        )

    # ── Fast path: data unchanged ─────────────────────────────────────────────
    if is_cache_fresh():
        print("[analytics] Source data unchanged — returning cached results.")
        with open(config.CACHE_PATH, encoding='utf-8') as fh:
            return json.load(fh)

    # ── Parse source sheets ───────────────────────────────────────────────────
    xl    = pd.ExcelFile(config.XLSX_PATH)
    names = xl.sheet_names

    def _find(*keywords):
        for kw in keywords:
            for n in names:
                if kw.lower() in n.lower():
                    return n
        return None

    fat_raw_sheet       = _find('fats raw', 'fat raw')       or names[0]
    fat_spread_sheet    = _find('fat spread')                  or names[1]
    feeder_raw_sheet    = _find('feeders raw', 'feeder raw')  or names[2]
    feeder_spread_sheet = _find('feeder spread')               or names[3]

    fat_spreads    = merge_spread_archive(parse_spread_sheet(xl, fat_spread_sheet),    config.ARCHIVE_DIR / "fat_spreads.csv")
    feeder_spreads = merge_spread_archive(parse_spread_sheet(xl, feeder_spread_sheet), config.ARCHIVE_DIR / "feeder_spreads.csv")
    fat_raw        = merge_raw_archive(   parse_raw_sheet(xl, fat_raw_sheet),           config.ARCHIVE_DIR / "fats_raw.csv")
    feeder_raw     = merge_raw_archive(   parse_raw_sheet(xl, feeder_raw_sheet),        config.ARCHIVE_DIR / "feeders_raw.csv")
    cot_df         = parse_cot_sheet(xl)
    xl.close()

    all_spread_dfs = {**fat_spreads, **feeder_spreads}
    all_raw        = {**fat_raw,     **feeder_raw}

    # ── Support structures ────────────────────────────────────────────────────
    le_slope_series = _build_le_slope_series(fat_raw)
    le_front_symbol = _front_symbol(fat_raw)
    gf_front_symbol = _front_symbol(feeder_raw)
    le_front_df     = fat_raw.get(le_front_symbol)
    gf_front_df     = feeder_raw.get(gf_front_symbol)

    store = {
        "spreads":   {},
        "contracts": {"LE": {}, "GF": {}},
        "portfolio": {},
        "cot":       {},
    }

    # ── Spread analytics ──────────────────────────────────────────────────────
    rw_flags = get_roll_window_flags()   # computed once; same for all spreads

    for s in SPREADS:
        sid = s["id"]
        if s["phase2"]:
            store["spreads"][sid] = None
            continue

        search = sid.replace("-", " - ")
        df = next((v for k, v in all_spread_dfs.items() if k.startswith(search)), None)
        if df is None or len(df) == 0:
            store["spreads"][sid] = None
            continue

        closes = df["close"].dropna()
        series = df.set_index('date')['close']

        # Base series — inject None at contract roll boundaries so Plotly
        # breaks the line instead of drawing a vertical spike across the gap.
        raw_series = []
        _sy_col = df["spread_year"] if "spread_year" in df.columns else None
        _prev_sy = None
        for _r, _c, _sy in zip(
            df["date"], df["close"],
            _sy_col if _sy_col is not None else [None] * len(df)
        ):
            if pd.isna(_r) or pd.isna(_c):
                continue
            if (_prev_sy is not None and _sy is not None
                    and pd.notna(_sy) and pd.notna(_prev_sy)
                    and _sy != _prev_sy):
                raw_series.append([_r.strftime("%Y-%m-%d"), None])
            raw_series.append([_r.strftime("%Y-%m-%d"), _f4(_c)])
            if _sy is not None and pd.notna(_sy):
                _prev_sy = _sy
        seasonal, prior_years = _compute_seasonal(df)
        range16y = {
            "high": _f4(closes.max()),
            "low":  _f4(closes.min()),
            "mean": _f4(closes.mean()),
        }

        # Technical indicators
        latest_calcs, calcs_series = _spread_indicators(df)

        # Rolling z-score (500-day ≈ 2 years) + edge stats
        rolling_z = compute_rolling_zscore(series, window=500)
        rolling_z_series = [
            [d.strftime('%Y-%m-%d'), _f4(v)]
            for d, v in rolling_z.dropna().items()
        ][-750:]
        edge_stats = _compute_edge_stats(series, rolling_z)

        # Seasonal rank (regime-weighted)
        seasonal_rank = compute_seasonal_rank(df, regime_series=le_slope_series)

        # Leg resolution
        leg1_bare, leg2_bare = _spread_legs(sid)
        leg1_sym = _resolve_leg(leg1_bare, all_raw)
        leg2_sym = _resolve_leg(leg2_bare, all_raw)

        # Fly kink Z-score
        fly_bare = FLY_MAP.get(sid)
        kink_z   = compute_kink_z(fly_bare, all_raw) if fly_bare else None

        # OI Signature
        oi_sig = None
        if leg1_sym and leg2_sym:
            l1_oi = all_raw.get(leg1_sym)
            l2_oi = all_raw.get(leg2_sym)
            if l1_oi is not None and l2_oi is not None:
                near_oi = l1_oi['oi'].dropna()
                def_oi  = l2_oi['oi'].dropna()
                near_oi_chg = int(near_oi.iloc[-1] - near_oi.iloc[-2]) if len(near_oi) >= 2 else None
                def_oi_chg  = int(def_oi.iloc[-1]  - def_oi.iloc[-2])  if len(def_oi)  >= 2 else None
                oi_sig = classify_oi_signature(near_oi_chg, def_oi_chg)

        # Roll pressure (only inside GSCI roll window)
        roll_pressure_score = None
        roll_warning        = False
        if rw_flags.get('gsci_active') and leg1_sym and leg2_sym:
            rp_l1 = all_raw.get(leg1_sym)
            rp_l2 = all_raw.get(leg2_sym)
            if (rp_l1 is not None and rp_l2 is not None
                    and 'volume' in rp_l1.columns and 'volume' in rp_l2.columns):
                v1_ser = rp_l1['volume'].dropna()
                v2_ser = rp_l2['volume'].dropna()
                if len(v1_ser) >= 20 and len(v2_ser) >= 20:
                    v1_hist = v1_ser.iloc[-260:].values.astype(float)
                    v2_hist = v2_ser.iloc[-260:].values.astype(float)
                    min_len = min(len(v1_hist), len(v2_hist))
                    v1_h, v2_h = v1_hist[-min_len:], v2_hist[-min_len:]
                    total_h = v1_h + v2_h
                    share_h = np.where(total_h > 0, np.minimum(v1_h, v2_h) / total_h, np.nan)
                    share_h = share_h[~np.isnan(share_h)]
                    if len(share_h) >= 10:
                        vol_share = float(share_h[-1])
                        std_s = float(share_h.std(ddof=1))
                        if std_s > 0:
                            share_z = (vol_share - float(share_h.mean())) / std_s
                            roll_pressure_score = round(float(share_z), 3)
                            roll_warning        = bool(roll_pressure_score > 1.5)

        # VWAP, mean-reversion, risk, and structure analytics
        spread_vwap_20d = compute_spread_vwap(
            series, all_raw.get(leg1_sym), all_raw.get(leg2_sym), window=20
        )
        ou_hl     = compute_ou_halflife(series)
        adf       = compute_adf(series)
        regime_cond = {}
        if le_slope_series is not None:
            try:
                regime_cond = compute_regime_conditional_stats(df, le_slope_series)
            except Exception:
                pass
        skew_kurt  = compute_skew_kurt(series)
        multiplier = 400 if s['type'] == 'LE' else 500
        var_stats  = compute_var(series, contract_dollar_multiplier=multiplier)
        max_dd     = compute_max_drawdown(series)

        front_df = le_front_df if s['type'] == 'LE' else gf_front_df
        beta = {}
        if front_df is not None:
            try:
                beta = compute_beta_to_front(df, front_df)
            except Exception:
                pass

        # Roll yield + SCY (before momentum to allow carry-momo quad)
        scy        = None
        roll_yield = None
        if leg1_sym and leg2_sym:
            near_p = _latest_close(all_raw.get(leg1_sym))
            def_p  = _latest_close(all_raw.get(leg2_sym))
            if near_p is not None and def_p is not None:
                scy        = compute_shadow_convenience_yield(leg1_sym, leg2_sym, near_p, def_p)
                roll_yield = compute_roll_yield(leg1_sym, leg2_sym, near_p, def_p)

        # Composite score
        roc_vol_norm = None
        roc5  = latest_calcs.get('roc_5d')
        vol20 = latest_calcs.get('vol_20d')
        if roc5 is not None and vol20 and vol20 != 0:
            roc_vol_norm = roc5 / vol20
        composite = compute_composite_score(
            zscore=latest_calcs.get('zscore_full'),
            percentile=None,
            roc_5d_vol_norm=roc_vol_norm,
        )

        # Momentum regime
        roc60_vn = latest_calcs.get('roc_60d_vol_norm')
        momentum_regime = 'MIXED'
        if roc_vol_norm is not None and roc60_vn is not None:
            if abs(roc60_vn) > 1.5 and (roc_vol_norm * roc60_vn > 0):
                momentum_regime = 'TRENDING'
            elif abs(roc60_vn) > 0.5 and (roc_vol_norm * roc60_vn < 0):
                momentum_regime = 'MEAN_REVERTING'

        # Carry-momentum quadrant
        roc20_vn = latest_calcs.get('roc_20d_vol_norm')
        carry_momo_quad = None
        if roll_yield is not None and roc20_vn is not None:
            if roll_yield > 0 and roc20_vn > 0:   carry_momo_quad = 'Carry + Momentum'
            elif roll_yield > 0 and roc20_vn < 0: carry_momo_quad = 'Carry Fade'
            elif roll_yield < 0 and roc20_vn > 0: carry_momo_quad = 'Momo vs Carry'
            else:                                  carry_momo_quad = 'Double Headwind'

        # Seasonal sigma (position inside DOY Z-cloud)
        seasonal_sigma = None
        last_dates = df["date"].dropna()
        if len(last_dates) > 0 and len(closes) > 0:
            cur_doy = str(last_dates.iloc[-1].timetuple().tm_yday)
            close_val = float(closes.iloc[-1])
            if cur_doy in seasonal:
                entry = seasonal[cur_doy]
                if len(entry) >= 4 and entry[3] != 0:
                    seasonal_sigma = round((close_val - entry[0]) / entry[3], 4)

        store["spreads"][sid] = {
            "series":               raw_series,
            "seasonal":             seasonal,
            "prior_years":          prior_years,
            "range16y":             range16y,
            "latest_calcs":         latest_calcs,
            "calcs_series":         calcs_series,
            "rolling_zscore_500d":  rolling_z_series,
            "seasonal_rank":        seasonal_rank,
            "seasonal_sigma":       seasonal_sigma,
            "spread_vwap_20d":      spread_vwap_20d,
            "ou_halflife":          ou_hl,
            "adf":                  adf,
            "regime_conditional":   regime_cond,
            "skew_kurt":            skew_kurt,
            "var":                  var_stats,
            "max_drawdown":         max_dd,
            "beta_to_front":        beta,
            "composite_score":      composite,
            "shadow_convenience_yield": scy,
            "roll_yield":           roll_yield,
            "oi_signature":         oi_sig,
            "kink_z":               kink_z,
            "edge_stats":           edge_stats,
            "momentum_regime":      momentum_regime,
            "carry_momo_quad":      carry_momo_quad,
            "roll_pressure_score":  roll_pressure_score,
            "roll_warning":         roll_warning,
        }

    # ── Post-loop: cross-sectional roll-yield rank ────────────────────────────
    ry_vals = {
        sid: d["roll_yield"]
        for sid, d in store["spreads"].items()
        if d and d.get("roll_yield") is not None
    }
    if ry_vals:
        sorted_ry = sorted(ry_vals.values())
        n_ry      = len(sorted_ry)
        for sid, ry in ry_vals.items():
            below = sum(1 for v in sorted_ry if v < ry)
            store["spreads"][sid]["roll_yield_rank"] = round(100 * below / n_ry)

    # ── Contract analytics ────────────────────────────────────────────────────
    for symbol, df in fat_raw.items():
        store["contracts"]["LE"][symbol] = _contract_entry(df, symbol)
    for symbol, df in feeder_raw.items():
        store["contracts"]["GF"][symbol] = _contract_entry(df, symbol)

    # ── Portfolio analytics ───────────────────────────────────────────────────
    phase1_dfs = {
        sid: df
        for sid, df in [
            (s["id"], next(
                (v for k, v in all_spread_dfs.items()
                 if k.startswith(s["id"].replace("-", " - "))),
                None
            ))
            for s in SPREADS if not s["phase2"]
        ]
        if df is not None
    }

    store["portfolio"] = {
        "correlation_matrix":  compute_correlation_matrix(phase1_dfs),
        "pca":                 compute_pca_on_spreads(phase1_dfs),
        "curve_convexity_le":  compute_curve_convexity(_build_sorted_curve(fat_raw)),
        "curve_convexity_gf":  compute_curve_convexity(_build_sorted_curve(feeder_raw)),
    }

    store["cot"] = compute_cot_stats(cot_df)

    return store


# ── Internal helpers ──────────────────────────────────────────────────────────

def _compute_seasonal(df: pd.DataFrame) -> tuple[dict, dict]:
    df = df.copy()
    df["doy"]  = df["date"].dt.dayofyear
    df["year"] = df["date"].dt.year
    seasonal = {}
    for doy, grp in df.groupby("doy"):
        vals = grp["close"].dropna().tolist()
        if vals:
            seasonal[str(doy)] = [
                round(float(np.mean(vals)), 4),
                round(float(np.min(vals)),  4),
                round(float(np.max(vals)),  4),
                round(float(np.std(vals, ddof=1)), 4) if len(vals) >= 2 else 0.0,
            ]
    prior_years = {}
    for year, grp in df.groupby("year"):
        rows = grp[["doy", "close"]].sort_values("doy")
        prior_years[str(year)] = [
            [int(d), _f4(c)]
            for d, c in zip(rows["doy"], rows["close"])
            if pd.notna(c)
        ]
    return seasonal, prior_years


def _compute_edge_stats(series: pd.Series, rolling_z: pd.Series) -> dict:
    """
    For each Z-tier, compute historical forward return statistics from the
    spread's own price history. Used to show expected return and hit-rate
    for the current Z position.

    Z-tier keys: z_gt2, z_1to2, z_neg1to1, z_neg2toneg1, z_lt_neg2
    Returns: {tier_key: {"5d": {"mean": float, "hit_rate": float, "n": int}, ...}}
    """
    aligned = pd.concat(
        [series.rename('close'), rolling_z.rename('z')], axis=1, join='inner'
    ).dropna()
    n = len(aligned)
    if n < 60:
        return {}

    closes = aligned['close'].values.astype(float)
    zs     = aligned['z'].values.astype(float)

    # Vectorised tier assignment using np.digitize
    # bins: -2, -1, 1, 2 → bucket indices 0,1,2,3,4
    tier_idx = np.digitize(zs, bins=[-2.0, -1.0, 1.0, 2.0])
    tier_map  = {0: 'z_lt_neg2', 1: 'z_neg2toneg1', 2: 'z_neg1to1',
                 3: 'z_1to2',    4: 'z_gt2'}
    BULLISH   = {'z_neg2toneg1', 'z_lt_neg2'}

    result: dict = {}
    for h in (5, 10, 20):
        base_idx = np.arange(n - h)
        base_c   = closes[base_idx]
        fwd_c    = closes[base_idx + h]
        with np.errstate(divide='ignore', invalid='ignore'):
            fwd_ret = np.where(base_c != 0, (fwd_c - base_c) / np.abs(base_c), 0.0)
        fwd_ret = np.nan_to_num(fwd_ret, nan=0.0)
        base_tier_idx = tier_idx[base_idx]

        for tidx, tier_key in tier_map.items():
            mask = base_tier_idx == tidx
            arr  = fwd_ret[mask]
            if len(arr) < 10:
                continue
            bullish  = tier_key in BULLISH
            hit_rate = float((arr > 0).mean()) if bullish else float((arr < 0).mean())
            if tier_key not in result:
                result[tier_key] = {}
            result[tier_key][f'{h}d'] = {
                'mean':     round(float(arr.mean()), 6),
                'hit_rate': round(hit_rate, 4),
                'n':        int(len(arr)),
            }

    return result


def _contract_entry(df: pd.DataFrame, symbol: str) -> dict:
    if df is None or len(df) == 0:
        return {}
    df   = df.sort_values("date")
    last = df.iloc[-1]

    change_val = None
    if pd.notna(last.get("change")):
        change_val = _f4(last["change"])
    elif len(df) >= 2:
        prev = df.iloc[-2]["close"]
        if pd.notna(prev) and pd.notna(last["close"]):
            change_val = _f4(last["close"] - prev)

    # OI metrics — mirrors Excel Contract Calcs: OI_Change, OI_5D_Avg
    oi_series = df["oi"].dropna()
    oi_change = None
    oi_5d_avg = None
    if len(oi_series) >= 2:
        oi_change = int(oi_series.iloc[-1] - oi_series.iloc[-2])
    if len(oi_series) >= 5:
        oi_5d_avg = round(float(oi_series.iloc[-5:].mean()), 0)

    # VWAP 20D — mirrors Excel: SUMPRODUCT(close*vol) / SUM(vol) over last 20 rows
    vwap_20d = None
    if "volume" in df.columns:
        w20 = df.tail(20).dropna(subset=["close", "volume"])
        if len(w20) >= 2:
            vol_sum = float(w20["volume"].sum())
            if vol_sum > 0:
                vwap_20d = _f4(float((w20["close"] * w20["volume"]).sum() / vol_sum))

    # Vol 20D — close-to-close std over last 20 daily changes
    vol_20d = None
    chg = df["close"].diff().dropna()
    if len(chg) >= 20:
        vol_20d = _f4(float(chg.iloc[-20:].std(ddof=1)))

    return {
        "date":           last["date"].strftime("%Y-%m-%d"),
        "close":          _f4(last["close"]) if pd.notna(last["close"]) else None,
        "change":         change_val,
        "volume":         int(last["volume"]) if pd.notna(last.get("volume")) else None,
        "oi":             int(last["oi"])     if pd.notna(last.get("oi"))     else None,
        "oi_change":      oi_change,
        "oi_5d_avg":      oi_5d_avg,
        "vwap_20d":       vwap_20d,
        "vol_20d":        vol_20d,
        "days_to_expiry": get_days_to_expiry(symbol),
        "oi_signature":   None,  # requires spread-pair context; Phase 3
    }


def _build_le_slope_series(fat_raw: dict) -> pd.Series | None:
    from .parser import _symbol_expiry
    if not fat_raw:
        return None
    sorted_syms = sorted(fat_raw.keys(), key=lambda s: (_symbol_expiry(s) or 999999))
    if len(sorted_syms) < 2:
        return None
    front_s  = fat_raw[sorted_syms[0]].set_index('date')['close'].rename('front')
    back_s   = fat_raw[sorted_syms[-1]].set_index('date')['close'].rename('back')
    combined = pd.concat([front_s, back_s], axis=1, join='inner').dropna()
    return (combined['front'] - combined['back']).rename('le_slope')


def _front_symbol(raw_dict: dict) -> str | None:
    from .parser import _symbol_expiry
    candidates = {}
    for s in raw_dict:
        exp = _symbol_expiry(s)
        if exp is None:
            continue
        dte = get_days_to_expiry(s)
        if dte is not None and dte >= 15:
            candidates[s] = exp
    if not candidates:
        return None
    return min(candidates, key=candidates.get)


def _latest_close(df: pd.DataFrame | None) -> float | None:
    if df is None or len(df) == 0:
        return None
    val = df.sort_values('date').iloc[-1]['close']
    return float(val) if pd.notna(val) else None


def _build_sorted_curve(raw_dict: dict) -> list[dict]:
    from .parser import _symbol_expiry
    rows = []
    for sym, df in raw_dict.items():
        exp = _symbol_expiry(sym)
        if exp is None or df is None or len(df) == 0:
            continue
        close = _latest_close(df)
        rows.append({"symbol": sym, "expiry": exp, "close": close})
    rows.sort(key=lambda r: r["expiry"])
    return rows


def _spread_legs(spread_id: str) -> tuple[str | None, str | None]:
    parts = spread_id.split('-')
    return (parts[0], parts[1]) if len(parts) == 2 else (None, None)


def _resolve_leg(bare_leg: str | None, all_raw: dict) -> str | None:
    """Map a bare leg prefix ('LEJ') to the year-suffixed key in all_raw ('LEJ27').
    Prefers contracts with >= 15 DTE (avoiding delivery-period noise).
    Falls back to the non-expired contract with the most recent last date."""
    if not bare_leg or len(bare_leg) < 3:
        return None
    product    = bare_leg[:2].upper()
    month_code = bare_leg[2].upper()
    candidates = {}
    for sym, df in all_raw.items():
        if not (len(sym) >= 3 and sym[:2].upper() == product and sym[2].upper() == month_code):
            continue
        if df is None or len(df) == 0:
            continue
        dte = get_days_to_expiry(sym)
        if dte is None or dte <= 0:
            continue
        candidates[sym] = (dte, df['date'].max())
    if not candidates:
        return None
    # Prefer contracts >= 15 DTE; fall back to any positive DTE if none qualify
    active = {s: v for s, v in candidates.items() if v[0] >= 15}
    pool   = active if active else candidates
    return max(pool, key=lambda s: pool[s][1])
