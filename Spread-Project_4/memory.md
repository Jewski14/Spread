# Spread-Project_4 — Session Memory

**Last updated:** 2026-05-10 (Session 10 complete — work PC, OneDrive)
**Project status: COMPLETE AND WORKING — all 7 phases + 10 post-launch fixes + archive migration**

---

## How to Start

```powershell
cd "C:\Users\Jewski\OneDrive - kapcofutures.com\Spread-Project_4"
python app.py
```

Open **http://localhost:5000**

- First run with no cache builds automatically — subsequent starts are instant (fast-path cache check).
- Cache at `cache/stats.json` is auto-rebuilt if missing or stale.

---

## How to Rebuild the Cache (OneDrive — CRITICAL)

**NEVER use `http://localhost:5000/rebuild` on OneDrive after editing Python files.**
Flask imports modules once per process. If you edit a `.py` file while the server is running, the `/rebuild` endpoint uses the OLD cached module — the new code is NOT applied. Always kill the server first.

**Correct rebuild sequence after code changes:**

```powershell
# 1. Kill the server
Get-Process python* | Format-Table Id, StartTime, CPU
Stop-Process -Id <PID> -Force

# 2. Rebuild from CLI (uses new code)
python -c "from data.store import rebuild; rebuild()"

# 3. Restart server
python app.py
```

Or delete the cache file and restart:

```powershell
Remove-Item "cache\stats.json"
python app.py
```

**If server appears hung / dashboard not loading:**
1. `Get-Process python* | Format-Table Id, StartTime, CPU`
2. `Stop-Process -Id <PID> -Force`
3. `python app.py`

---

## What's Built — All Three Pages Working

| Page | Route | Features |
|---|---|---|
| Monitor | `/` | Regime strip (8 cells), mini LE/GF curve bars, sortable signal table (17 spreads, 7 cols), data-pulse LIVE/STALE dot, amber roll-warning row highlight |
| Research | `/spread/<id>` | Signal bar (6 chips), bias summary text, 4 charts (seasonal/history/z-score/overlay), 5-section metric grid (30+ cards), keyboard arrow navigation |
| Portfolio | `/portfolio` | Correlation heatmap (17×17), PCA variance + loadings, Spread Factor Map scatter (tier-colored), LE/GF curve shape charts |

### Research Page Charts (current design)

| Chart | Title | Description |
|---|---|---|
| Chart 1 | Seasonal Pattern | 5yr/10yr/15yr period-specific smoothed avg (JS-computed from `prior_years`), ±1σ band, prior years (dim), analog year (teal dashed), current year (orange solid) |
| Chart 2 | Full History | Raw settlement prices with NaN breaks at contract roll transitions, 16Y high/low reference lines, 1Y/3Y/5Y/All zoom |
| Chart 3 | Rolling Z-Score (500d) | EWM Z-score (`rolling_zscore_500d`) — last 750 pts (~3 years), ±1σ/±2σ reference lines |
| Chart 4 | Current Year: Close + Z-Score | Current calendar year close (orange) + EWM Z-score overlay (blue) |

---

## Architecture

### Stack
Python 3.11/3.14 · Flask · pandas · numpy · statsmodels · scikit-learn · openpyxl · Plotly.js 2.35.2 (CDN) · Vanilla JS · CSS

### Data Source

**Two-layer architecture (as of Session 10):**

1. `data/archive/*.csv` — 16-year history exported 2026-05-08. Read-only, never modified.
2. `Copy of Cattle_Spreads.xlsx` — live RTD feed. **Trimmed to 1 reference row (2026-05-08) per series.** Grows by 1 row per trading day. **Never save from Python** (strips RTD/CmdtyView formulas).

On every rebuild, `merge_spread_archive()` and `merge_raw_archive()` in `parser.py` union the archive CSV with the XLSX. XLSX wins on any date overlap (dedup keep='last').

| Sheet | Used for |
|---|---|
| `Fats Raw Data` | LE individual contract prices, volume, OI |
| `Feeders Raw Data` | GF individual contract prices, volume, OI |
| `Fat Spreads` | LE calendar spread prices + `spread_year` column |
| `Feeder Spreads` | GF calendar spread prices + `spread_year` column |

The `spread_year` column (e.g. `"LEJ26 - LEM26"`) changes at each contract roll. It is used by `build_store()` to inject NaN breaks into `raw_series` at transition boundaries so Plotly draws clean segment endpoints instead of vertical "flash crash" lines.

### Archive Files (`data/archive/`)

| File | Rows | IDs | Date range |
|---|---|---|---|
| `fat_spreads.csv` | 36,878 | 9 LE spread series | 2010-01-19 → 2026-05-08 |
| `feeder_spreads.csv` | 32,583 | 8 GF spread series | 2010-01-04 → 2026-05-08 |
| `fats_raw.csv` | 24,696 | 6 LE contracts | 2010-01-04 → 2026-05-08 |
| `feeders_raw.csv` | 32,918 | 8 GF contracts | 2010-01-04 → 2026-05-08 |
| `spread_calcs.csv` | 69,802 | 17 spreads (Excel-side calcs) | 2010-01-04 → 2026-05-08 |
| `contract_calcs.csv` | 57,614 | 14 contracts (Excel-side calcs) | 2010-01-04 → 2026-05-08 |

`spread_calcs.csv` and `contract_calcs.csv` are archived for reference only — not read by the Python app.

### The 17 Spreads
| Tier | Spreads |
|---|---|
| T1 Critical | LEJ-LEM, LEM-LEQ, LEQ-LEZ, LEQ-LEV |
| T2 High | LEG-LEJ, LEV-LEZ, LEZ-LEG, GFF-GFH, GFX-GFF, GFK-GFQ, GFV-GFX |
| T3 Active | GFH-GFJ, GFJ-GFK, GFQ-GFU, GFU-GFV |
| T4 Skip-Month | LEG-LEM, LEJ-LEQ |

Spread definitions live in **`metadata.json`** (project root). `data/constants.py` loads them at import time.

### Flask Routes (13)
| Route | Returns |
|---|---|
| `GET /` | Monitor page |
| `GET /spread/<id>` | Research page |
| `GET /portfolio` | Portfolio page |
| `GET /api/curve` | LE/GF curves + all chips + regime |
| `GET /api/spread/<id>` | Full research payload (40+ fields) |
| `GET /api/sidebar` | Lightweight chips |
| `GET /api/portfolio` | Correlation matrix, PCA, curve convexity |
| `GET /api/cot` | COT stats (`available: false` until sheet added) |
| `GET /api/roll-windows` | GSCI/BCOM roll window flags |
| `GET /api/contract/<product>/<symbol>` | Single contract detail |
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/data-status` | XLSX freshness: LIVE / STALE / MISSING |
| `GET/POST /rebuild` | Delete cache, rebuild from XLSX (kill server first if code changed) |

---

## Key Files

| File | Purpose |
|---|---|
| `app.py` | 13 Flask routes + startup |
| `config.py` | Relative paths, host=0.0.0.0, port=5000, `ARCHIVE_DIR` |
| `run.bat` | Windows one-click launcher |
| `metadata.json` | Authoritative spread definitions (id, label, full, tier, type, phase2) |
| `data/__init__.py` | Public API re-exports |
| `data/constants.py` | Loads SPREADS from metadata.json; SPREAD_META, PHASE1_IDS, FLY_MAP, MONTH_CODES |
| `data/analytics.py` | `build_store()` — full cache builder; NaN-break injection at roll transitions; `_spread_indicators()`, `_compute_seasonal()`, `_compute_edge_stats()`, `_resolve_leg()`, `_front_symbol()` |
| `data/advanced_analytics.py` | 24 analytics functions: `compute_rolling_zscore` (EWM), seasonal_rank, kink_z, roll_yield (% of deferred), oi_signature, composite_score, curve_convexity, pca, etc. |
| `data/store.py` | In-memory store, all query functions, `_find_leg_dte()`, `_percentile()` |
| `data/parser.py` | XLSX parsers + `merge_spread_archive()` / `merge_raw_archive()` — unions archive CSVs with XLSX data; uses `sym_col.iloc[-1]` to get current contract symbol; preserves `spread_year` column; `.replace(0, nan)` on `close` to drop RTD blank artifacts |
| `data/archive/` | 6 CSV files: 16-year history exported 2026-05-08. Read-only. 4 files used by parser merge; 2 (spread_calcs, contract_calcs) archived for reference only. |
| `export_to_archive.py` | One-time export script (project root). Already ran 2026-05-10. Keep for future re-export if needed. |
| `data/contract_calendar.py` | CME expiry dates, GSCI/BCOM roll windows |
| `data/cot_manager.py` | COT parser (wired, awaiting COT sheet) |
| `templates/base.html` | 3-tab nav, data-pulse div, conditional sidebar (hidden on Monitor) |
| `templates/monitor.html` | Monitor page |
| `templates/research.html` | Research page — 5yr/10yr/15yr seasonal buttons; chart titles: "Rolling Z-Score (500d)", "Current Year: Close + Z-Score" |
| `templates/portfolio.html` | Portfolio page — injects `window.SPREAD_TIERS` for PCA scatter |
| `static/app.js` | All JS — `_computeSeasonalAvg()`, all chart renderers, `_zTierKey()`, `_pollDataStatus()`, `_renderPCAScatter()` |
| `static/style.css` | All CSS — dark theme, all 3-page component styles, `.data-pulse`, `.roll-warning-row` |
| `cache/stats.json` | Pre-computed analytics cache (gitignored, auto-rebuilt) |
| `docs/research/master-report.md` | Domain reference — CME cattle spread mechanics |
| `docs/research/spread-rankings.md` | Domain reference — spread tier rankings |
| `tests/test_routes.py` | Route tests — all pages + API fields |
| `tests/test_advanced_analytics.py` | Unit tests for all analytics functions |
| `tests/test_analytics.py` | Parser utils, store helpers |
| `tests/test_constants.py` | Spread definitions, tier assignments |
| `memory.md` | This file |

---

## Test Suite — 81 Tests, All Passing

```powershell
python -m pytest tests/ -v
```

| File | Tests | Covers |
|---|---|---|
| `test_advanced_analytics.py` | 39 | All analytics functions: EWM zscore, kink_z, regime seasonal rank, roll yield (% formula), edge stats — no XLSX needed |
| `test_analytics.py` | 14 | Parser utils, store helpers — no XLSX needed |
| `test_constants.py` | 8 | Spread definitions, FLY_MAP, tier assignments — no XLSX needed |
| `test_routes.py` | 20 | All 3 pages, all API fields |

**Non-critical warnings (expected, not errors):**
- `Pandas4Warning` in `compute_spread_vwap` — pandas concat sort deprecation, no functional impact

**All RuntimeWarnings from `_compute_edge_stats` are now gone** — fixed in Session 8 via `np.errstate` + `np.nan_to_num`.

---

## Analytics Computed at Build Time (`build_store()`)

All fields below are stored in `cache/stats.json` per spread and served via `/api/spread/<id>`.

| Field | Description |
|---|---|
| `series` | `[date, close]` list — raw settlement prices; `null` values injected at contract roll transitions for clean Plotly line breaks |
| `seasonal` | `{doy: [mean, min, max, std]}` — all-years DOY average; std is 4th element |
| `prior_years` | `{year: [[doy, close], ...]}` — raw per-year DOY series; used by JS for period-specific seasonal avg |
| `range16y` | `{high, low, mean}` — computed from raw prices |
| `latest_calcs` | `{zscore_full, zscore_struct, roc_5d, roc_20d_vol_norm, roc_60d_vol_norm, vol_20d}` |
| `calcs_series` | `[date, zscore_full]` — full 16-year Z-score history; used in composite score, NOT displayed in charts |
| `rolling_zscore_500d` | EWM Z-score (span=500) — last 750 pts stored (~3 years); used for Chart 3 and Chart 4 overlay |
| `seasonal_rank` | Closest prior year by Pearson corr (regime-weighted) |
| `seasonal_sigma` | Current close vs DOY mean in units of DOY std |
| `spread_vwap_20d` | 20-day volume-weighted avg price |
| `ou_halflife` | Ornstein-Uhlenbeck mean-reversion half-life (days) |
| `adf` | ADF stationarity test `{adf_stat, p_value, stationary, critical_1pct, critical_5pct}` |
| `regime_conditional` | Mean/std split by backwardation vs contango |
| `skew_kurt` | `{skewness, excess_kurtosis, n_obs}` |
| `var` | Historical VaR at 95%/99% per cwt and per contract |
| `max_drawdown` | `{max_drawdown_cwt, peak_date, trough_date, duration_calendar_days}` |
| `beta_to_front` | OLS beta vs front contract `{beta, r_squared, p_value}` |
| `composite_score` | Weighted signal: zscore 40% + percentile 35% + roc_vol_norm 25%. Positive = expensive/sell |
| `shadow_convenience_yield` | Near-term scarcity premium (%) |
| `roll_yield` | `(near_price − def_price) / \|def_price\| × 100` — straight % of deferred; positive = backwardation |
| `roll_yield_rank` | Cross-sectional percentile rank among all 17 spreads (0–100) |
| `oi_signature` | `ROLL / NEW_MONEY / LIQUIDATION / UNKNOWN` based on leg OI changes |
| `kink_z` | 2-year EWM Z-score of butterfly fly (`front − 2×mid + back`) |
| `edge_stats` | Per-Z-tier forward return stats: `{tier: {5d: {mean, hit_rate, n}, 10d:…, 20d:…}}` |
| `momentum_regime` | `TRENDING / MEAN_REVERTING / MIXED` from roc_5d and roc_60d vol-norm |
| `carry_momo_quad` | `Carry + Momentum / Carry Fade / Momo vs Carry / Double Headwind` |
| `roll_pressure_score` | Volume-share Z-score during active GSCI roll window |
| `roll_warning` | `true` when roll_pressure_score > 1.5 |

---

## Design Principles for Spread Analytics (hard-won lessons)

**Panama is invalid for calendar spreads.**
Panama backward adjustment is designed for outright futures (trend-following, P&L backtest). Calendar spreads are absolute-value relative metrics — if LEJ-LEM traded at +$4.00 in 2023, that IS the historical reality. Panama would shift it to a phantom number by applying cumulative roll offsets. All Z-scores, seasonals, and edge stats must operate on raw settlement prices. The `spread_year` column is used only to detect where to break the Plotly line (NaN injection), not to adjust prices.

**Full-history Z-score is a trap for non-stationary commodities.**
Cattle is in a generational supply super-cycle. Using a 16-year static mean produces Z-scores that are permanently extreme and never revert to zero — useless for tactical timing. Use EWM (span≈500) to anchor to the current structural regime while avoiding the SMA drop-off cliff.

**Do not annualize biological spreads.**
Cattle carry is a cliff, not a linear decay. Annualizing a 60-day $6 premium to `~36%/yr` is nonsensical. Quote as a straight percentage of the deferred price: `(near − def) / |def| × 100`.

**Respect the delivery window.**
Front-month cattle contracts enter a delivery/convergence regime in their final 2 weeks. Prices are driven by basis convergence and localized mechanics, not macro price discovery. `_front_symbol()`, `_resolve_leg()`, and `compute_roll_yield()` all enforce `DTE ≥ 15` to avoid contaminating signals with delivery-period noise.

**EWM Z-score eliminates the drop-off cliff.**
With a fixed SMA window, a large historical shock exactly `window + 1` days ago causes a sudden mean jump the next day even if today's price is unchanged. EWM exponentially decays the weight of old data — the influence of any single event fades smoothly over months rather than snapping out of the window overnight.

---

## Regime Strip — Expected Behaviour (not bugs)

- **BCOM Roll "INACTIVE"** when GSCI shows DAY 1/5 is **correct**: GSCI rolls BD 5–9, BCOM rolls BD 6–10.
- **COT LE/GF showing `—`** is **correct**: no COT sheet in XLSX yet (intentionally deferred).
- **`roll_pressure_score = null`** outside of GSCI roll window is **correct**: only computed BD 5–9.

---

## Intentionally Deferred — Do Not Delete

| Feature | What to do when ready |
|---|---|
| **COT data** | Add sheet named `COT` to `Copy of Cattle_Spreads.xlsx` with columns: `Date \| LE_MM_Long \| LE_MM_Short \| GF_MM_Long \| GF_MM_Short` (weekly CFTC data), then rebuild cache. Everything else auto-activates. |
| **Phase 2 spreads** | Set `"phase2": true` → `false` in `metadata.json` for any spread when data is ready. |

---

## Bugs Fixed (complete history)

| Bug | Fix |
|---|---|
| `roll_yield` null for all spreads | `parse_raw_sheet` took `sym_col.iloc[0]` (oldest symbol); changed to `iloc[-1]` |
| DTE chips hidden | Same parser bug — fixed by same `iloc[-1]` change |
| `calcs_series` / `roll_yield` not in API | Added to `get_spread_research()` return dict in `data/store.py` |
| Contract OI/VWAP/vol always None | `_contract_entry()` not reading raw DataFrames |
| `_front_symbol()` returning expired contracts | Added `get_days_to_expiry(s) > 0` filter |
| `_percentile()` with 1–2 obs | Added `if len(comparisons) < 5: return None` |
| Composite score double-negation | Rewrote to 3-param version with positive = expensive = sell signal |
| Flask module caching: `/rebuild` used old code after edits | Must kill server → CLI rebuild → restart |
| Panama adjustment applied to calendar spreads (Session 6 error) | Removed `_roll_adjust()` entirely — invalid for spreads; phantom prices distorted all Z-scores and seasonals |
| Full-history Z-score on non-stationary cattle data | Switched to EWM Z-score `rolling_zscore_500d` (span=500 ≈ 2-year regime); full-history mean biased by super-cycle |
| Annualized log roll yield on biological assets | `compute_roll_yield()` → `(near−def)/\|def\|×100`; cattle carry is a cliff, not linear decay |
| DTE rollover: picking contracts in delivery period | `_front_symbol()` `dte > 0` → `dte >= 15`; `_resolve_leg()` prefers ≥15 DTE; `compute_roll_yield()` returns None when DTE < 15 |
| Seasonal averages on Panama-adjusted prices | Fixed by removing Panama; `prior_years` now carries raw settlement prices |
| Full History chart: Plotly drawing vertical spike lines at roll transitions | `build_store()` injects `[date, null]` at `spread_year` transitions; 33 breaks in LEJ-LEM; Plotly renders null as line break |
| `RuntimeWarning: divide by zero` in `_compute_edge_stats` | Wrapped `np.where` division with `np.errstate(divide='ignore', invalid='ignore')` + `np.nan_to_num`; NumPy pre-evaluates both branches of `np.where` before applying the mask |
| EWM/SMA drop-off cliff in rolling Z-score | Replaced `series.rolling(window).mean/std` with `series.ewm(span=window).mean/std` in `compute_rolling_zscore` |
| Zero-price RTD artifacts from CmdtyView blank cells | `parser.py` now calls `.replace(0, float("nan"))` on `close` after `pd.to_numeric` in both `parse_spread_sheet` and `parse_raw_sheet`; volume/OI columns unaffected (zero is valid for those) |

---

## Session History

| Session | Date | Computer | Key Work |
|---|---|---|---|
| 1 | 2026-05-06 | Home PC | Backend complete — 30+ analytics, all routes, Phase 2+3 wiring, frontend spec written |
| 2 | 2026-05-07 | Work PC (OneDrive) | Frontend built (3 pages), 5 spec gaps patched, parser bug fixed (roll_yield + DTE), full project cleanup |
| 3 | 2026-05-07 | Work PC (OneDrive) | 5-phase implementation — hierarchical clustering, Plotly.react, array slicing, analog highlighting, asymmetric VaR, ranked analogs |
| 4 | 2026-05-08 | Work PC (OneDrive) | Phases 1–3: removed 7 indicators (RSI/BB/Hurst/SPI/entry-prob), fixed 5 bugs, slimmed calcs_series, 17 spreads (19→17), 68 tests |
| 5 | 2026-05-08 | Work PC (OneDrive) | Phases 4A–4K + Phase 7: OI sig, kink_z, log roll yield, zscore_struct, seasonal_sigma, Z-Cloud band, edge stats, momentum regime, carry-momo quad, roll pressure, PCA scatter, data-pulse watchdog, metadata.json — 80 tests |
| 6 | 2026-05-09 | Work PC (OneDrive) | Chart redesigns: seasonal 5/10/15yr period-specific smoothed avg, Z-score → full-history calcs_series, overlay → current year only — 85 tests |
| 7 | 2026-05-09 | Work PC (OneDrive) | 5 mathematical flaws fixed: removed Panama, 500d EWM Z-score, non-annualized roll yield, 15-DTE rollover guard, raw prior_years — 81 tests |
| 8 | 2026-05-09 | Work PC (OneDrive) | 4 audit fixes: RuntimeWarning silenced (errstate+nan_to_num), NaN breaks at roll transitions (33 in LEJ-LEM), EWM Z-score replacing SMA, sign convention verified correct — 81 tests |
| 9 | 2026-05-09 | Work PC (OneDrive) | Root-cause fix for zero-price RTD artifacts: `parser.py` replaces zero `close` with NaN in both spread and raw parsers; volume/OI columns untouched — 81 tests, 0 warnings |
| 10 | 2026-05-10 | Work PC (OneDrive) | Archive migration: exported 6 CSV files to `data/archive/` (16yr history through 2026-05-08); Sam manually trimmed XLSX to 1 reference row per series; added `merge_spread_archive()` / `merge_raw_archive()` to `parser.py`; added `ARCHIVE_DIR` to `config.py`; updated `analytics.py` to union archive + XLSX on rebuild — 81 tests, 0 warnings |
