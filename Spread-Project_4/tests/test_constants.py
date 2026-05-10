"""
tests/test_constants.py — Validate the SPREADS definitions and lookup tables.
No XLSX required.
"""
from data.constants import SPREADS, SPREAD_META, PHASE1_IDS, MONTH_CODES, MONTH_NAMES


def test_total_spread_count():
    assert len(SPREADS) == 17


def test_all_spreads_have_required_keys():
    required = {"id", "label", "full", "tier", "type", "phase2"}
    for s in SPREADS:
        missing = required - set(s.keys())
        assert not missing, f"Spread {s.get('id')} missing keys: {missing}"


def test_spread_meta_covers_all_ids():
    ids_in_list = {s["id"] for s in SPREADS}
    assert set(SPREAD_META.keys()) == ids_in_list


def test_phase1_ids_excludes_phase2_spreads():
    for sid in PHASE1_IDS:
        assert not SPREAD_META[sid]["phase2"], f"{sid} is phase2 but in PHASE1_IDS"



def test_tiers_are_1_through_4():
    tiers = {s["tier"] for s in SPREADS}
    assert tiers == {1, 2, 3, 4}


def test_month_codes_are_complete():
    assert len(MONTH_CODES) == 12
    assert set(MONTH_CODES.values()) == set(range(1, 13))


def test_month_names_match_codes():
    assert set(MONTH_NAMES.keys()) == set(MONTH_CODES.keys())


def test_spread_types_are_known():
    valid_types = {"LE", "GF"}
    for s in SPREADS:
        assert s["type"] in valid_types, f"Unknown type '{s['type']}' in spread {s['id']}"
