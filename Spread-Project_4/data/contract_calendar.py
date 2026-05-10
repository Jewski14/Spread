"""
data/contract_calendar.py — CME cattle contract expiry dates and roll window logic.
"""
import datetime
import calendar as _calendar
import numpy as np

# ── Delivery month codes ──────────────────────────────────────────────────────
LE_DELIVERY_MONTHS = {'G': 2, 'J': 4, 'M': 6, 'Q': 8, 'V': 10, 'Z': 12}
GF_DELIVERY_MONTHS = {'F': 1, 'H': 3, 'J': 4, 'K': 5, 'Q': 8, 'U': 9, 'V': 10, 'X': 11}

# ── Roll window parameters (business-day-of-month, 1-indexed) ─────────────────
GSCI_ROLL_START_BD = 5   # GSCI roll begins on 5th business day of month
GSCI_ROLL_END_BD   = 9   # GSCI roll ends on 9th business day of month
BCOM_ROLL_START_BD = 6   # BCOM roll begins on 6th business day of month
BCOM_ROLL_END_BD   = 10  # BCOM roll ends on 10th business day of month


def _last_business_day_of_month(year: int, month: int) -> datetime.date:
    """Return the last business day (Mon-Fri) of the given month."""
    last_day = _calendar.monthrange(year, month)[1]
    d = datetime.date(year, month, last_day)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= datetime.timedelta(days=1)
    return d


def _last_thursday_of_month(year: int, month: int) -> datetime.date:
    """Return the last Thursday (weekday=3) of the given month."""
    last_day = _calendar.monthrange(year, month)[1]
    d = datetime.date(year, month, last_day)
    while d.weekday() != 3:
        d -= datetime.timedelta(days=1)
    return d


def get_expiry_date(symbol: str) -> datetime.date | None:
    """
    Return the approximate last trading day for a CME cattle contract symbol.
    LE (Live Cattle): last business day of delivery month.
    GF (Feeder Cattle): last Thursday of delivery month.
    Returns None for unrecognised symbols.
    """
    if len(symbol) < 4:
        return None
    product    = symbol[:2].upper()   # 'LE' or 'GF'
    month_code = symbol[2].upper()
    year_str   = symbol[3:]
    try:
        year = 2000 + int(year_str)
    except ValueError:
        return None

    if product == 'LE':
        month = LE_DELIVERY_MONTHS.get(month_code)
        if month is None:
            return None
        return _last_business_day_of_month(year, month)

    if product == 'GF':
        month = GF_DELIVERY_MONTHS.get(month_code)
        if month is None:
            return None
        return _last_thursday_of_month(year, month)

    return None


def get_days_to_expiry(symbol: str, as_of: datetime.date | None = None) -> int | None:
    """
    Return calendar days from as_of (default today) to the contract's expiry.
    Returns None if symbol is unrecognised or already expired.
    """
    if as_of is None:
        as_of = datetime.date.today()
    expiry = get_expiry_date(symbol)
    if expiry is None:
        return None
    delta = (expiry - as_of).days
    return delta if delta >= 0 else None


def get_business_day_n_of_month(d: datetime.date) -> int:
    """
    Return the 1-indexed count of business days elapsed in d's month up to and
    including d.  E.g. if d is the 3rd business day of the month, returns 3.
    """
    month_start = d.replace(day=1)
    # numpy.busday_count counts business days in the half-open interval [start, end)
    n = int(np.busday_count(month_start.strftime('%Y-%m-%d'), d.strftime('%Y-%m-%d')))
    # Add 1 because busday_count is exclusive of the end date but we want inclusive
    if np.is_busday(d.strftime('%Y-%m-%d')):
        n += 1
    return max(n, 0)


def get_roll_window_flags(as_of: datetime.date | None = None) -> dict:
    """
    Return a dict describing whether today falls inside the GSCI or BCOM
    cattle roll windows.

    Returns:
        {
            "gsci_active": bool,
            "bcom_active": bool,
            "business_day_n": int,   # 1-indexed business day of month
            "gsci_day": int|None,    # day within GSCI window (1-5) or None
            "bcom_day": int|None,    # day within BCOM window (1-5) or None
            "as_of_date": str        # ISO date string
        }
    """
    if as_of is None:
        as_of = datetime.date.today()
    bd_n = get_business_day_n_of_month(as_of)
    gsci_active = GSCI_ROLL_START_BD <= bd_n <= GSCI_ROLL_END_BD
    bcom_active = BCOM_ROLL_START_BD <= bd_n <= BCOM_ROLL_END_BD
    return {
        "gsci_active":    gsci_active,
        "bcom_active":    bcom_active,
        "business_day_n": bd_n,
        "gsci_day":       (bd_n - GSCI_ROLL_START_BD + 1) if gsci_active else None,
        "bcom_day":       (bd_n - BCOM_ROLL_START_BD + 1) if bcom_active else None,
        "as_of_date":     as_of.strftime('%Y-%m-%d'),
    }


def days_between_contracts(symbol_near: str, symbol_def: str) -> int | None:
    """
    Return the number of calendar days between the expiry of two contracts.
    Returns None if either symbol is unrecognised.
    """
    near_exp = get_expiry_date(symbol_near)
    def_exp  = get_expiry_date(symbol_def)
    if near_exp is None or def_exp is None:
        return None
    return abs((def_exp - near_exp).days)
