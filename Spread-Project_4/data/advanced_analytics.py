"""
data/advanced_analytics.py — All Python-side advanced calculations.
Called from data/analytics.py::build_store() after base metrics are computed.

Calculation index (matches implementation plan):
  #9b  rolling_zscore          — Z-score vs. rolling 260-day window
  #12  correlation_matrix      — N×N Pearson correlation of daily spread returns
  #13  days_to_expiry          — via contract_calendar
  #14  seasonal_rank           — closest prior year by Pearson correlation
  #16b spread_vwap             — VWAP using average leg volume
  #17  ou_halflife             — Ornstein-Uhlenbeck mean-reversion half-life
  #18  adf_test                — Augmented Dickey-Fuller stationarity
  #19  bollinger_current       — latest Bollinger Band values (from pre-computed calcs)
  #20  regime_conditional      — mean/std split by backwardation vs. contango
  #21  rsi_current             — latest RSI value (from pre-computed calcs)
  #22  roll_yield              — annualised roll yield between two contracts
  #23  skew_kurt               — skewness + excess kurtosis of daily changes
  #24  historical_var          — 1-day VaR at 95% and 99%
  #25  max_drawdown            — peak-to-trough decline over full history
  #26  beta_to_front           — OLS beta of spread changes vs front contract changes
  #27  oi_signature            — classify OI movement as Roll/New Money/Liquidation
  #28  composite_score         — weighted multi-signal score, −3 to +3
  #29  seasonal_perf_index     — monthly mean ± 1σ probability band
  #30  hurst_exponent          — R/S analysis Hurst exponent
  #31  entry_exit_probability  — historical reversion probability by z-score bucket
  #32  curve_convexity         — quadratic coefficient of price vs. contract index
  #33  roll_window_flags       — via contract_calendar.get_roll_window_flags() (not implemented here)
  #34  shadow_convenience_yield — annualised near-term scarcity premium
  #35  pca_on_spreads          — PCA decomposition of spread return matrix
  #36  cot_stats               — from data/cot_manager.py (imported, not duplicated here)
"""
import datetime
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from scipy.cluster.hierarchy import linkage, dendrogram
from scipy.spatial.distance import squareform
from statsmodels.tsa.stattools import adfuller
from sklearn.decomposition import PCA as SklearnPCA

from .contract_calendar import (
    get_days_to_expiry,
    get_roll_window_flags,
    days_between_contracts,
)
from .parser import _f4


# ── #9b Rolling Z-score ───────────────────────────────────────────────────────

def compute_rolling_zscore(series: pd.Series, window: int = 500) -> pd.Series:
    """
    Return a Series of EWM z-scores (span=window).

    Uses exponentially weighted mean/std instead of a simple rolling window.
    This eliminates the SMA 'drop-off cliff': with a fixed window, a large
    shock that was exactly window+1 days ago causes a sudden mean-jump the
    next day even when today's price is unchanged.  EWM smoothly decays the
    weight of old data, anchoring the metric to the structural regime without
    artificial overnight gaps.
    """
    ewm_mean = series.ewm(span=window, adjust=False).mean()
    ewm_std  = series.ewm(span=window, adjust=False).std()
    return ((series - ewm_mean) / ewm_std).round(4)


# ── #12 Correlation Matrix ────────────────────────────────────────────────────

def compute_correlation_matrix(all_spread_dfs: dict) -> dict:
    """
    Compute pairwise Pearson correlation of daily spread-close changes.

    Parameters
    ----------
    all_spread_dfs : {spread_id: DataFrame with columns [date, close, ...]}
                     DataFrames are oldest-first.

    Returns
    -------
    Nested dict: {spread_id_a: {spread_id_b: float}}
    Empty dict if fewer than 2 spreads have enough data.
    """
    returns = {}
    for sid, df in all_spread_dfs.items():
        if df is None or len(df) < 30:
            continue
        s = df.set_index('date')['close'].diff().dropna()
        if len(s) >= 30:
            returns[sid] = s

    if len(returns) < 2:
        return {}

    combined = pd.DataFrame(returns).dropna()
    if combined.shape[0] < 30:
        return {}

    corr = combined.corr()

    # Hierarchical clustering — reorder rows/cols so correlated spreads cluster together
    try:
        dist = np.clip(1.0 - corr.fillna(0).values, 0, 2)
        np.fill_diagonal(dist, 0)
        dist = (dist + dist.T) / 2          # enforce exact symmetry
        Z    = linkage(squareform(dist), method='average')
        order = dendrogram(Z, no_plot=True)['leaves']
        ordered = [corr.index[i] for i in order]
        corr = corr.loc[ordered, ordered]
    except Exception:
        pass                                # fall back to original order on any error

    return {
        a: {b: round(float(corr.loc[a, b]), 4) for b in corr.columns}
        for a in corr.index
    }


# ── #14 Seasonal Rank ─────────────────────────────────────────────────────────

def compute_seasonal_rank(df: pd.DataFrame, regime_series: pd.Series | None = None) -> dict:
    """
    Compare current year's DOY trajectory to every prior year using Pearson
    correlation. When regime_series is provided, boost years with matching
    LE slope sign (×1.15) and penalise mismatched years (×0.85).
    """
    df = df.copy()
    df['doy']  = df['date'].dt.dayofyear
    df['year'] = df['date'].dt.year

    current_year = int(df['year'].max())
    cur = df[df['year'] == current_year][['doy', 'close']].set_index('doy')['close']

    if len(cur) < 10:
        return {"current_year": current_year, "closest_year": None,
                "closest_correlation": None, "rankings": []}

    # Determine current regime sign from regime_series
    cur_regime_sign = None
    if regime_series is not None:
        cur_yr_vals = regime_series[regime_series.index.year == current_year]
        if len(cur_yr_vals) >= 5:
            cur_regime_sign = 1 if float(cur_yr_vals.mean()) > 0 else -1

    rankings = []
    for year, grp in df[df['year'] < current_year].groupby('year'):
        prior = grp.set_index('doy')['close']
        aligned = pd.concat([cur, prior], axis=1, join='inner')
        aligned.columns = ['current', 'prior']
        aligned = aligned.dropna()
        if len(aligned) < 10:
            continue
        corr, _ = scipy_stats.pearsonr(aligned['current'], aligned['prior'])
        if pd.isna(corr):
            continue
        # Regime weighting
        if cur_regime_sign is not None and regime_series is not None:
            yr_vals = regime_series[regime_series.index.year == year]
            if len(yr_vals) >= 5:
                yr_sign = 1 if float(yr_vals.mean()) > 0 else -1
                corr *= 1.15 if yr_sign == cur_regime_sign else 0.85
        rankings.append({"year": int(year), "correlation": round(float(corr), 4)})

    rankings.sort(key=lambda x: x['correlation'], reverse=True)
    if rankings:
        return {
            "current_year":        current_year,
            "closest_year":        rankings[0]['year'],
            "closest_correlation": rankings[0]['correlation'],
            "rankings":            rankings,
        }
    return {"current_year": current_year, "closest_year": None,
            "closest_correlation": None, "rankings": []}


# ── #16b Spread VWAP ──────────────────────────────────────────────────────────

def compute_spread_vwap(
    spread_close_series: pd.Series,
    leg1_df: pd.DataFrame | None,
    leg2_df: pd.DataFrame | None,
    window: int = 20,
) -> float | None:
    """
    Compute a rolling VWAP for a spread using the average volume of its two legs.

    Parameters
    ----------
    spread_close_series : pd.Series indexed by date, oldest-first
    leg1_df, leg2_df    : raw contract DataFrames with [date, close, volume] columns
    window              : rolling window in trading days

    Returns most recent rolling VWAP value or None if data is insufficient.
    """
    if leg1_df is None and leg2_df is None:
        return None

    # Build average-volume series aligned to spread dates
    vol_parts = []
    for raw_df in [leg1_df, leg2_df]:
        if raw_df is not None and 'volume' in raw_df.columns:
            v = raw_df.set_index('date')['volume']
            v = pd.to_numeric(v, errors='coerce')
            vol_parts.append(v)

    if not vol_parts:
        return None

    vol_combined = pd.concat(vol_parts, axis=1, join='outer').mean(axis=1)
    aligned      = pd.concat(
        [spread_close_series.rename('close'), vol_combined.rename('vol')], axis=1, join='inner'
    ).dropna()

    if len(aligned) < window:
        return None

    cv      = aligned['close'] * aligned['vol']
    vwap    = cv.rolling(window).sum() / aligned['vol'].rolling(window).sum()
    last    = vwap.dropna()
    return _f4(float(last.iloc[-1])) if len(last) > 0 else None


# ── #17 O-U Half-Life ─────────────────────────────────────────────────────────

def compute_ou_halflife(series: pd.Series) -> float | None:
    """
    Estimate Ornstein-Uhlenbeck mean-reversion half-life via AR(1) regression.

    Model: Δx_t = α + β·x_{t-1} + ε
    Half-life = −ln(2) / ln(1 + β)

    Returns None when:
    - Fewer than 30 observations
    - β >= 0 (no mean reversion detected)
    - β <= -2 (unstable / explosive)
    - Computed half-life is non-positive or > 1000 trading days
    """
    prices = series.dropna().values
    if len(prices) < 30:
        return None
    lagged = prices[:-1]
    delta  = prices[1:] - prices[:-1]
    slope, _intercept, _r, _p, _se = scipy_stats.linregress(lagged, delta)
    if slope >= 0 or slope <= -2:
        return None
    hl = -np.log(2) / np.log(1.0 + slope)
    if hl <= 0 or hl > 1000:
        return None
    return round(float(hl), 2)


# ── #18 ADF Stationarity Test ─────────────────────────────────────────────────

def compute_adf(series: pd.Series) -> dict:
    """
    Run Augmented Dickey-Fuller test for stationarity.

    Returns
    -------
    {
        "adf_stat": float,
        "p_value": float,
        "stationary": bool,      # True when p_value < 0.05
        "critical_1pct": float,
        "critical_5pct": float,
        "n_obs": int
    }
    Empty dict on error.
    """
    clean = series.dropna()
    if len(clean) < 20:
        return {}
    try:
        result = adfuller(clean, autolag='AIC')
        return {
            "adf_stat":      round(float(result[0]), 4),
            "p_value":       round(float(result[1]), 4),
            "stationary":    bool(result[1] < 0.05),
            "critical_1pct": round(float(result[4]['1%']), 4),
            "critical_5pct": round(float(result[4]['5%']), 4),
            "n_obs":         int(result[3]),
        }
    except Exception:
        return {}


# ── #20 Regime-Conditional Stats ──────────────────────────────────────────────

def compute_regime_conditional_stats(
    spread_df: pd.DataFrame,
    le_slope_series: pd.Series,
) -> dict:
    """
    Split spread history by LE market regime (backwardation vs. contango) and
    compute mean/std/count for each regime.

    Parameters
    ----------
    spread_df       : DataFrame with [date, close]. Oldest-first.
    le_slope_series : pd.Series indexed by date with LE front-minus-back values.
                      Positive = backwardation.

    Returns
    -------
    {
        "backwardation": {"mean": float, "std": float, "count": int},
        "contango":      {"mean": float, "std": float, "count": int}
    }
    """
    spread = spread_df.set_index('date')['close']
    aligned = pd.concat(
        [spread.rename('spread'), le_slope_series.rename('slope')], axis=1, join='inner'
    ).dropna()

    back   = aligned[aligned['slope'] > 0]['spread']
    cont   = aligned[aligned['slope'] <= 0]['spread']

    def _stats(s):
        if len(s) < 5:
            return {"mean": None, "std": None, "count": len(s)}
        return {
            "mean":  round(float(s.mean()), 4),
            "std":   round(float(s.std(ddof=1)), 4),
            "count": len(s),
        }

    return {"backwardation": _stats(back), "contango": _stats(cont)}


# ── #22 Roll Yield ────────────────────────────────────────────────────────────

def compute_roll_yield(
    near_symbol: str,
    def_symbol: str,
    near_price: float,
    def_price: float,
    as_of: datetime.date | None = None,
) -> float | None:
    """
    Roll yield as the near-leg premium over the deferred leg, expressed as a
    percentage of the deferred price.  Positive = backwardation (near premium).

    Formula: (near_price - def_price) / |def_price| * 100

    Does not annualise — biological spreads have non-linear, cliff-shaped carry
    that makes annualisation misleading.  Returns None when the near contract
    has fewer than 15 days to expiry (delivery-period noise).
    """
    if near_price is None or near_price <= 0 or def_price is None or def_price == 0:
        return None
    if as_of is None:
        as_of = datetime.date.today()
    dte = get_days_to_expiry(near_symbol, as_of)
    if dte is not None and dte < 15:
        return None
    return round(float((near_price - def_price) / abs(def_price) * 100), 4)


# ── #23 Skewness and Excess Kurtosis ─────────────────────────────────────────

def compute_skew_kurt(series: pd.Series) -> dict:
    """
    Compute skewness and excess kurtosis of daily close-to-close changes.

    Returns
    -------
    {
        "skewness": float,
        "excess_kurtosis": float,   # 0 for normal distribution
        "n_obs": int
    }
    """
    daily_changes = series.diff().dropna()
    if len(daily_changes) < 10:
        return {}
    return {
        "skewness":        round(float(scipy_stats.skew(daily_changes)), 4),
        "excess_kurtosis": round(float(scipy_stats.kurtosis(daily_changes)), 4),
        "n_obs":           len(daily_changes),
    }


# ── #24 Historical VaR ────────────────────────────────────────────────────────

def compute_var(series: pd.Series, contract_dollar_multiplier: int = 400) -> dict:
    """
    Historical Value at Risk from daily close-to-close changes.
    contract_dollar_multiplier: dollars per 1 $/cwt move.
        LE = 40,000 lbs / 100 = 400
        GF = 50,000 lbs / 100 = 500

    Returns
    -------
    {
        "var_1d_95_per_cwt": float,    # 95% 1-day VaR in $/cwt (positive number)
        "var_1d_99_per_cwt": float,
        "var_5d_95_per_cwt": float,    # scaled by sqrt(5)
        "var_1d_95_per_contract": float,
        "var_1d_99_per_contract": float,
        "contract_dollar_multiplier": int,
        "n_obs": int
    }
    """
    daily = series.diff().dropna()
    if len(daily) < 30:
        return {}
    # Long VaR: loss on a long position = left-tail loss (spread falls)
    long_v95 = abs(float(np.percentile(daily, 5)))
    long_v99 = abs(float(np.percentile(daily, 1)))
    long_v5d = long_v95 * np.sqrt(5)
    # Short VaR: loss on a short position = right-tail loss (spread rises)
    short_v95 = abs(float(np.percentile(daily, 95)))
    short_v99 = abs(float(np.percentile(daily, 99)))
    return {
        # Legacy keys kept for backward compatibility
        "var_1d_95_per_cwt":        round(long_v95, 4),
        "var_1d_99_per_cwt":        round(long_v99, 4),
        "var_5d_95_per_cwt":        round(long_v5d, 4),
        "var_1d_95_per_contract":   round(long_v95 * contract_dollar_multiplier, 2),
        "var_1d_99_per_contract":   round(long_v99 * contract_dollar_multiplier, 2),
        # Asymmetric directional VaR
        "long_var_1d_95_per_cwt":   round(long_v95, 4),
        "long_var_1d_99_per_cwt":   round(long_v99, 4),
        "short_var_1d_95_per_cwt":  round(short_v95, 4),
        "short_var_1d_99_per_cwt":  round(short_v99, 4),
        "contract_dollar_multiplier": contract_dollar_multiplier,
        "n_obs":                    len(daily),
    }


# ── #25 Maximum Drawdown ──────────────────────────────────────────────────────

def compute_max_drawdown(series: pd.Series) -> dict:
    """
    Compute the maximum peak-to-trough drawdown over the entire close history.

    Returns
    -------
    {
        "max_drawdown_cwt": float,       # signed (always <= 0)
        "peak_date": str,
        "trough_date": str,
        "duration_calendar_days": int
    }
    """
    s = series.dropna()
    if len(s) < 5:
        return {}
    running_max = s.cummax()
    drawdown    = s - running_max
    min_dd      = float(drawdown.min())
    trough_date = drawdown.idxmin()
    peak_date   = s.loc[:trough_date].idxmax()
    duration    = (trough_date - peak_date).days
    return {
        "max_drawdown_cwt":       round(min_dd, 4),
        "peak_date":              peak_date.strftime('%Y-%m-%d'),
        "trough_date":            trough_date.strftime('%Y-%m-%d'),
        "duration_calendar_days": int(duration),
    }


# ── #26 Beta to Front Contract ────────────────────────────────────────────────

def compute_beta_to_front(
    spread_df: pd.DataFrame,
    front_df:  pd.DataFrame,
) -> dict:
    """
    OLS regression of daily spread-close changes ~ daily front-contract changes.

    Parameters
    ----------
    spread_df : DataFrame with [date, close]. Oldest-first.
    front_df  : DataFrame with [date, close] for the front outright contract.

    Returns
    -------
    {
        "beta": float,
        "r_squared": float,
        "p_value": float,
        "n_obs": int
    }
    Empty dict if fewer than 60 aligned observations.
    """
    s_chg = spread_df.set_index('date')['close'].diff().dropna().rename('spread')
    f_chg = front_df.set_index('date')['close'].diff().dropna().rename('front')
    aligned = pd.concat([s_chg, f_chg], axis=1, join='inner').dropna()
    if len(aligned) < 60:
        return {}
    slope, _intercept, r_val, p_val, _se = scipy_stats.linregress(
        aligned['front'], aligned['spread']
    )
    return {
        "beta":      round(float(slope), 4),
        "r_squared": round(float(r_val ** 2), 4),
        "p_value":   round(float(p_val), 4),
        "n_obs":     len(aligned),
    }


# ── #27 OI Signature Classifier ───────────────────────────────────────────────

def classify_oi_signature(
    near_oi_change: float | None,
    def_oi_change:  float | None,
    threshold: int = 500,
) -> str:
    """
    Classify today's OI movement for an adjacent contract pair.

    Logic:
      ROLL         — nearby OI falls AND deferred OI rises (net transfer)
      NEW_MONEY    — both rise, or deferred rises sharply with total OI growing
      LIQUIDATION  — both fall
      MIXED        — none of the above

    Parameters
    ----------
    near_oi_change : OI change in the nearer-dated contract today
    def_oi_change  : OI change in the farther-dated contract today
    threshold      : minimum absolute change (contracts) to classify as meaningful
    """
    if near_oi_change is None or def_oi_change is None:
        return 'UNKNOWN'
    near_down = near_oi_change < -threshold
    near_up   = near_oi_change >  threshold
    def_down  = def_oi_change  < -threshold
    def_up    = def_oi_change  >  threshold

    if near_down and def_up:
        return 'ROLL'
    if (near_up and def_up) or (not near_down and def_up):
        return 'NEW_MONEY'
    if near_down and def_down:
        return 'LIQUIDATION'
    return 'MIXED'


# ── #28 Composite Signal Score ────────────────────────────────────────────────

def compute_composite_score(
    zscore:          float | None,
    percentile:      float | None,
    roc_5d_vol_norm: float | None,
) -> float | None:
    """
    Weighted composite signal score from −3 (strong buy) to +3 (strong sell).
    Negative = spread is cheap / below average = buy signal.
    Positive = spread is expensive / above average = sell signal.

    Components (all produce positive = expensive = sell):
      zscore:          high z = overbought = positive
      percentile:      high pct = expensive = positive
      vol-norm momentum: positive momentum = positive

    Weights: zscore 40% | percentile 35% | vol-norm momentum 25%
    """
    components = []

    if zscore is not None:
        z_c = np.clip(float(zscore), -3, 3)
        components.append((z_c, 0.40))

    if percentile is not None:
        p_c = (float(percentile) / 50.0 - 1.0) * 3.0
        components.append((np.clip(p_c, -3, 3), 0.35))

    if roc_5d_vol_norm is not None:
        m_c = np.clip(float(roc_5d_vol_norm), -3, 3)
        components.append((m_c, 0.25))

    if len(components) < 2:
        return None

    total_weight = sum(w for _, w in components)
    score = sum(val * w for val, w in components) / total_weight
    return round(float(np.clip(score, -3, 3)), 3)


# ── Fly Kink Z-Score ──────────────────────────────────────────────────────────

def compute_kink_z(
    fly_bare: tuple[str, str, str] | None,
    all_raw:  dict,
) -> float | None:
    """
    Compute the 2-year Z-score of the butterfly fly where the deferred leg
    of a spread is the middle contract.

    fly_bare: (front_bare, mid_bare, back_bare) — e.g. ('LEJ', 'LEM', 'LEQ')
    all_raw:  dict of year-suffixed symbol → DataFrame(date, close, ...)

    Returns None when any leg is missing, data is sparse (<60 aligned rows),
    or the fly has zero variance.
    """
    if fly_bare is None or len(fly_bare) != 3:
        return None

    def _resolve(bare: str) -> str | None:
        product    = bare[:2].upper()
        month_code = bare[2].upper()
        best_sym, best_dt = None, None
        for sym, df in all_raw.items():
            if len(sym) < 3:
                continue
            if sym[:2].upper() != product or sym[2].upper() != month_code:
                continue
            if df is None or len(df) == 0:
                continue
            latest = df['date'].max()
            if pd.notna(latest) and (best_dt is None or latest > best_dt):
                best_dt, best_sym = latest, sym
        return best_sym

    sym_f = _resolve(fly_bare[0])
    sym_m = _resolve(fly_bare[1])
    sym_b = _resolve(fly_bare[2])
    if not (sym_f and sym_m and sym_b):
        return None

    s_f = all_raw[sym_f].set_index('date')['close'].rename('f')
    s_m = all_raw[sym_m].set_index('date')['close'].rename('m')
    s_b = all_raw[sym_b].set_index('date')['close'].rename('b')

    aligned = pd.concat([s_f, s_m, s_b], axis=1, join='inner').dropna()
    if len(aligned) < 60:
        return None

    fly = aligned['f'] - 2 * aligned['m'] + aligned['b']
    window = fly.iloc[-520:]  # ~2 years of trading days
    std = float(window.std(ddof=1))
    if std == 0:
        return None
    z = (float(fly.iloc[-1]) - float(window.mean())) / std
    return round(z, 4)


# ── #32 Curve Convexity ───────────────────────────────────────────────────────

def compute_curve_convexity(sorted_contracts: list[dict]) -> float | None:
    """
    Fit a quadratic P = a·t² + b·t + c to contract prices indexed 0, 1, 2, ...
    Returns the quadratic coefficient `a`.
    Negative a = concave = backwardation accelerating toward the front.
    Positive a = convex  = contango accelerating toward the back.

    Parameters
    ----------
    sorted_contracts : list of dicts with keys 'close' (float) sorted by expiry
                       asc (nearest first).
    """
    valid_contracts = [c for c in sorted_contracts if c.get('close') is not None and c.get('symbol')]
    if len(valid_contracts) < 3:
        return None

    prices = []
    dtes = []
    for c in valid_contracts:
        dte = get_days_to_expiry(c['symbol'])
        if dte is not None and dte >= 0:
            prices.append(c['close'])
            dtes.append(dte)

    if len(dtes) < 3:
        return None

    front_dte = dtes[0]
    t = np.array([dte - front_dte for dte in dtes], dtype=float)
    coef = np.polyfit(t, prices, 2)   # coef[0] = a (quadratic)
    return round(float(coef[0]), 6)


# ── #34 Shadow Convenience Yield ──────────────────────────────────────────────

def compute_shadow_convenience_yield(
    near_symbol: str,
    def_symbol:  str,
    near_price:  float,
    def_price:   float,
    as_of:       datetime.date | None = None,
) -> float | None:
    """
    Annualised shadow convenience yield as a percentage.
    SCY = (near_price − def_price) / def_price × (365 / days_between) × 100

    Returns None if contract symbols are not recognised.
    """
    d_between = days_between_contracts(near_symbol, def_symbol)
    if d_between is None or d_between == 0 or def_price == 0:
        return None
    raw = near_price - def_price
    scy = (raw / def_price) * (365.0 / d_between) * 100.0
    return round(float(scy), 4)


# ── #35 PCA on Spread Matrix ──────────────────────────────────────────────────

def compute_pca_on_spreads(all_spread_dfs: dict) -> dict:
    """
    PCA decomposition of daily spread-return matrix.

    Parameters
    ----------
    all_spread_dfs : {spread_id: DataFrame with [date, close]} oldest-first

    Returns
    -------
    {
        "explained_variance_ratio": [float, ...],
        "cumulative_variance":      [float, ...],
        "components": {
            "PC1": {spread_id: float, ...},
            "PC2": {spread_id: float, ...},
            ...
        },
        "n_spreads": int,
        "n_obs":     int
    }
    Empty dict if fewer than 3 spreads or 60 observations.
    """
    returns = {}
    for sid, df in all_spread_dfs.items():
        if df is None or len(df) < 30:
            continue
        s = df.set_index('date')['close'].diff().dropna()
        if len(s) >= 30:
            returns[sid] = s

    if len(returns) < 3:
        return {}

    combined = pd.DataFrame(returns).dropna()
    if combined.shape[0] < 60:
        return {}

    n_comp = min(5, combined.shape[1])
    pca    = SklearnPCA(n_components=n_comp)
    pca.fit(combined)

    evr  = [round(float(v), 4) for v in pca.explained_variance_ratio_]
    cumv = [round(float(sum(evr[:i + 1])), 4) for i in range(len(evr))]
    comps = {
        f'PC{i + 1}': {
            sid: round(float(pca.components_[i][j]), 4)
            for j, sid in enumerate(combined.columns)
        }
        for i in range(n_comp)
    }

    return {
        "explained_variance_ratio": evr,
        "cumulative_variance":      cumv,
        "components":               comps,
        "n_spreads":                int(combined.shape[1]),
        "n_obs":                    int(combined.shape[0]),
    }
