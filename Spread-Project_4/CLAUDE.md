# Spread-Project_4 — Claude Session Instructions

**FIRST ACTION every session:** Read `memory.md` in this directory for complete project context (architecture, all 13 routes, 28 analytics fields, full bug history, session log).

## Memory Update Rule — CRITICAL

**`memory.md` in this project root is the ONLY authoritative memory file.**

Sam switches computers frequently. This file lives on OneDrive and syncs everywhere. The machine-local `.claude/projects/.../memory/` folder does NOT sync — treat it as a disposable cache.

**Every session, when you learn something worth remembering:**
- Write it to `memory.md` here (project root, OneDrive path)
- Do NOT rely on `.claude/projects/.../memory/` as the primary record

**At the end of any session where code changed, bugs were fixed, or design decisions were made:**
- Update the "Session History" table in `memory.md`
- Update the "Bugs Fixed" table if applicable
- Update any stale field descriptions (e.g. if a formula changed)

---

## Quick Start

```powershell
python app.py        # start server
# open http://localhost:5000
```

```powershell
python -m pytest tests/ -v    # 81 tests, 0 warnings expected
```

---

## Rebuild Rule (CRITICAL)

Flask caches Python modules at startup. **Never call `/rebuild` via HTTP after editing `.py` files** — it runs old code. Always:

```powershell
Stop-Process -Id <PID> -Force                              # kill server
python -c "from data.store import rebuild; rebuild()"      # CLI rebuild
python app.py                                              # restart
```

---

## The 6 Quantitative Rules — DO NOT VIOLATE

These protect against silent mathematical regressions. Each was introduced after a real incident.

**1. No Panama adjustment on spread prices.**
Panama is for outright futures. Calendar spreads are absolute-value metrics — if LEJ-LEM was +$4.00 in 2023, that is historical fact. `_roll_adjust()` was deleted in Session 7. The `spread_year` column is used only for NaN line-breaks in `raw_series` (Plotly rendering), never for price adjustment.

**2. No 16-year static mean for Z-scores.**
Cattle is in a generational supply super-cycle. A static 16-year mean produces Z-scores that are permanently extreme and useless for timing. `compute_rolling_zscore()` uses `series.ewm(span=500)` — EWM anchors to the 2-year structural regime.

**3. No annualised roll yield on biological assets.**
Cattle carry is a cliff, not linear decay. The current formula is `(near − def) / |def| × 100` — a straight percentage. The old `(ln(near) − ln(def)) × 365/dte × 100` formula was removed in Session 7. Do not reintroduce it.

**4. Enforce the 15-day delivery window.**
Cattle contracts in their final 2 weeks are driven by basis convergence and delivery mechanics, not macro price discovery. `_front_symbol()`, `_resolve_leg()`, and `compute_roll_yield()` all require DTE ≥ 15. Do not relax this.

**5. Use EWM, not SMA rolling windows.**
A fixed SMA window causes an instant mean-jump when a large historical event exits the window, even if today's price didn't move. `compute_rolling_zscore` uses `ewm(span=window)`. Do not revert to `rolling(window).mean/std`.

**6. Zero close prices = missing RTD data.**
Cattle never trades at $0.00. `parser.py` calls `.replace(0, float("nan"))` on `close` in both parsers. Volume and OI columns are NOT touched (zero is valid there).

---

## Never Save the XLSX

`Copy of Cattle_Spreads.xlsx` has live CmdtyView RTD formulas. `openpyxl` silently strips them on save. Python reads the file only — never writes it.

**As of Session 10 (2026-05-10) the XLSX is trimmed to 1 reference row per series (dated 2026-05-08).** It is no longer the historical archive — it is only the live RTD feed. Historical data lives in `data/archive/`.

---

## Archive — Do Not Modify

`data/archive/` contains 6 CSV files with 16 years of history exported 2026-05-08. These are the only copy of that history.

- **Never delete, overwrite, or re-export these files without explicit instruction.**
- `fat_spreads.csv`, `feeder_spreads.csv`, `fats_raw.csv`, `feeders_raw.csv` — read by `parser.py` on every rebuild via `merge_spread_archive()` / `merge_raw_archive()`.
- `spread_calcs.csv`, `contract_calcs.csv` — archived for reference only, not read by the app.
- `export_to_archive.py` in the project root is the one-time export script. It has already run. Do not re-run it unless explicitly asked.

---

## Intentionally Deferred (do not implement without instruction)

- **COT data**: add `COT` sheet to XLSX with `Date|LE_MM_Long|LE_MM_Short|GF_MM_Long|GF_MM_Short`, rebuild cache
- **Phase 2 spreads**: 2 spreads gated by `"phase2": true` in `metadata.json`
