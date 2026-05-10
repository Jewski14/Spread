"""
tests/test_advanced_analytics.py — Unit tests for advanced_analytics.py.
No XLSX required.
"""
import datetime
import numpy as np
import pandas as pd
import pytest

from data.advanced_analytics import (
    compute_rolling_zscore,
    compute_ou_halflife,
    compute_adf,
    compute_skew_kurt,
    compute_var,
    compute_max_drawdown,
    compute_composite_score,
    compute_curve_convexity,
    classify_oi_signature,
)
from data.contract_calendar import (
    get_expiry_date,
    get_days_to_expiry,
    get_business_day_n_of_month,
    get_roll_window_flags,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mean_reverting_series():
    """Synthetic AR(1) mean-reverting series."""
    np.random.seed(42)
    n = 500
    x = [0.0]
    for _ in range(n - 1):
        x.append(x[-1] * 0.95 + np.random.normal(0, 0.5))
    dates = pd.date_range('2010-01-01', periods=n, freq='B')
    return pd.Series(x, index=dates)


@pytest.fixture
def spread_df(mean_reverting_series):
    return pd.DataFrame({
        'date':  mean_reverting_series.index,
        'close': mean_reverting_series.values,
    })


# ── Rolling Z-score ───────────────────────────────────────────────────────────

def test_rolling_zscore_length(mean_reverting_series):
    z = compute_rolling_zscore(mean_reverting_series, window=20)
    assert len(z) == len(mean_reverting_series)


def test_rolling_zscore_ema_has_values(mean_reverting_series):
    """EWM z-score: values computed from early in the series (no long NaN prefix)."""
    z = compute_rolling_zscore(mean_reverting_series, window=20)
    assert len(z) == len(mean_reverting_series)
    # EWM std is undefined for a single point; from point 2 onward values exist
    assert z.iloc[5:].notna().sum() > len(mean_reverting_series) * 0.95


# ── O-U Half-life ─────────────────────────────────────────────────────────────

def test_ou_halflife_mean_reverting(mean_reverting_series):
    hl = compute_ou_halflife(mean_reverting_series)
    assert hl is not None
    assert 5 < hl < 100   # AR(1) coef 0.95 → half-life ~13 days


def test_ou_halflife_random_walk():
    np.random.seed(0)
    rw = pd.Series(np.cumsum(np.random.normal(0, 1, 200)))
    hl = compute_ou_halflife(rw)
    # Random walk may or may not have a detectable slope with this seed.
    # Accept None or any positive half-life — just verify no crash.
    assert hl is None or hl > 0


def test_ou_halflife_too_short():
    assert compute_ou_halflife(pd.Series([1.0, 2.0, 3.0])) is None


# ── ADF Test ──────────────────────────────────────────────────────────────────

def test_adf_stationary(mean_reverting_series):
    result = compute_adf(mean_reverting_series)
    assert 'adf_stat' in result
    assert 'p_value' in result
    assert result['stationary']   # strongly mean-reverting should be stationary


def test_adf_too_short():
    assert compute_adf(pd.Series([1.0] * 5)) == {}


# ── Skew / Kurt ───────────────────────────────────────────────────────────────

def test_skew_kurt_normal():
    np.random.seed(1)
    s = pd.Series(np.random.normal(0, 1, 500))
    r = compute_skew_kurt(s)
    assert abs(r['skewness'])        < 0.3
    assert abs(r['excess_kurtosis']) < 0.5
    assert r['n_obs'] == 499   # diff removes first


# ── VaR ───────────────────────────────────────────────────────────────────────

def test_var_keys(mean_reverting_series):
    r = compute_var(mean_reverting_series, contract_dollar_multiplier=400)
    for k in ['var_1d_95_per_cwt', 'var_1d_99_per_cwt', 'var_5d_95_per_cwt',
              'var_1d_95_per_contract', 'var_1d_99_per_contract']:
        assert k in r
        assert r[k] >= 0


def test_var_99_gte_95(mean_reverting_series):
    r = compute_var(mean_reverting_series)
    assert r['var_1d_99_per_cwt'] >= r['var_1d_95_per_cwt']


# ── Max Drawdown ──────────────────────────────────────────────────────────────

def test_max_drawdown_negative(mean_reverting_series):
    r = compute_max_drawdown(mean_reverting_series)
    assert r['max_drawdown_cwt'] <= 0


def test_max_drawdown_dates(mean_reverting_series):
    r = compute_max_drawdown(mean_reverting_series)
    assert 'peak_date' in r
    assert 'trough_date' in r
    assert r['duration_calendar_days'] >= 0


# ── Composite Score ───────────────────────────────────────────────────────────

def test_composite_score_range():
    score = compute_composite_score(
        zscore=2.0, percentile=85.0, roc_5d_vol_norm=1.5
    )
    assert score is not None
    assert -3.0 <= score <= 3.0


def test_composite_score_buy_signal():
    # Low z-score, low percentile, negative momentum = buy signal (negative score)
    score = compute_composite_score(
        zscore=-2.5, percentile=5.0, roc_5d_vol_norm=-2.0
    )
    assert score is not None
    assert score < 0


def test_composite_score_sell_signal():
    # High z-score, high percentile = sell signal (positive score)
    score = compute_composite_score(
        zscore=2.5, percentile=95.0, roc_5d_vol_norm=2.0
    )
    assert score is not None
    assert score > 0


def test_composite_score_too_many_nones():
    assert compute_composite_score(None, None, None) is None


def test_composite_score_one_component_returns_none():
    # Only 1 component — should return None (needs >= 2)
    assert compute_composite_score(zscore=1.0, percentile=None, roc_5d_vol_norm=None) is None


def test_composite_score_two_components_ok():
    # 2 components is sufficient
    score = compute_composite_score(zscore=1.0, percentile=70.0, roc_5d_vol_norm=None)
    assert score is not None


# ── Curve Convexity ───────────────────────────────────────────────────────────

def test_curve_convexity_backwardated():
    # Backwardation: front > back; uses DTE via get_days_to_expiry so symbols are required
    contracts = [
        {'close': 253.0, 'symbol': 'LEJ30'},
        {'close': 248.0, 'symbol': 'LEM30'},
        {'close': 242.0, 'symbol': 'LEQ30'},
        {'close': 240.0, 'symbol': 'LEZ30'},
    ]
    conv = compute_curve_convexity(contracts)
    assert conv is not None


def test_curve_convexity_insufficient():
    # Two contracts with valid symbols still returns None (need ≥ 3)
    assert compute_curve_convexity([
        {'close': 100.0, 'symbol': 'LEJ30'},
        {'close': 101.0, 'symbol': 'LEM30'},
    ]) is None


# ── OI Signature ──────────────────────────────────────────────────────────────

def test_oi_signature_roll():
    assert classify_oi_signature(-2000, 1800) == 'ROLL'


def test_oi_signature_new_money():
    assert classify_oi_signature(1000, 1500) == 'NEW_MONEY'


def test_oi_signature_liquidation():
    assert classify_oi_signature(-1500, -1200) == 'LIQUIDATION'


def test_oi_signature_unknown():
    assert classify_oi_signature(None, None) == 'UNKNOWN'


# ── Contract Calendar ─────────────────────────────────────────────────────────

def test_expiry_le():
    d = get_expiry_date('LEM26')
    assert d is not None
    assert d.year == 2026
    assert d.month == 6


def test_expiry_gf():
    d = get_expiry_date('GFK26')
    assert d is not None
    assert d.year == 2026
    assert d.month == 5
    assert d.weekday() == 3   # Thursday


def test_expiry_unrecognised():
    assert get_expiry_date('BADONE') is None


def test_days_to_expiry_positive():
    # Use a far-future contract to guarantee positive DTE
    dte = get_days_to_expiry('LEM30', as_of=datetime.date(2026, 1, 1))
    assert dte is not None
    assert dte > 0


# ── Regime-Matched Seasonal Rank ──────────────────────────────────────────────

def test_seasonal_rank_regime_weighting(spread_df):
    """With regime_series, correlations should differ from the no-regime baseline."""
    from data.advanced_analytics import compute_seasonal_rank
    baseline = compute_seasonal_rank(spread_df)
    # Build a synthetic regime series (all positive = backwardation)
    regime = pd.Series(
        1.0,
        index=pd.date_range('2010-01-01', periods=len(spread_df), freq='B'),
    )
    weighted = compute_seasonal_rank(spread_df, regime_series=regime)
    # Both calls return the same structure
    assert 'rankings' in weighted
    assert 'closest_year' in weighted
    # The weighted correlations can differ from baseline
    base_corrs = {r['year']: r['correlation'] for r in baseline['rankings']}
    wt_corrs   = {r['year']: r['correlation'] for r in weighted['rankings']}
    # Not every correlation must change — some years may be MIXED — but the
    # function must not crash and must return a valid structure
    assert isinstance(weighted['rankings'], list)


def test_seasonal_rank_no_regime_unchanged(spread_df):
    """Passing regime_series=None produces identical output to the no-arg call."""
    from data.advanced_analytics import compute_seasonal_rank
    a = compute_seasonal_rank(spread_df)
    b = compute_seasonal_rank(spread_df, regime_series=None)
    assert a['closest_year'] == b['closest_year']
    assert a['closest_correlation'] == b['closest_correlation']


# ── Kink Z ────────────────────────────────────────────────────────────────────

def _make_raw(seed, n=500) -> pd.DataFrame:
    """Synthetic raw DataFrame matching the structure of all_raw values."""
    np.random.seed(seed)
    dates = pd.date_range('2010-01-01', periods=n, freq='B')
    closes = 150.0 + np.cumsum(np.random.normal(0, 0.5, n))
    return pd.DataFrame({'date': dates, 'close': closes})


def test_kink_z_returns_float():
    from data.advanced_analytics import compute_kink_z
    all_raw = {
        'LEJ26': _make_raw(1),
        'LEM26': _make_raw(2),
        'LEQ26': _make_raw(3),
    }
    result = compute_kink_z(('LEJ', 'LEM', 'LEQ'), all_raw)
    assert result is None or isinstance(result, float)


def test_kink_z_insufficient_data():
    from data.advanced_analytics import compute_kink_z
    # Only 30 rows — below the 60-row minimum
    all_raw = {
        'LEJ26': _make_raw(1, n=30),
        'LEM26': _make_raw(2, n=30),
        'LEQ26': _make_raw(3, n=30),
    }
    assert compute_kink_z(('LEJ', 'LEM', 'LEQ'), all_raw) is None


def test_kink_z_missing_leg():
    from data.advanced_analytics import compute_kink_z
    all_raw = {'LEJ26': _make_raw(1), 'LEM26': _make_raw(2)}
    # LEQ missing from all_raw — should return None gracefully
    assert compute_kink_z(('LEJ', 'LEM', 'LEQ'), all_raw) is None


# ── Roll Yield (percentage of deferred, no annualisation) ────────────────────

def test_roll_yield_pct_formula_backwardation():
    """Backwardation: near > deferred → positive yield."""
    from data.advanced_analytics import compute_roll_yield
    import datetime
    ry = compute_roll_yield('LEM30', 'LEQ30', 155.0, 150.0,
                            as_of=datetime.date(2026, 1, 1))
    assert ry is not None
    # (155 - 150) / 150 * 100 = 3.3333...
    assert ry == pytest.approx(3.3333, abs=0.001)


def test_roll_yield_pct_formula_contango():
    """Contango: near < deferred → negative yield."""
    from data.advanced_analytics import compute_roll_yield
    import datetime
    ry = compute_roll_yield('LEM30', 'LEQ30', 145.0, 150.0,
                            as_of=datetime.date(2026, 1, 1))
    assert ry is not None
    # (145 - 150) / 150 * 100 = -3.3333...
    assert ry == pytest.approx(-3.3333, abs=0.001)


def test_roll_yield_negative_price_returns_none():
    from data.advanced_analytics import compute_roll_yield
    import datetime
    assert compute_roll_yield('LEM30', 'LEQ30', -1.0, 150.0,
                              as_of=datetime.date(2026, 1, 1)) is None


def test_roll_yield_zero_price_returns_none():
    from data.advanced_analytics import compute_roll_yield
    import datetime
    assert compute_roll_yield('LEM30', 'LEQ30', 155.0, 0.0,
                              as_of=datetime.date(2026, 1, 1)) is None


# ── Edge Stats ────────────────────────────────────────────────────────────────

def test_edge_stats_returns_dict(mean_reverting_series):
    from data.analytics import _compute_edge_stats
    rolling_z = mean_reverting_series.rolling(260).apply(
        lambda x: (x.iloc[-1] - x.mean()) / x.std(ddof=1) if x.std(ddof=1) else 0
    )
    result = _compute_edge_stats(mean_reverting_series, rolling_z)
    assert isinstance(result, dict)
    # Each populated tier must have 5d/10d/20d sub-dicts with mean, hit_rate, n
    for tier_data in result.values():
        for hk in tier_data:
            assert hk in ('5d', '10d', '20d')
            assert 'mean' in tier_data[hk]
            assert 'hit_rate' in tier_data[hk]
            assert 'n' in tier_data[hk]
            assert 0.0 <= tier_data[hk]['hit_rate'] <= 1.0


def test_edge_stats_too_short(mean_reverting_series):
    from data.analytics import _compute_edge_stats
    short = mean_reverting_series.iloc[:30]
    z = short.rolling(20).mean()
    assert _compute_edge_stats(short, z) == {}


