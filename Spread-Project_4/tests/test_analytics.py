"""
tests/test_analytics.py — Unit tests for parser utilities and store helpers.
No XLSX required.
"""
import pytest
import pandas as pd

from data.parser import _f4, _symbol_expiry
from data.store  import _parse_md, _parse_year, _build_curve


# ── _f4 ───────────────────────────────────────────────────────────────────────

def test_f4_rounds_to_4_places():
    assert _f4(1.23456789) == 1.2346

def test_f4_exact_value():
    assert _f4(5.0) == 5.0

def test_f4_returns_none_on_none():
    assert _f4(None) is None

def test_f4_returns_none_on_bad_string():
    assert _f4("not a number") is None

def test_f4_handles_integer():
    assert _f4(7) == 7.0


# ── _symbol_expiry ────────────────────────────────────────────────────────────

def test_symbol_expiry_live_cattle():
    assert _symbol_expiry("LEM26") == 202606   # Jun 2026
    assert _symbol_expiry("LEZ26") == 202612   # Dec 2026
    assert _symbol_expiry("LEJ27") == 202704   # Apr 2027

def test_symbol_expiry_feeder_cattle():
    assert _symbol_expiry("GFF27") == 202701   # Jan 2027
    assert _symbol_expiry("GFX26") == 202611   # Nov 2026

def test_symbol_expiry_too_short():
    assert _symbol_expiry("LE") is None
    assert _symbol_expiry("") is None

def test_symbol_expiry_unknown_month_code():
    assert _symbol_expiry("LEA26") is None     # 'A' is not a valid CME month code


# ── _parse_md / _parse_year ───────────────────────────────────────────────────

def test_parse_md_extracts_month_day():
    assert _parse_md("2026-05-05") == (5, 5)
    assert _parse_md("2026-01-31") == (1, 31)

def test_parse_year_extracts_year():
    assert _parse_year("2026-05-05") == 2026
    assert _parse_year("2010-12-01") == 2010


# ── _build_curve ──────────────────────────────────────────────────────────────

def test_build_curve_sorts_by_expiry():
    contracts = {
        "LEZ26": {"close": 180.0, "change": 0.5, "volume": 1000, "oi": 5000, "date": "2026-05-05"},
        "LEM26": {"close": 175.0, "change": 0.2, "volume": 2000, "oi": 8000, "date": "2026-05-05"},
        "LEJ26": {"close": 172.0, "change": 0.1, "volume": 3000, "oi": 9000, "date": "2026-05-05"},
    }
    result = _build_curve(contracts)
    symbols = [r["symbol"] for r in result]
    assert symbols == ["LEJ26", "LEM26", "LEZ26"]

def test_build_curve_removes_expiry_key():
    contracts = {
        "LEM26": {"close": 175.0, "change": None, "volume": None, "oi": None, "date": "2026-05-05"},
    }
    result = _build_curve(contracts)
    assert len(result) == 1
    assert "expiry" not in result[0]

def test_build_curve_skips_unparseable_symbols():
    contracts = {
        "BADONE": {"close": 100.0, "change": None, "volume": None, "oi": None, "date": "2026-05-05"},
    }
    result = _build_curve(contracts)
    assert result == []
