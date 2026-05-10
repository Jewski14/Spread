"""
tests/test_routes.py — Flask route tests.
Health and 404 tests run without XLSX. Data-dependent tests skip when absent.
"""
import json
import pytest
from tests.conftest import requires_xlsx


# ── Always-available routes ───────────────────────────────────────────────────

def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert json.loads(r.data)["status"] == "ok"


def test_api_data_status_returns_status(client):
    r    = client.get("/api/data-status")
    body = json.loads(r.data)
    assert r.status_code == 200
    assert "status" in body
    assert body["status"] in ("LIVE", "STALE", "MISSING")
    assert "age_hours" in body


def test_api_spread_unknown_id_returns_404(client):
    r = client.get("/api/spread/FAKE-SPREAD")
    assert r.status_code == 404


def test_page_spread_unknown_id_returns_404(client):
    r = client.get("/spread/FAKE-SPREAD")
    assert r.status_code == 404


# ── Integration tests (require XLSX) ─────────────────────────────────────────

@requires_xlsx
def test_monitor_page_loads(client):
    r = client.get("/")
    assert r.status_code == 200


@requires_xlsx
def test_research_page_loads(client):
    r = client.get("/spread/LEM-LEQ")
    assert r.status_code == 200


@requires_xlsx
def test_portfolio_page_loads(client):
    r = client.get("/portfolio")
    assert r.status_code == 200


@requires_xlsx
def test_api_curve_returns_expected_keys(client):
    r    = client.get("/api/curve")
    body = json.loads(r.data)
    assert r.status_code == 200
    for key in ("le_curve", "gf_curve", "chips", "regime", "updated"):
        assert key in body, f"Missing key: {key}"


@requires_xlsx
def test_api_curve_regime_has_required_fields(client):
    regime = json.loads(client.get("/api/curve").data)["regime"]
    for field in ("market_structure", "le_slope", "gf_slope", "extremes_count", "extremes_total"):
        assert field in regime, f"Missing regime field: {field}"


@requires_xlsx
def test_api_curve_chips_have_signal_fields(client):
    chips = json.loads(client.get("/api/curve").data)["chips"]
    phase1 = [c for c in chips if not c.get("phase2")]
    assert len(phase1) > 0
    first = phase1[0]
    for field in ("composite_score", "zscore_full", "roll_yield", "change"):
        assert field in first, f"Chip missing signal field: {field}"


@requires_xlsx
def test_api_sidebar_returns_17_spreads(client):
    r = client.get("/api/sidebar")
    assert r.status_code == 200
    assert len(json.loads(r.data)["spreads"]) == 17


@requires_xlsx
def test_api_spread_phase1_returns_core_fields(client):
    body = json.loads(client.get("/api/spread/LEM-LEQ").data)
    assert body.get("phase2") is not True
    for field in ("series", "seasonal", "range16y", "composite_score",
                  "roll_yield", "roll_yield_rank", "near_dte", "deferred_dte",
                  "adf", "max_drawdown", "beta_to_front", "calcs_series",
                  "momentum_regime", "carry_momo_quad",
                  "oi_signature", "kink_z", "edge_stats",
                  "roll_pressure_score", "roll_warning", "seasonal_sigma"):
        assert field in body, f"Missing spread field: {field}"


@requires_xlsx
def test_api_spread_adf_has_full_stats(client):
    adf = json.loads(client.get("/api/spread/LEM-LEQ").data).get("adf", {})
    for field in ("adf_stat", "p_value", "stationary", "critical_1pct", "critical_5pct"):
        assert field in adf, f"Missing ADF field: {field}"


@requires_xlsx
def test_api_spread_max_drawdown_has_dates(client):
    dd = json.loads(client.get("/api/spread/LEM-LEQ").data).get("max_drawdown", {})
    for field in ("max_drawdown_cwt", "peak_date", "trough_date", "duration_calendar_days"):
        assert field in dd, f"Missing drawdown field: {field}"


@requires_xlsx
def test_api_spread_beta_has_p_value(client):
    beta = json.loads(client.get("/api/spread/LEM-LEQ").data).get("beta_to_front", {})
    assert "p_value" in beta


@requires_xlsx
def test_api_spread_latest_calcs_has_zscore_struct(client):
    lc = json.loads(client.get("/api/spread/LEM-LEQ").data).get("latest_calcs", {})
    assert "zscore_struct" in lc
    assert "roc_20d_vol_norm" in lc
    assert "roc_60d_vol_norm" in lc


@requires_xlsx
def test_api_portfolio_returns_expected_keys(client):
    body = json.loads(client.get("/api/portfolio").data)
    assert client.get("/api/portfolio").status_code == 200
    for key in ("correlation_matrix", "pca", "curve_convexity_le", "curve_convexity_gf"):
        assert key in body, f"Missing portfolio key: {key}"


@requires_xlsx
def test_api_roll_windows_has_expected_fields(client):
    body = json.loads(client.get("/api/roll-windows").data)
    assert client.get("/api/roll-windows").status_code == 200
    for field in ("gsci_active", "bcom_active", "business_day_n", "as_of_date"):
        assert field in body, f"Missing roll-windows field: {field}"


@requires_xlsx
def test_api_cot_returns_available_key(client):
    body = json.loads(client.get("/api/cot").data)
    assert client.get("/api/cot").status_code == 200
    assert "available" in body


@requires_xlsx
def test_rebuild_endpoint(client):
    r    = client.post("/rebuild")
    body = json.loads(r.data)
    assert r.status_code == 200
    assert body["status"] == "ok"
