# Cattle Spreads Dashboard

A local Flask dashboard for monitoring and researching CME Live Cattle (LE) and Feeder Cattle (GF) calendar spreads. Covers 17 spreads across three pages: a live monitor, a per-spread research view, and a portfolio analytics page.

---

## Pages

### Monitor (`/`)
- Live signal table for all 17 spreads — composite score, Z-score, roll yield, momentum regime, OI signature, roll warning
- Regime strip showing GSCI/BCOM roll window status and COT positions (8 cells)
- Mini LE/GF forward curve bars
- LIVE/STALE data-pulse indicator

### Research (`/spread/<id>`)
- 4 charts: Seasonal Pattern (5/10/15yr), Full History (16yr), Rolling Z-Score (500d EWM), Current Year Close + Z-Score Overlay
- 30+ metric cards: ADF stationarity, Ornstein-Uhlenbeck half-life, VaR, max drawdown, beta to front, carry-momentum quadrant, edge stats by Z-tier, and more
- Keyboard arrow navigation between spreads

### Portfolio (`/portfolio`)
- 17×17 correlation heatmap
- PCA variance + loadings
- Spread Factor Map scatter (tier-colored)
- LE/GF curve shape charts

---

## Tech Stack

- **Backend:** Python 3.11+, Flask, pandas, numpy, statsmodels, scikit-learn, openpyxl
- **Frontend:** Plotly.js 2.35.2 (CDN), Vanilla JS, CSS — no build step
- **Data:** CmdtyView RTD Excel feed + 16-year CSV archive

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run

```bash
python app.py
```

Open **http://localhost:5000**

The cache builds automatically on first run. Subsequent starts are instant (cache is reused if the XLSX hasn't changed).

### 3. Run tests

```bash
python -m pytest tests/ -v
```

81 tests, 0 warnings expected. Most tests run without the XLSX (unit tests only).

---

## Data

The dashboard uses a two-layer data architecture:

| Layer | Path | Purpose |
|---|---|---|
| Archive | `data/archive/*.csv` | 16-year settlement history (2010–2026-05-08), read-only |
| Live feed | `Copy of Cattle_Spreads.xlsx` | CmdtyView RTD formulas, grows 1 row per trading day |

On every rebuild, `parser.py` unions the archive CSVs with the XLSX — the XLSX wins on any overlapping date. This keeps the XLSX small (1 reference row per series at repo creation) while preserving the full price history.

**Note:** Live prices require a CmdtyView subscription with RTD enabled in Excel. Without it, the dashboard runs on archive data only (through 2026-05-08).

**Never open and save the XLSX from Python** — openpyxl silently strips the RTD/CmdtyView formulas.

---

## Rebuilding the Cache

After editing any `.py` file, kill the server before rebuilding — Flask caches modules at startup and `/rebuild` will run old code if the server is still running.

```bash
# Kill the server first, then:
python -c "from data.store import rebuild; rebuild()"
python app.py
```

Or just delete `cache/stats.json` and restart — it rebuilds automatically.

---

## The 17 Spreads

| Tier | Spreads |
|---|---|
| T1 Critical | LEJ-LEM, LEM-LEQ, LEQ-LEZ, LEQ-LEV |
| T2 High | LEG-LEJ, LEV-LEZ, LEZ-LEG, GFF-GFH, GFX-GFF, GFK-GFQ, GFV-GFX |
| T3 Active | GFH-GFJ, GFJ-GFK, GFQ-GFU, GFU-GFV |
| T4 Skip-Month | LEG-LEM, LEJ-LEQ |

Spread definitions are in `metadata.json`.

---

## Folder Structure

```
Spread-Project_4/
│
├── app.py                        # Flask app — 13 routes, server startup
├── config.py                     # Paths, host/port, ARCHIVE_DIR
├── metadata.json                 # Authoritative spread definitions (id, label, tier, type)
├── requirements.txt              # Python dependencies
├── run.bat                       # Windows one-click launcher
├── export_to_archive.py          # One-time export script (already ran 2026-05-08)
├── memory.md                     # Developer session notes
├── CLAUDE.md                     # AI assistant session instructions
│
├── Copy of Cattle_Spreads.xlsx   # Live CmdtyView RTD feed (never save from Python)
│
├── data/
│   ├── __init__.py               # Public API re-exports
│   ├── constants.py              # SPREADS, SPREAD_META, PHASE1_IDS, FLY_MAP, MONTH_CODES
│   ├── parser.py                 # XLSX parsers + merge_spread_archive / merge_raw_archive
│   ├── analytics.py              # build_store() — full cache builder, seasonal, edge stats
│   ├── advanced_analytics.py     # 24 analytics functions: EWM Z-score, roll yield, PCA, etc.
│   ├── store.py                  # In-memory store, all query functions
│   ├── contract_calendar.py      # CME expiry dates, GSCI/BCOM roll windows
│   ├── cot_manager.py            # COT parser (wired, awaiting COT sheet in XLSX)
│   │
│   └── archive/                  # 16-year settlement history — READ ONLY, never modify
│       ├── fat_spreads.csv       # 36,878 rows — 9 LE spread series, 2010–2026-05-08
│       ├── feeder_spreads.csv    # 32,583 rows — 8 GF spread series, 2010–2026-05-08
│       ├── fats_raw.csv          # 24,696 rows — 6 LE contracts, 2010–2026-05-08
│       ├── feeders_raw.csv       # 32,918 rows — 8 GF contracts, 2010–2026-05-08
│       ├── spread_calcs.csv      # 69,802 rows — reference only, not read by app
│       └── contract_calcs.csv    # 57,614 rows — reference only, not read by app
│
├── cache/
│   └── .gitkeep                  # Keeps folder in repo; stats.json is gitignored
│
├── static/
│   ├── app.js                    # All frontend JS — chart renderers, seasonal avg, polling
│   └── style.css                 # Dark theme, all 3-page component styles
│
├── templates/
│   ├── base.html                 # 3-tab nav, data-pulse div, sidebar
│   ├── monitor.html              # Monitor page
│   ├── research.html             # Research page — 4 charts, 5-section metric grid
│   └── portfolio.html            # Portfolio page — heatmap, PCA, curve charts
│
├── tests/
│   ├── conftest.py               # Shared pytest fixtures
│   ├── test_advanced_analytics.py  # 39 tests — all analytics functions (no XLSX needed)
│   ├── test_analytics.py           # 14 tests — parser utils, store helpers
│   ├── test_constants.py           #  8 tests — spread definitions, tier assignments
│   └── test_routes.py              # 20 tests — all pages and API endpoints
│
└── docs/
    └── research/
        ├── master-report.md      # Domain reference — CME cattle spread mechanics
        └── spread-rankings.md    # Spread tier rankings and rationale
```

---

## Analytics Design Notes

A few non-obvious decisions baked into the analytics:

- **No Panama adjustment on spread prices.** Panama is designed for outright futures trend-following. Calendar spreads are absolute-value metrics — if LEJ-LEM was +$4.00 in 2023, that is historical fact. Applying cumulative roll offsets would produce phantom prices.

- **EWM Z-score, not SMA.** Cattle is in a generational supply super-cycle. A 16-year static mean produces Z-scores that are permanently extreme. EWM (span=500, ≈2-year regime) anchors to the current structural environment. It also eliminates the SMA "drop-off cliff" where a large historical event suddenly exits the window and snaps the mean.

- **No annualized roll yield.** Cattle carry is a cliff, not linear decay. Roll yield is quoted as a straight percentage of deferred: `(near − deferred) / |deferred| × 100`.

- **15-day delivery window enforced.** Front-month cattle in final delivery is driven by basis convergence, not price discovery. All DTE logic requires ≥ 15 days to expiry.
