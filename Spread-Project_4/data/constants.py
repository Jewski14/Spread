"""
data/constants.py — Static spread definitions and CME month-code lookups.
"""
import json
import pathlib

_meta_path = pathlib.Path(__file__).parent.parent / "metadata.json"
SPREADS = json.loads(_meta_path.read_text(encoding="utf-8"))["spreads"]

FLY_MAP: dict[str, tuple[str, str, str]] = {
    # deferred leg is the middle of the fly
    "LEG-LEJ": ("LEG", "LEJ", "LEM"),
    "LEJ-LEM": ("LEJ", "LEM", "LEQ"),
    "LEM-LEQ": ("LEM", "LEQ", "LEV"),
    "LEQ-LEV": ("LEQ", "LEV", "LEZ"),
    "LEQ-LEZ": ("LEQ", "LEZ", "LEG"),
    "LEV-LEZ": ("LEV", "LEZ", "LEG"),
    "LEZ-LEG": ("LEZ", "LEG", "LEJ"),
    "LEG-LEM": ("LEG", "LEM", "LEQ"),
    "LEJ-LEQ": ("LEJ", "LEQ", "LEV"),
    "GFF-GFH": ("GFF", "GFH", "GFJ"),
    "GFH-GFJ": ("GFH", "GFJ", "GFK"),
    "GFJ-GFK": ("GFJ", "GFK", "GFQ"),
    "GFK-GFQ": ("GFK", "GFQ", "GFU"),
    "GFQ-GFU": ("GFQ", "GFU", "GFV"),
    "GFU-GFV": ("GFU", "GFV", "GFX"),
    "GFV-GFX": ("GFV", "GFX", "GFF"),
    "GFX-GFF": ("GFX", "GFF", "GFH"),
}

MONTH_CODES = {
    'F':  1, 'G':  2, 'H':  3, 'J':  4, 'K':  5, 'M':  6,
    'N':  7, 'Q':  8, 'U':  9, 'V': 10, 'X': 11, 'Z': 12,
}

MONTH_NAMES = {
    'F': 'Jan', 'G': 'Feb', 'H': 'Mar', 'J': 'Apr', 'K': 'May', 'M': 'Jun',
    'N': 'Jul', 'Q': 'Aug', 'U': 'Sep', 'V': 'Oct', 'X': 'Nov', 'Z': 'Dec',
}

SPREAD_META = {s["id"]: s for s in SPREADS}
PHASE1_IDS  = [s["id"] for s in SPREADS if not s["phase2"]]
