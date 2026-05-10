"""
app.py — Flask application for the Cattle Spreads Dashboard.
Run with: python app.py  (or double-click run.bat on Windows)
Dashboard: http://localhost:5000
"""
from flask import Flask, jsonify, render_template, abort
from datetime import datetime

import config
import data

app = Flask(__name__)


# ── Page routes ───────────────────────────────────────────────────────────────

@app.route("/")
def monitor():
    return render_template(
        "monitor.html",
        spreads=data.SPREADS,
        chips=data.get_all_spread_chips(),
        spread_id=None,
        page="monitor",
    )


@app.route("/portfolio")
def portfolio():
    return render_template(
        "portfolio.html",
        spreads=data.SPREADS,
        chips=data.get_all_spread_chips(),
        spread_id=None,
        page="portfolio",
    )


@app.route("/spread/<spread_id>")
def research(spread_id):
    meta = data.SPREAD_META.get(spread_id)
    if not meta:
        abort(404)

    ids     = data.PHASE1_IDS
    idx     = ids.index(spread_id) if spread_id in ids else 0
    prev_id = ids[(idx - 1) % len(ids)]
    next_id = ids[(idx + 1) % len(ids)]

    return render_template(
        "research.html",
        spreads=data.SPREADS,
        chips=data.get_all_spread_chips(),
        spread_id=spread_id,
        meta=meta,
        prev_id=prev_id,
        next_id=next_id,
        page="research",
    )


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/curve")
def api_curve():
    le_curve, gf_curve = data.get_curve_data()
    chips = data.get_all_spread_chips()

    le_front = le_curve[0]["close"]  if le_curve              else None
    le_back  = le_curve[-1]["close"] if len(le_curve) > 1     else None
    gf_front = gf_curve[0]["close"]  if gf_curve              else None
    gf_back  = gf_curve[-1]["close"] if len(gf_curve) > 1     else None

    le_slope = round(le_front - le_back, 3) if (le_front is not None and le_back is not None) else None
    gf_slope = round(gf_front - gf_back, 3) if (gf_front is not None and gf_back is not None) else None

    market_structure = "BACKWARDATION" if (le_slope is not None and le_slope > 0) else "CONTANGO"

    phase1_chips = [c for c in chips if not data.SPREAD_META.get(c["id"], {}).get("phase2")]
    extremes     = sum(1 for c in phase1_chips if c.get("percentile") is not None and c["percentile"] >= 90)

    return jsonify({
        "le_curve": le_curve,
        "gf_curve": gf_curve,
        "chips":    chips,
        "regime": {
            "market_structure": market_structure,
            "le_slope":         le_slope,
            "gf_slope":         gf_slope,
            "extremes_count":   extremes,
            "extremes_total":   len(phase1_chips),
            "le_front_oi":      le_curve[0].get("oi") if le_curve else None,
        },
        "updated": le_curve[0].get("date") if le_curve else None,
    })


@app.route("/api/spread/<spread_id>")
def api_spread(spread_id):
    if spread_id not in data.SPREAD_META:
        return jsonify({"error": "Not found"}), 404
    if data.SPREAD_META[spread_id].get("phase2"):
        return jsonify({"phase2": True, "meta": data.SPREAD_META[spread_id]})
    result = data.get_spread_research(spread_id)
    if not result:
        return jsonify({"error": "No data for this spread"}), 404
    return jsonify(result)


@app.route("/api/sidebar")
def api_sidebar():
    return jsonify({"spreads": data.get_all_spread_chips()})


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


@app.route("/api/data-status")
def api_data_status():
    """Return XLSX freshness: LIVE when <4 hours old (or weekend), STALE otherwise."""
    path = config.XLSX_PATH
    if not path.exists():
        return jsonify({"status": "MISSING", "age_hours": None, "last_modified": None})
    mtime  = datetime.fromtimestamp(path.stat().st_mtime)
    age_h  = (datetime.now() - mtime).total_seconds() / 3600
    is_wkd = datetime.now().weekday() >= 5   # Sat=5, Sun=6
    status = "LIVE" if (is_wkd or age_h < 4) else "STALE"
    return jsonify({
        "status":        status,
        "age_hours":     round(age_h, 1),
        "last_modified": mtime.strftime("%Y-%m-%d %H:%M"),
    })


@app.route("/api/portfolio")
def api_portfolio():
    """Correlation matrix + PCA across all Phase 1 spreads."""
    return jsonify(data.get_portfolio_analytics())


@app.route("/api/cot")
def api_cot():
    """COT managed-money positioning stats."""
    return jsonify(data.get_cot_status())


@app.route("/api/roll-windows")
def api_roll_windows():
    """GSCI / BCOM roll window status for today."""
    return jsonify(data.get_roll_window_status())


@app.route("/api/contract/<product>/<symbol>")
def api_contract(product, symbol):
    """Full contract detail including OI trend, VWAP, days-to-expiry."""
    result = data.get_contract_details(product, symbol)
    if not result:
        return jsonify({"error": "Not found"}), 404
    return jsonify(result)


@app.route("/rebuild", methods=["GET", "POST"])
def rebuild():
    data.rebuild()
    return jsonify({"status": "ok", "message": "Cache rebuilt successfully"})


# ── Startup ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Loading data…")
    data.load()
    print(f"Dashboard ready -> http://localhost:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
