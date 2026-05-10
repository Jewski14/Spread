/* app.js — Plotly chart rendering, API calls, toggle controls */
"use strict";

// ── Constants ──────────────────────────────────────────────────────────────

const COLORS = {
  bg:        '#0f1117',
  panel:     '#13161f',
  grid:      '#1e2333',
  le:        '#ef8c2f',
  gf:        '#5ba0d0',
  pos:       '#4caf50',
  neg:       '#f44336',
  warn:      '#f5a623',
  muted:     '#555555',
  prior:     'rgba(74,100,90,0.35)',
  band:      'rgba(30,58,42,0.45)',
  text:      '#888888',
  tier1:     '#ef8c2f',
  tier2:     '#5ba0d0',
  tier3:     '#4caf50',
  tier4:     '#666666',
};

const SCORE_COLORS = [
  { max: -1.5, hex: '#4caf50' },
  { max: -0.5, hex: '#66bb6a' },
  { max:  0.5, hex: '#888888' },
  { max:  1.5, hex: '#ef8c2f' },
  { max: Infinity, hex: '#f44336' },
];

const MONTH_NAMES = {
  F:'Jan', G:'Feb', H:'Mar', J:'Apr', K:'May', M:'Jun',
  N:'Jul', Q:'Aug', U:'Sep', V:'Oct', X:'Nov', Z:'Dec',
};

const MON_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

const PLOTLY_BASE = {
  paper_bgcolor: COLORS.panel,
  plot_bgcolor:  COLORS.bg,
  font:          { family: "'Segoe UI', monospace", size: 10, color: COLORS.text },
  margin:        { l: 40, r: 10, t: 10, b: 30 },
  xaxis: { gridcolor: COLORS.grid, linecolor: COLORS.grid, zerolinecolor: COLORS.grid, tickfont: { size: 9 } },
  yaxis: { gridcolor: COLORS.grid, linecolor: COLORS.grid, zerolinecolor: true, tickfont: { size: 9 } },
  showlegend: false,
  hovermode: 'x unified',
};

const PLOTLY_CFG = { displayModeBar: false, responsive: true };

// ── Shared state ───────────────────────────────────────────────────────────

let _researchData = null;
let _monitorChips = [];
let _signalSort   = { col: '_abs_composite', dir: 'desc' };
let _showPrior    = true;
let _showBand     = true;
let _seasonalYrs  = 10;
let _historyZoom  = 'all';


// ════════════════════════════════════════════════════════════════════════════
// MONITOR PAGE
// ════════════════════════════════════════════════════════════════════════════

function initMonitor() {
  Promise.all([
    fetch('/api/curve').then(r => r.json()),
    fetch('/api/cot').then(r => r.json()),
    fetch('/api/roll-windows').then(r => r.json()),
  ]).then(([curve, cot, rw]) => {
    _pollDataStatus();
    setInterval(_pollDataStatus, 300000);
    _renderTopbar(curve.updated, curve.le_curve, curve.gf_curve);
    _renderRegimeStrip(curve.regime, cot, rw);
    _renderMiniCurves(curve.le_curve, curve.gf_curve);
    _monitorChips = curve.chips || [];
    _renderSignalTable(_monitorChips);
    _setupTableSortHeaders();
  });
}

function _renderRegimeStrip(r, cot, rw) {
  if (!r) return;

  const structure = r.market_structure || '—';
  const sEl = _setCell('rc-structure-val', structure);
  if (sEl) sEl.className = 'rc-val ' + (structure === 'BACKWARDATION' ? 'neg' : 'pos');

  const leSlope = r.le_slope;
  const lsEl = _setCell('rc-le-slope-val', leSlope !== null && leSlope !== undefined ? fmtSigned(leSlope, 3) : '—');
  if (lsEl) lsEl.className = 'rc-val ' + (leSlope > 0 ? 'neg' : 'pos');
  _setCell('rc-le-slope-sub', r.le_slope_sub || '');

  const gfSlope = r.gf_slope;
  const gsEl = _setCell('rc-gf-slope-val', gfSlope !== null && gfSlope !== undefined ? fmtSigned(gfSlope, 3) : '—');
  if (gsEl) gsEl.className = 'rc-val ' + (gfSlope > 0 ? 'neg' : 'pos');

  const ext = r.extremes_count;
  const extEl = _setCell('rc-extremes-val', ext !== null ? `${ext} / ${r.extremes_total}` : '—');
  if (extEl) extEl.className = 'rc-val ' + (ext > 0 ? 'warn' : '');

  // Roll windows
  if (rw) {
    const gsciEl = _setCell('rc-gsci-val', rw.gsci_active ? `DAY ${rw.gsci_day}/5` : 'INACTIVE');
    if (gsciEl) gsciEl.className = 'rc-val ' + (rw.gsci_active ? 'warn' : 'muted');
    const bcomEl = _setCell('rc-bcom-val', rw.bcom_active ? `DAY ${rw.bcom_day}/5` : 'INACTIVE');
    if (bcomEl) bcomEl.className = 'rc-val ' + (rw.bcom_active ? 'warn' : 'muted');
  }

  // COT
  if (cot && cot.available) {
    const leNet = cot.le_mm_net;
    const lePct = cot.le_mm_net_percentile;
    _setCell('rc-cot-le-val', leNet !== null ? fmtK(leNet) : '—');
    _setCell('rc-cot-le-sub', lePct !== null ? `${lePct}th pct` : '');
    const gfNet = cot.gf_mm_net;
    const gfPct = cot.gf_mm_net_percentile;
    _setCell('rc-cot-gf-val', gfNet !== null ? fmtK(gfNet) : '—');
    _setCell('rc-cot-gf-sub', gfPct !== null ? `${gfPct}th pct` : '');
  } else {
    _setCell('rc-cot-le-val', '—');
    _setCell('rc-cot-gf-val', '—');
  }
}

function _renderMiniCurves(le, gf) {
  _renderMiniCurvePanel('le', le);
  _renderMiniCurvePanel('gf', gf);
}

function _renderMiniCurvePanel(type, curve) {
  const barsEl   = document.getElementById(`${type}-mini-bars`);
  const pricesEl = document.getElementById(`${type}-mini-prices`);
  if (!barsEl || !curve || !curve.length) return;

  const prices = curve.map(c => c.close || 0);
  const max    = Math.max(...prices);
  const min    = Math.min(...prices);
  const range  = max - min || 1;
  const HEIGHT = 28;

  barsEl.innerHTML = curve.map(c => {
    const h = Math.max(2, Math.round(((c.close - min) / range) * HEIGHT));
    return `<div class="mini-bar ${type}" style="height:${h}px" title="${c.month || ''} ${c.close}"></div>`;
  }).join('');

  pricesEl.innerHTML = `
    <span>${max.toFixed(2)}</span>
    <span>${min.toFixed(2)}</span>`;
}

function _renderSignalTable(chips) {
  const tbody = document.getElementById('signal-table-body');
  if (!tbody) return;

  const rows = chips.map(c => ({ ...c, _abs_composite: Math.abs(c.composite_score ?? 0) }));
  const { col, dir } = _signalSort;

  rows.sort((a, b) => {
    let va = a[col], vb = b[col];
    if (va === null || va === undefined) va = -Infinity;
    if (vb === null || vb === undefined) vb = -Infinity;
    return dir === 'desc' ? vb - va : va - vb;
  });

  tbody.innerHTML = rows.map(c => {
    if (c.phase2) {
      return `<tr class="p2-row">
        <td class="td-spread">${c.label} <span class="td-tier-badge tb-t${c.tier}">P2</span></td>
        ${Array(6).fill('<td class="muted">—</td>').join('')}
      </tr>`;
    }

    const score  = c.composite_score;
    const arrow  = score !== null ? (score < 0 ? ' ▲' : ' ▼') : '';
    const sigClr = score !== null ? scoreHex(score) : '#888';
    const sigTxt = score !== null ? `${fmtSigned(score, 2)}${arrow}` : '—';

    const pct   = c.percentile;
    const pctTx = pct !== null ? `${pct}th${pct >= 90 ? ' ⚠' : ''}` : '—';

    const ry    = c.roll_yield;
    const ryCl  = ry !== null ? (ry > 0 ? 'pos' : 'neg') : '';

    const chg   = c.change;
    const chgCl = chg !== null ? (chg > 0 ? 'pos' : chg < 0 ? 'neg' : '') : '';

    const z   = c.zscore_full;
    const zCl = z !== null ? (z < 0 ? 'pos' : 'neg') : '';

    const rwClass = c.roll_warning ? ' roll-warning-row' : '';
    return `<tr class="${rwClass}" onclick="location.href='/spread/${c.id}'">
      <td class="td-spread">${c.label}<span class="td-tier-badge tb-t${c.tier}">T${c.tier}</span></td>
      <td class="td-signal" style="color:${sigClr}">${sigTxt}</td>
      <td class="${c.close !== null ? (c.close > 0 ? 'pos' : c.close < 0 ? 'neg' : '') : ''}">${c.close !== null ? fmtSigned(c.close, 3) : '—'}</td>
      <td class="${pct >= 90 ? 'warn' : ''}">${pctTx}</td>
      <td class="${zCl}">${z !== null ? fmtSigned(z, 2) + 'σ' : '—'}</td>
      <td class="${ryCl}">${ry !== null ? fmtSigned(ry, 1) + '%' : '—'}</td>
      <td class="${chgCl}">${chg !== null ? fmtSigned(chg, 3) : '—'}</td>
    </tr>`;
  }).join('');
}

function _setupTableSortHeaders() {
  document.querySelectorAll('#signal-table thead th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (!col) return;
      if (_signalSort.col === col) {
        _signalSort.dir = _signalSort.dir === 'desc' ? 'asc' : 'desc';
      } else {
        _signalSort.col = col;
        _signalSort.dir = 'desc';
      }
      document.querySelectorAll('#signal-table thead th').forEach(h => {
        h.classList.remove('sort-asc', 'sort-desc');
      });
      th.classList.add(_signalSort.dir === 'desc' ? 'sort-desc' : 'sort-asc');
      _renderSignalTable(_monitorChips);
    });
  });
}


// ════════════════════════════════════════════════════════════════════════════
// RESEARCH PAGE
// ════════════════════════════════════════════════════════════════════════════

function initResearch() {
  const id = window.SPREAD_ID;
  if (!id) return;

  Promise.all([
    fetch(`/api/spread/${id}`).then(r => r.json()),
    fetch('/api/curve').then(r => r.json()),
    fetch('/api/roll-windows').then(r => r.json()),
  ]).then(([d, curve, rw]) => {
    _pollDataStatus();
    setInterval(_pollDataStatus, 300000);
    _renderTopbar(d.current ? d.current.date : (curve.updated || null), curve.le_curve, curve.gf_curve);
    if (d.phase2) return;
    _researchData = d;
    _renderResearchHeader(d, rw);
    _renderSignalBar(d);
    _renderBiasSummary(d);
    _renderSeasonalChart(d);
    _renderHistoryChart(d);
    _renderZscoreChart(d);
    _renderOverlayChart(d);
    _renderMetricGrid(d);

    // Keyboard navigation: left/right arrow for spread switching
    document.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      const prevEl = document.querySelector('.nav-arrow[title="Previous"]');
      const nextEl = document.querySelector('.nav-arrow[title="Next"]');
      if (e.key === 'ArrowLeft'  && prevEl) { location.href = prevEl.href; }
      if (e.key === 'ArrowRight' && nextEl) { location.href = nextEl.href; }
    });
  });
}

function _renderResearchHeader(d, rw) {
  // Roll window badge
  const badge = document.getElementById('window-badge');
  if (badge && rw) {
    if (rw.gsci_active || rw.bcom_active) {
      const label = rw.gsci_active ? `GSCI Day ${rw.gsci_day}/5` : `BCOM Day ${rw.bcom_day}/5`;
      badge.textContent = label;
      badge.className   = 'window-badge active';
    } else {
      badge.textContent = 'No Active Roll';
      badge.className   = 'window-badge';
    }
  }

  // DTE chips
  _renderDTEChip('near-dte', d.near_dte, d.id ? d.id.split('-')[0] : '');
  _renderDTEChip('deferred-dte', d.deferred_dte, d.id ? d.id.split('-')[1] : '');
}

function _renderDTEChip(elId, dte, sym) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (dte === null || dte === undefined) { el.style.display = 'none'; return; }
  el.style.display = '';
  el.textContent   = `${sym}: ${dte}d`;
  el.className     = 'dte-chip' + (dte <= 21 ? ' dte-urgent' : '');
}

function _renderSignalBar(d) {
  const lc  = d.latest_calcs || {};
  const rzArr = d.rolling_zscore_500d || [];
  const rzLast = rzArr.length ? rzArr[rzArr.length - 1][1] : null;

  const score = d.composite_score;
  const arrow = score !== null ? (score < 0 ? '▲ BUY' : '▼ SELL') : '';
  _setSigChip('sc-composite',  score !== null ? `${fmtSigned(score, 2)} ${arrow}` : '—',
    score !== null ? scoreHex(score) : '#888');

  const zf = lc.zscore_full;
  _setSigChip('sc-z-full', zf !== null && zf !== undefined ? `Z ${fmtSigned(zf, 2)}σ` : '—',
    zf !== null ? (zf < 0 ? COLORS.pos : COLORS.neg) : COLORS.text);

  _setSigChip('sc-z-260d', rzLast !== null && rzLast !== undefined ? `Z500 ${fmtSigned(rzLast, 2)}σ` : '—',
    rzLast !== null ? (rzLast < 0 ? COLORS.pos : COLORS.neg) : COLORS.text);

  const pct = d.percentile;
  _setSigChip('sc-pct', pct !== null && pct !== undefined ? `${pct}th${pct >= 90 ? ' ⚠' : ''}` : '—',
    pct !== null ? (pct >= 90 ? COLORS.neg : pct >= 70 ? COLORS.warn : COLORS.text) : COLORS.text);

  const ry = d.roll_yield;
  _setSigChip('sc-roll-yield', ry !== null && ry !== undefined ? `${fmtSigned(ry, 1)}% RY` : '—',
    ry !== null ? (ry > 0 ? COLORS.pos : COLORS.neg) : COLORS.text);

  const hl = d.ou_halflife;
  _setSigChip('sc-ou-hl', hl !== null && hl !== undefined ? `${Math.round(hl)}d HL` : '—', COLORS.text);
}

function _setSigChip(id, text, color) {
  const el = document.getElementById(id);
  if (!el) return;
  const v = el.querySelector('.sig-chip-val');
  if (v) { v.textContent = text; v.style.color = color; }
}

function _renderMetricGrid(d) {
  const lc   = d.latest_calcs || {};
  const adf  = d.adf || {};
  const dd   = d.max_drawdown || {};
  const beta = d.beta_to_front || {};
  const sk   = d.skew_kurt || {};
  const v    = d.var || {};
  const rc   = d.regime_conditional || {};
  const sr   = d.seasonal_rank || {};
  const r16  = d.range16y || {};
  const r52  = d.range52w || {};

  // Section 1 — Spread Valuation
  _fillCards('ms-technical', [
    { label: 'Close',      val: d.current?.close !== undefined ? fmtSigned(d.current.close, 3) : null },
    { label: 'VWAP 20D',  val: d.spread_vwap_20d != null ? fmtSigned(d.spread_vwap_20d, 3) : null },
    { label: 'vs Seas',   val: d.seasonal_dev != null ? fmtSigned(d.seasonal_dev, 3) : null, cls: signCls(d.seasonal_dev) },
    { label: 'Z 10Y',     val: lc.zscore_struct != null ? fmtSigned(lc.zscore_struct, 2) + 'σ' : null, cls: signCls(lc.zscore_struct) },
    { label: 'Seasonal σ', val: d.seasonal_sigma != null ? d.seasonal_sigma.toFixed(2) : null, cls: signCls(d.seasonal_sigma) },
  ]);

  // Section 2 — Mean Reversion
  const mrCards = [
    { label: 'OU Half-Life', val: d.ou_halflife !== null && d.ou_halflife !== undefined ? `${Math.round(d.ou_halflife)}d` : null },
    { label: 'ADF p-val',    val: adf.p_value !== undefined ? `p=${adf.p_value}` : null, cls: adf.p_value < 0.05 ? 'green' : 'red' },
    { label: 'ADF',          val: adf.stationary !== undefined ? null : null, badge: adf.stationary ? 'YES' : (adf.stationary === false ? 'NO' : null) },
    { label: 'ADF t-stat',   val: adf.adf_stat !== undefined ? `t=${adf.adf_stat?.toFixed(2)}` : null, cls: 'grey' },
    { label: 'Crit 1%',      val: adf.critical_1pct !== undefined ? `${adf.critical_1pct}` : null, cls: 'grey' },
    { label: 'Crit 5%',      val: adf.critical_5pct !== undefined ? `${adf.critical_5pct}` : null, cls: 'grey' },
  ];
  // Append edge stats for the current Z tier
  const zTier    = _zTierKey(lc.zscore_full);
  const cellStat = zTier ? (d.edge_stats || {})[zTier] || {} : {};
  if (cellStat['5d'] && cellStat['5d'].n >= 10) {
    mrCards.push({
      label: 'Edge 5d',
      val:   `${fmtSigned(cellStat['5d'].mean * 100, 1)}% (${(cellStat['5d'].hit_rate * 100).toFixed(0)}%)`,
    });
    if (cellStat['10d']) {
      mrCards.push({
        label: 'Edge 10d',
        val:   `${fmtSigned(cellStat['10d'].mean * 100, 1)}% (${(cellStat['10d'].hit_rate * 100).toFixed(0)}%)`,
      });
    }
  }
  _fillCards('ms-mean-rev', mrCards);

  // Section 3 — Risk (asymmetric Long/Short VaR; falls back to legacy keys if cache not rebuilt)
  _fillCards('ms-risk', [
    { label: 'L VaR 1d 95%', val: (v.long_var_1d_95_per_cwt ?? v.var_1d_95_per_cwt) !== undefined ? `$${v.long_var_1d_95_per_cwt ?? v.var_1d_95_per_cwt}/cwt` : null },
    { label: 'L VaR 1d 99%', val: (v.long_var_1d_99_per_cwt ?? v.var_1d_99_per_cwt) !== undefined ? `$${v.long_var_1d_99_per_cwt ?? v.var_1d_99_per_cwt}/cwt` : null },
    { label: 'S VaR 1d 95%', val: v.short_var_1d_95_per_cwt !== undefined ? `$${v.short_var_1d_95_per_cwt}/cwt` : null },
    { label: 'S VaR 1d 99%', val: v.short_var_1d_99_per_cwt !== undefined ? `$${v.short_var_1d_99_per_cwt}/cwt` : null },
    { label: 'VaR 5d 95%',   val: v.var_5d_95_per_cwt !== undefined ? `$${v.var_5d_95_per_cwt}/cwt` : null },
    { label: 'VaR/ct',       val: v.var_1d_95_per_contract !== undefined ? `$${v.var_1d_95_per_contract}/ct` : null },
    { label: 'Max Drawdown', val: dd.max_drawdown_cwt !== undefined ? fmtSigned(dd.max_drawdown_cwt, 2) : null, cls: 'red' },
    { label: 'DD Days',      val: dd.duration_calendar_days !== undefined ? `${dd.duration_calendar_days}d` : null },
    { label: 'DD Period',    val: (dd.peak_date && dd.trough_date) ? `${dd.peak_date?.slice(0,7)} → ${dd.trough_date?.slice(0,7)}` : null, cls: 'grey' },
    { label: 'Beta',         val: beta.beta !== undefined ? `β=${beta.beta}` : null },
    { label: 'R²',           val: beta.r_squared !== undefined ? `R²=${beta.r_squared}` : null },
    { label: 'Beta p-val',   val: beta.p_value !== undefined ? `p=${beta.p_value}` : null, cls: beta.p_value < 0.05 ? 'green' : 'red' },
  ]);

  // Section 4 — Seasonal (top 3 analogs from rankings array)
  const rankings = sr.rankings || [];
  const seasonalCards = [
    { label: 'Best Analog', val: sr.closest_year !== undefined ? String(sr.closest_year) : null },
    { label: 'Analog Corr', val: sr.closest_correlation !== undefined ? `r=${sr.closest_correlation}` : null },
  ];
  rankings.slice(1, 4).forEach((r, i) => {
    seasonalCards.push({ label: `Analog #${i + 2}`, val: `${r.year}  r=${r.correlation}` });
  });
  seasonalCards.push(
    { label: 'Skewness', val: sk.skewness !== undefined ? fmtSigned(sk.skewness, 2) : null },
    { label: 'Kurtosis', val: sk.excess_kurtosis !== undefined ? sk.excess_kurtosis?.toFixed(2) : null },
  );
  _fillCards('ms-seasonal', seasonalCards);

  // Section 5 — Carry & Structure
  const back = rc.backwardation || {};
  const cont = rc.contango      || {};
  const ryRank = d.roll_yield_rank != null ? ` (${d.roll_yield_rank}th)` : '';
  _fillCards('ms-carry', [
    { label: 'Roll Yield', val: d.roll_yield != null ? fmtSigned(d.roll_yield, 1) + '%' + ryRank : null,
      cls: d.roll_yield > 0 ? 'green' : 'red' },
    { label: 'Shadow CY',  val: d.shadow_convenience_yield != null ? fmtSigned(d.shadow_convenience_yield, 1) + '%' : null },
    { label: 'OI Signal',  val: d.oi_signature && d.oi_signature !== 'UNKNOWN' ? d.oi_signature : null,
      cls: d.oi_signature === 'NEW_MONEY' ? 'green' : d.oi_signature === 'LIQUIDATION' ? 'red' : '' },
    { label: 'Kink Z',     val: d.kink_z != null ? fmtSigned(d.kink_z, 2) + 'σ' : null, cls: signCls(d.kink_z) },
    { label: 'Spread β',   val: beta.beta != null ? `β=${beta.beta}` : null },
    { label: 'Momo',       val: d.momentum_regime || null,
      cls: d.momentum_regime === 'TRENDING' ? 'warn' : d.momentum_regime === 'MEAN_REVERTING' ? 'green' : '' },
    { label: 'Carry/Momo', val: d.carry_momo_quad || null },
    { label: 'Roll Pres',  val: d.roll_pressure_score != null ? d.roll_pressure_score.toFixed(2) + (d.roll_warning ? ' ⚠' : '') : null,
      cls: d.roll_warning ? 'warn' : '' },
    { label: 'Regime Back', val: back.mean != null ? `${back.mean} ± ${back.std}` : null },
    { label: 'Regime Cont', val: cont.mean != null ? `${cont.mean} ± ${cont.std}` : null },
    { label: '16Y High',    val: r16.high !== undefined ? fmtSigned(r16.high, 3) : null, cls: 'green' },
    { label: '16Y Mean',    val: r16.mean !== undefined ? fmtSigned(r16.mean, 3) : null },
    { label: '16Y Low',     val: r16.low  !== undefined ? fmtSigned(r16.low,  3) : null, cls: 'red' },
    { label: '52W High',    val: r52.high !== undefined ? fmtSigned(r52.high, 3) : null },
    { label: '52W Low',     val: r52.low  !== undefined ? fmtSigned(r52.low,  3) : null },
  ]);
}

function _fillCards(containerId, cards) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = cards.map(c => {
    let display = c.val !== null && c.val !== undefined ? c.val : '—';
    if (c.badge !== null && c.badge !== undefined) {
      display = `<span class="mc-badge ${c.badge === 'YES' ? 'badge-yes' : 'badge-no'}">${c.badge}</span>`;
    }
    const cls = (c.val !== null && c.val !== undefined && c.cls) ? c.cls : '';
    return `<div class="metric-card"><div class="mc-label">${c.label}</div><div class="mc-val ${cls}">${display}</div></div>`;
  }).join('');
}

// ── Seasonal: compute period-specific mean/std per DOY from prior_years ───────

function _computeSeasonalAvg(prior, curYear, n) {
  const winYears = Object.keys(prior).map(Number)
    .filter(y => y < curYear && y >= curYear - n);

  const doyData = {};
  winYears.forEach(yr => {
    (prior[String(yr)] || []).forEach(([doy, val]) => {
      if (!doyData[doy]) doyData[doy] = [];
      doyData[doy].push(val);
    });
  });

  const doys = Object.keys(doyData).map(Number).sort((a, b) => a - b);
  const rawAvg = {}, rawStd = {};
  doys.forEach(doy => {
    const vals = doyData[doy];
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    rawAvg[doy] = mean;
    if (vals.length > 1) {
      const variance = vals.reduce((a, b) => a + (b - mean) ** 2, 0) / (vals.length - 1);
      rawStd[doy] = Math.sqrt(variance);
    } else {
      rawStd[doy] = 0;
    }
  });

  // 7-point smoothing
  const hw = 3;
  const sAvg = {}, sStd = {};
  doys.forEach((doy, i) => {
    const slice = doys.slice(Math.max(0, i - hw), Math.min(doys.length, i + hw + 1));
    const aVals = slice.map(d => rawAvg[d]).filter(v => !isNaN(v));
    const sVals = slice.map(d => rawStd[d]).filter(v => !isNaN(v));
    sAvg[doy] = aVals.reduce((a, b) => a + b, 0) / aVals.length;
    sStd[doy] = sVals.reduce((a, b) => a + b, 0) / sVals.length;
  });

  return { avg: sAvg, std: sStd, doys };
}


// ── Seasonal Overlay Chart ─────────────────────────────────────────────────

function _renderSeasonalChart(d) {
  const yrs        = _seasonalYrs;
  const prior      = d.prior_years || {};
  const analogYear = (d.seasonal_rank || {}).closest_year;
  const allYears   = Object.keys(prior).map(Number).sort();
  const curYear    = allYears.length ? allYears[allYears.length - 1] : new Date().getFullYear();
  const winYears   = allYears.filter(y => y < curYear && y >= curYear - yrs);
  const calc       = _computeSeasonalAvg(prior, curYear, yrs);
  const traces     = [];

  if (_showPrior) {
    // All non-analog prior years first (very dim)
    winYears.forEach(yr => {
      if (yr === analogYear) return;
      const pts = prior[String(yr)] || [];
      traces.push({
        x: pts.map(p => doyToDateStr(p[0])),
        y: pts.map(p => p[1]),
        mode: 'lines',
        line: { color: 'rgba(60,80,70,0.20)', width: 0.7 },
        hoverinfo: 'skip',
      });
    });
    // Analog year: teal, dashed — clearly distinct from current-year orange
    if (analogYear && winYears.includes(analogYear)) {
      const pts = prior[String(analogYear)] || [];
      traces.push({
        x: pts.map(p => doyToDateStr(p[0])),
        y: pts.map(p => p[1]),
        mode: 'lines',
        line: { color: '#80cbc4', width: 1.6, dash: 'dash' },
        hovertemplate: `${analogYear} ★ analog: %{y:.3f}<extra></extra>`,
      });
    }
  }

  // ±1σ band from the selected period
  if (_showBand && calc.doys.length) {
    const xs  = calc.doys.map(doy => doyToDateStr(doy));
    const yLo = calc.doys.map(doy => calc.avg[doy] - calc.std[doy]);
    const yHi = calc.doys.map(doy => calc.avg[doy] + calc.std[doy]);
    traces.push({
      x: [...xs, ...xs.slice().reverse()],
      y: [...yHi, ...yLo.slice().reverse()],
      fill: 'toself', fillcolor: COLORS.band,
      line: { color: 'transparent' }, hoverinfo: 'skip',
    });
  }

  // Smoothed period average line
  if (calc.doys.length) {
    traces.push({
      x: calc.doys.map(doy => doyToDateStr(doy)),
      y: calc.doys.map(doy => calc.avg[doy]),
      mode: 'lines',
      line: { color: COLORS.pos, width: 1.5, dash: 'dot' },
      hovertemplate: `${yrs}Y Avg: %{y:.3f}<extra></extra>`,
    });
  }

  // Current year: orange, thick — clearly the active spread
  const curPts = prior[String(curYear)] || [];
  if (curPts.length) {
    traces.push({
      x: curPts.map(p => doyToDateStr(p[0])),
      y: curPts.map(p => p[1]),
      mode: 'lines+markers',
      line: { color: COLORS.le, width: 2.5 },
      marker: { color: COLORS.le, size: curPts.map((_, i) => i === curPts.length - 1 ? 6 : 0) },
      hovertemplate: `${curYear}: %{y:.3f}<extra></extra>`,
    });
  }

  const todayDOY = Math.floor((Date.now() - Date.UTC(new Date().getFullYear(), 0, 0)) / 86400000);
  const layout = Object.assign({}, PLOTLY_BASE, {
    height: 240,
    xaxis: Object.assign({}, PLOTLY_BASE.xaxis, { tickformat: '%b', range: ['2000-01-01', '2000-12-31'], dtick: 'M1' }),
    shapes: [{ type:'line', x0:doyToDateStr(todayDOY), x1:doyToDateStr(todayDOY), y0:0, y1:1, yref:'paper', line:{color:COLORS.muted,width:1,dash:'dash'} }],
  });

  Plotly.react('seasonal-chart', traces, layout, PLOTLY_CFG);
}


// ── Full History Chart ─────────────────────────────────────────────────────

function _renderHistoryChart(d) {
  const series = d.series || [];
  if (!series.length) return;

  const r16      = d.range16y || {};
  const allDates = series.map(p => p[0]);
  const allVals  = series.map(p => p[1]);

  // Slice to zoom window so Plotly auto-scales Y-axis to visible data only
  const [rangeStart] = _historyRange(allDates);
  const startIdx = Math.max(0, allDates.findIndex(s => s >= rangeStart));
  const dates = allDates.slice(startIdx);
  const vals  = allVals.slice(startIdx);

  const curYr = new Date().getFullYear();
  const split = dates.findIndex(s => s.startsWith(String(curYr)));
  const traces = [];

  if (split > 0) {
    traces.push({ x: dates.slice(0, split), y: vals.slice(0, split), mode:'lines', line:{color:COLORS.muted,width:1}, hovertemplate:'%{x|%Y-%m-%d}: %{y:.3f}<extra>Prior</extra>' });
    traces.push({ x: dates.slice(split),    y: vals.slice(split),    mode:'lines', line:{color:COLORS.le,width:2},    hovertemplate:`%{x|%Y-%m-%d}: %{y:.3f}<extra>${curYr}</extra>` });
  } else {
    traces.push({ x: dates, y: vals, mode:'lines', line:{color:COLORS.le,width:1.5}, hovertemplate:'%{x|%Y-%m-%d}: %{y:.3f}<extra></extra>' });
  }

  const shapes = [];
  if (r16.high !== null && r16.high !== undefined) shapes.push({ type:'line', x0:dates[0], x1:dates[dates.length-1], y0:r16.high, y1:r16.high, line:{color:'#4caf5050',width:1,dash:'dash'} });
  if (r16.low  !== null && r16.low  !== undefined) shapes.push({ type:'line', x0:dates[0], x1:dates[dates.length-1], y0:r16.low,  y1:r16.low,  line:{color:'#f4433650',width:1,dash:'dash'} });

  const layout = Object.assign({}, PLOTLY_BASE, {
    height: 240,
    shapes,
    xaxis: Object.assign({}, PLOTLY_BASE.xaxis, { tickformat: _historyZoom === 'all' ? '%Y' : '%b %Y' }),
  });

  Plotly.react('history-chart', traces, layout, PLOTLY_CFG);
}

function _historyRange(dates) {
  if (!dates || !dates.length) return [undefined, undefined];
  const last = dates[dates.length - 1];
  const now  = new Date(last);
  if (_historyZoom === '1y') return [_dateOffset(now, -1), last];
  if (_historyZoom === '3y') return [_dateOffset(now, -3), last];
  if (_historyZoom === '5y') return [_dateOffset(now, -5), last];
  return [dates[0], last];
}


// ── Rolling Z-Score (500d) Chart ──────────────────────────────────────────

function _renderZscoreChart(d) {
  const series = d.rolling_zscore_500d || [];
  if (!series.length) return;

  const xs = series.map(p => p[0]);
  const ys = series.map(p => p[1]);

  const traces = [
    { x: xs, y: ys, mode: 'lines', line: { color: COLORS.gf, width: 1.5 }, hovertemplate: '%{x|%Y-%m-%d}: %{y:.2f}σ<extra></extra>' },
  ];

  const last = xs[xs.length - 1];
  const shapes = [-2, -1, 1, 2].map(v => ({
    type: 'line', x0: xs[0], x1: last, y0: v, y1: v,
    line: { color: v === -1 || v === 1 ? '#44556688' : '#55667788', width: 1, dash: 'dash' },
  }));

  const layout = Object.assign({}, PLOTLY_BASE, {
    height: 190,
    shapes,
    yaxis: Object.assign({}, PLOTLY_BASE.yaxis, { zeroline: true, zerolinecolor: '#2a3040', zerolinewidth: 1 }),
  });

  Plotly.react('zscore-chart', traces, layout, PLOTLY_CFG);
}


// ── Current Year: Close + Z-Score Overlay Chart ───────────────────────────

function _renderOverlayChart(d) {
  const series  = d.series || [];
  const zSeries = d.rolling_zscore_500d || [];
  if (!series.length) return;

  const zMap = {};
  zSeries.forEach(p => { zMap[p[0]] = p[1]; });

  // Always show current calendar year only
  const curYr      = new Date().getFullYear();
  const curYrStart = `${curYr}-01-01`;
  const allDates   = series.map(p => p[0]);
  const startIdx   = Math.max(0, allDates.findIndex(s => s >= curYrStart));
  const sliced     = series.slice(startIdx);

  const dates  = sliced.map(p => p[0]);
  const closes = sliced.map(p => p[1]);
  const zVals  = dates.map(dt => zMap[dt] ?? null);
  const last   = dates[dates.length - 1];

  const traces = [
    { x: dates, y: closes, mode: 'lines', yaxis: 'y',
      line: { color: COLORS.le, width: 2 },
      hovertemplate: '%{x|%Y-%m-%d}: %{y:.3f}<extra>Close</extra>' },
    { x: dates, y: zVals, mode: 'lines', yaxis: 'y2',
      line: { color: COLORS.gf, width: 1.5 },
      hovertemplate: '%{x|%Y-%m-%d}: %{y:.2f}σ<extra>Z-Score</extra>' },
  ];

  const layout = Object.assign({}, PLOTLY_BASE, {
    height: 270,
    yaxis:  Object.assign({}, PLOTLY_BASE.yaxis, { domain: [0, 1], title: { text: 'Close', font: { size: 9 } } }),
    yaxis2: Object.assign({}, PLOTLY_BASE.yaxis, {
      overlaying: 'y', side: 'right',
      title: { text: 'Z-Score', font: { size: 9 } },
      zeroline: true, zerolinecolor: '#2a3040',
    }),
    shapes: [
      { type:'line', x0:dates[0], x1:last, y0:-2, y1:-2, yref:'y2', line:{color:'#4caf5040',width:1,dash:'dash'} },
      { type:'line', x0:dates[0], x1:last, y0:2,  y1:2,  yref:'y2', line:{color:'#f4433640',width:1,dash:'dash'} },
    ],
  });

  Plotly.react('overlay-chart', traces, layout, PLOTLY_CFG);
}


// ── Bias Summary ───────────────────────────────────────────────────────────

function _renderBiasSummary(d) {
  const el = document.getElementById('bias-summary');
  if (!el) return;

  const score = d.composite_score;
  const zf    = (d.latest_calcs || {}).zscore_full;
  const pct   = d.percentile;
  const ry    = d.roll_yield;
  const sr    = d.seasonal_rank || {};
  const adf   = d.adf || {};
  const hl    = d.ou_halflife;
  const dev   = d.seasonal_dev;

  if (score === null || score === undefined) {
    el.textContent = 'Insufficient data to generate bias summary.';
    return;
  }

  const dir      = score < 0 ? 'BUY' : 'SELL';
  const absS     = Math.abs(score);
  const strength = absS >= 2 ? 'Strong' : absS >= 1 ? 'Moderate' : 'Weak';
  let summary = `${strength} ${dir} bias (composite ${fmtSigned(score, 2)}).`;

  const parts = [];
  if (zf !== null && zf !== undefined) {
    parts.push(`${Math.abs(zf).toFixed(1)}σ ${zf < 0 ? 'below' : 'above'} historical mean`);
  }
  if (pct !== null && pct !== undefined) {
    parts.push(`${pct}th percentile for this calendar week`);
  }
  if (parts.length) summary += ` Currently ${parts.join(', ')}.`;

  const regimeParts = [];
  if (sr.closest_year) regimeParts.push(`tracking ${sr.closest_year} analog (r=${sr.closest_correlation})`);
  if (dev !== null && dev !== undefined) {
    regimeParts.push(`${Math.abs(dev).toFixed(3)} ${dev > 0 ? 'above' : 'below'} seasonal average`);
  }
  if (ry !== null && ry !== undefined) {
    regimeParts.push(`roll yield ${fmtSigned(ry, 1)}%`);
  }
  if (d.carry_momo_quad) {
    regimeParts.push(d.carry_momo_quad);
  }
  if (regimeParts.length) summary += ` ${regimeParts.join('; ')}.`;

  if (adf.stationary && hl) {
    summary += ` Stationary (ADF p=${adf.p_value}), half-life ${Math.round(hl)} days.`;
  }

  el.textContent = summary;
  el.style.color = score < 0 ? COLORS.pos : score > 0 ? COLORS.neg : COLORS.text;
}


// ════════════════════════════════════════════════════════════════════════════
// PORTFOLIO PAGE
// ════════════════════════════════════════════════════════════════════════════

function initPortfolio() {
  Promise.all([
    fetch('/api/portfolio').then(r => r.json()),
    fetch('/api/curve').then(r => r.json()),
    fetch('/api/cot').then(r => r.json()),
    fetch('/api/roll-windows').then(r => r.json()),
  ]).then(([port, curve, cot, rw]) => {
    _pollDataStatus();
    setInterval(_pollDataStatus, 300000);
    _renderTopbar(curve.updated, curve.le_curve, curve.gf_curve);
    _renderPortfolioHeader(curve.regime, cot, rw, port);
    _renderCorrelationHeatmap(port.correlation_matrix);
    _renderPCAChart(port.pca);
    _renderPCAScatter(port.pca);
    _renderMiniCurveChart('le-curve-chart', curve.le_curve || [], COLORS.le);
    _renderMiniCurveChart('gf-curve-chart', curve.gf_curve || [], COLORS.gf);
    _renderConvexitySub('le-convexity-sub', port.curve_convexity_le);
    _renderConvexitySub('gf-convexity-sub', port.curve_convexity_gf);
  });
}

function _renderPortfolioHeader(r, cot, rw, port) {
  if (!r) return;

  const structure = r.market_structure || '—';
  const sEl = _setCell('ph-structure-val', structure);
  if (sEl) sEl.className = 'rc-val ' + (structure === 'BACKWARDATION' ? 'neg' : 'pos');

  const leC = port.curve_convexity_le;
  _setCell('ph-le-conv-val', leC !== null && leC !== undefined ? `${leC > 0 ? '+' : ''}${leC} (${leC > 0 ? 'convex' : 'concave'})` : '—');
  const gfC = port.curve_convexity_gf;
  _setCell('ph-gf-conv-val', gfC !== null && gfC !== undefined ? `${gfC > 0 ? '+' : ''}${gfC} (${gfC > 0 ? 'convex' : 'concave'})` : '—');

  if (rw) {
    const gsciEl = _setCell('ph-gsci-val', rw.gsci_active ? `DAY ${rw.gsci_day}/5` : 'INACTIVE');
    if (gsciEl) gsciEl.className = 'rc-val ' + (rw.gsci_active ? 'warn' : 'muted');
    const bcomEl = _setCell('ph-bcom-val', rw.bcom_active ? `DAY ${rw.bcom_day}/5` : 'INACTIVE');
    if (bcomEl) bcomEl.className = 'rc-val ' + (rw.bcom_active ? 'warn' : 'muted');
  }

  if (cot && cot.available) {
    _setCell('ph-cot-le-val', cot.le_mm_net !== null ? fmtK(cot.le_mm_net) : '—');
    _setCell('ph-cot-le-sub', cot.le_mm_net_percentile !== null ? `${cot.le_mm_net_percentile}th pct` : '');
    _setCell('ph-cot-gf-val', cot.gf_mm_net !== null ? fmtK(cot.gf_mm_net) : '—');
    _setCell('ph-cot-gf-sub', cot.gf_mm_net_percentile !== null ? `${cot.gf_mm_net_percentile}th pct` : '');
  }

  const ext = r.extremes_count;
  const extEl = _setCell('ph-extremes-val', ext !== null ? `${ext} / ${r.extremes_total}` : '—');
  if (extEl) extEl.className = 'rc-val ' + (ext > 0 ? 'warn' : '');
}

function _renderCorrelationHeatmap(matrix) {
  if (!matrix || !Object.keys(matrix).length) return;

  const ids    = Object.keys(matrix);
  const labels = ids.map(id => { const p = id.split('-'); return p.length === 2 ? `${p[0].slice(2)}/${p[1].slice(2)}` : id; });
  const z      = ids.map(rowId => ids.map(colId => (matrix[rowId] || {})[colId] ?? null));

  const trace = {
    type: 'heatmap',
    x: labels, y: labels, z,
    colorscale: 'RdBu',
    reversescale: true,
    zmin: -1, zmax: 1,
    hovertemplate: '%{y} × %{x}: %{z:.3f}<extra></extra>',
    colorbar: { thickness: 10, len: 0.8, tickfont: { size: 8, color: '#666' } },
  };

  const layout = Object.assign({}, PLOTLY_BASE, {
    height: 410,
    margin: { l: 60, r: 10, t: 10, b: 60 },
    xaxis: Object.assign({}, PLOTLY_BASE.xaxis, { tickangle: -45, tickfont: { size: 8 } }),
    yaxis: Object.assign({}, PLOTLY_BASE.yaxis, { tickfont: { size: 8 }, autorange: 'reversed' }),
  });

  Plotly.newPlot('heatmap-chart', [trace], layout, PLOTLY_CFG);
}

function _renderPCAChart(pca) {
  if (!pca || !pca.explained_variance_ratio) return;

  const evr    = pca.explained_variance_ratio;
  const labels = evr.map((_, i) => `PC${i + 1}`);
  const pcts   = evr.map(v => +(v * 100).toFixed(1));

  const trace = {
    x: labels, y: pcts, type: 'bar',
    marker: { color: COLORS.le },
    hovertemplate: '%{x}: %{y:.1f}%<extra></extra>',
  };

  const layout = Object.assign({}, PLOTLY_BASE, {
    height: 160,
    margin: { l: 35, r: 8, t: 8, b: 25 },
    yaxis: Object.assign({}, PLOTLY_BASE.yaxis, { ticksuffix: '%' }),
  });

  Plotly.newPlot('pca-chart', [trace], layout, PLOTLY_CFG);

  // Cumulative annotation
  const cumv = pca.cumulative_variance || [];
  const pct3 = cumv.length >= 3 ? (cumv[2] * 100).toFixed(0) : null;
  if (pct3) setText('pca-cumulative', `PC1–PC3 explain ${pct3}% of variance`);

  // Loadings chips
  const comps = pca.components || {};
  _renderLoadings('pc1-loadings', comps.PC1 || {});
  _renderLoadings('pc2-loadings', comps.PC2 || {});
}

function _renderPCAScatter(pca) {
  const el = document.getElementById('pca-scatter');
  if (!el || !pca || !pca.components) return;

  const pc1  = pca.components.PC1 || {};
  const pc2  = pca.components.PC2 || {};
  const sids = Object.keys(pc1);
  if (!sids.length) return;

  const tiers = window.SPREAD_TIERS || {};

  const tierGroups = { 1: [], 2: [], 3: [], 4: [] };
  sids.forEach(sid => {
    const parts = sid.split('-');
    const label = parts.length === 2 ? `${parts[0].slice(2)}/${parts[1].slice(2)}` : sid;
    const tier  = tiers[sid] || 4;
    tierGroups[tier].push({ x: pc1[sid], y: pc2[sid], label });
  });

  const tierNames = { 1: 'T1 Critical', 2: 'T2 High', 3: 'T3 Active', 4: 'T4 Skip' };
  const traces = Object.entries(tierGroups)
    .filter(([, pts]) => pts.length)
    .map(([t, pts]) => ({
      x: pts.map(p => p.x),
      y: pts.map(p => p.y),
      text: pts.map(p => p.label),
      mode: 'markers+text',
      type: 'scatter',
      name: tierNames[t],
      textposition: 'top center',
      textfont: { size: 8 },
      marker: { color: COLORS[`tier${t}`], size: 8, opacity: 0.85 },
      hovertemplate: '%{text}<br>PC1: %{x:.3f}<br>PC2: %{y:.3f}<extra></extra>',
    }));

  const layout = Object.assign({}, PLOTLY_BASE, {
    height: 220,
    showlegend: true,
    legend: { font: { size: 9 }, x: 1, xanchor: 'right', y: 1 },
    margin: { l: 40, r: 60, t: 10, b: 30 },
    xaxis: Object.assign({}, PLOTLY_BASE.xaxis, {
      title: { text: 'PC1 (Level proxy)', font: { size: 9 } },
      zeroline: true, zerolinecolor: '#2a3040',
    }),
    yaxis: Object.assign({}, PLOTLY_BASE.yaxis, {
      title: { text: 'PC2 (Slope proxy)', font: { size: 9 } },
      zeroline: true, zerolinecolor: '#2a3040',
    }),
  });

  Plotly.newPlot('pca-scatter', traces, layout, PLOTLY_CFG);
}

function _renderLoadings(elId, loadings) {
  const el = document.getElementById(elId);
  if (!el) return;
  const sorted = Object.entries(loadings).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 10);
  el.innerHTML = sorted.map(([sid, v]) => {
    const parts = sid.split('-');
    const lbl   = parts.length === 2 ? `${parts[0].slice(2)}/${parts[1].slice(2)}` : sid;
    const cls   = v > 0 ? 'pca-pos' : 'pca-neg';
    return `<span class="pca-loading-chip ${cls}">${lbl} ${v > 0 ? '+' : ''}${v.toFixed(2)}</span>`;
  }).join('');
}

function _renderMiniCurveChart(elId, curve, color) {
  const el = document.getElementById(elId);
  if (!el || !curve.length) return;

  const labels = curve.map(c => c.month || '?');
  const prices = curve.map(c => c.close);

  const trace = {
    x: labels, y: prices, type: 'bar',
    marker: { color: color + '88' },
    hovertemplate: '%{x}: %{y:.2f}<extra></extra>',
  };

  const layout = Object.assign({}, PLOTLY_BASE, {
    height: 90,
    margin: { l: 30, r: 4, t: 4, b: 18 },
    xaxis: Object.assign({}, PLOTLY_BASE.xaxis, { tickfont: { size: 7 } }),
    yaxis: Object.assign({}, PLOTLY_BASE.yaxis, { tickfont: { size: 7 } }),
  });

  Plotly.newPlot(elId, [trace], layout, PLOTLY_CFG);
}

function _renderConvexitySub(elId, coef) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (coef === null || coef === undefined) { el.textContent = ''; return; }
  const dir = coef > 0 ? 'convex' : 'concave';
  el.textContent = `${coef > 0 ? '+' : ''}${coef} (${dir})`;
}


// ════════════════════════════════════════════════════════════════════════════
// TOGGLE HANDLERS
// ════════════════════════════════════════════════════════════════════════════

function togglePriorYears() {
  _showPrior = !_showPrior;
  document.getElementById('tog-prior').classList.toggle('active', _showPrior);
  if (_researchData) _renderSeasonalChart(_researchData);
}

function toggleBand() {
  _showBand = !_showBand;
  document.getElementById('tog-band').classList.toggle('active', _showBand);
  if (_researchData) _renderSeasonalChart(_researchData);
}

function setSeasonalWindow(yrs) {
  _seasonalYrs = yrs;
  [5, 10, 15].forEach(y => {
    document.getElementById(`tog-${y}yr`)?.classList.toggle('active', yrs === y);
  });
  if (_researchData) _renderSeasonalChart(_researchData);
}

function setHistoryZoom(zoom) {
  _historyZoom = zoom;
  ['1y','3y','5y','all'].forEach(z => {
    document.getElementById(`tog-${z}`)?.classList.toggle('active', z === zoom);
  });
  if (_researchData) _renderHistoryChart(_researchData);
}

// ════════════════════════════════════════════════════════════════════════════
// SHARED UTILITIES
// ════════════════════════════════════════════════════════════════════════════

function _renderTopbar(updated, le, gf) {
  const fmtFront = (curve) => {
    if (!curve || !curve[0]) return '—';
    const c = curve[0];
    const m = MONTH_NAMES[c.symbol && c.symbol[2]] || '';
    return `${m}${c.symbol ? c.symbol.slice(3) : ''} ${c.close !== null ? c.close.toFixed(2) : '—'}`;
  };
  setText('le-front', fmtFront(le));
  setText('gf-front', fmtFront(gf));
  setText('updated',  updated ? fmtDate(updated) : '—');
}

function _setCell(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
  return el;
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function scoreHex(score) {
  if (score === null || score === undefined) return '#888';
  for (const { max, hex } of SCORE_COLORS) {
    if (score <= max) return hex;
  }
  return SCORE_COLORS[SCORE_COLORS.length - 1].hex;
}

function fmtSigned(v, dp) {
  if (v === null || v === undefined || typeof v !== 'number') return '—';
  const s = v.toFixed(dp);
  return v >= 0 ? `+${s}` : s;
}

function fmtK(v) {
  if (v === null || v === undefined || typeof v !== 'number') return '—';
  return v >= 1000 || v <= -1000 ? `${(v / 1000).toFixed(1)}k` : String(v);
}

function fmtDate(ds) {
  if (!ds) return '—';
  const [y, m, d] = ds.split('-');
  return `${MON_ABBR[+m - 1]} ${+d}, ${y}`;
}

function bbCls(v) {
  if (v === null || v === undefined) return '';
  return v < 0.2 ? 'green' : v > 0.8 ? 'red' : '';
}

function signCls(v) {
  if (v === null || v === undefined) return '';
  return v > 0 ? 'green' : v < 0 ? 'red' : '';
}

function _zTierKey(z) {
  if (z == null) return null;
  if (z >  2)   return 'z_gt2';
  if (z >  1)   return 'z_1to2';
  if (z < -2)   return 'z_lt_neg2';
  if (z < -1)   return 'z_neg2toneg1';
  return 'z_neg1to1';
}

function doyToDateStr(doy) {
  const d = new Date(Date.UTC(2000, 0, doy));
  return d.toISOString().slice(0, 10);
}

function _pollDataStatus() {
  fetch('/api/data-status')
    .then(r => r.json())
    .then(d => {
      const dot   = document.getElementById('pulse-dot');
      const label = document.getElementById('pulse-label');
      if (!dot || !label) return;
      if (d.status === 'LIVE') {
        dot.className   = 'pulse-dot live';
        label.textContent = 'LIVE';
      } else if (d.status === 'STALE') {
        dot.className   = 'pulse-dot stale';
        label.textContent = `STALE ${d.age_hours}h`;
      } else {
        dot.className   = 'pulse-dot';
        label.textContent = d.status || '-';
      }
    })
    .catch(() => {});
}

function _dateOffset(date, yearsOffset) {
  const d = new Date(date);
  d.setFullYear(d.getFullYear() + yearsOffset);
  return d.toISOString().slice(0, 10);
}
