/* WCL raid dashboard - client side.
   Boss tabs are rendered entirely here from the compressed per-boss payload
   (one <script type="application/gzip+base64" id="data_tabN"> per boss). */
function dashShowError(err) {
  const strip = document.querySelector('.tabs');
  if (strip) strip.removeAttribute('inert');   // never leave the page in its loading state after a failed load
  document.querySelectorAll('[aria-busy]').forEach(n => n.removeAttribute('aria-busy'));
  document.querySelectorAll('.skeleton').forEach(n => n.remove());
  const el = document.getElementById('jsError');
  if (!el) return;
  el.hidden = false;
  const text = err && typeof err === 'object' ? `${err.message || err}\n${err.stack || ''}` : String(err);
  if (!el.textContent) el.textContent = 'The dashboard scripts hit an error, so some interactive parts may not work.';
  const pre = document.createElement('pre'); pre.style.whiteSpace = 'pre-wrap'; pre.style.fontSize = '11px'; pre.textContent = text;
  el.appendChild(pre);
}
window.addEventListener('error', e => dashShowError(e.error || e.message));
window.addEventListener('unhandledrejection', e => dashShowError(e.reason));
(async function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const REDUCED = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const SCROLL = REDUCED ? 'auto' : 'smooth';
  const store = { get: k => { try { return localStorage.getItem(k); } catch (_) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) { /* file:// without storage */ } } };

  // design tokens: the CSS file is the source; Plotly and inline SVG need the resolved strings
  const cssRoot = getComputedStyle(document.documentElement);
  const tok = name => cssRoot.getPropertyValue('--' + name).trim();
  const TOK = { ink: tok('ink'), inkDim: tok('ink-dim'), border: tok('border'), borderStrong: tok('border-strong'), borderControl: tok('border-control'),
    surfaceCard: tok('surface-card'), surfaceRaised: tok('surface-raised'), accent: tok('accent'),
    good: tok('good'), warn: tok('warn'), bad: tok('bad'), series: [1, 2, 3, 4, 5, 6].map(i => tok('series-' + i)) };

  // ---------------- small helpers ----------------
  const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
  const fmtN = n => n >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : Math.round(n).toString();
  const fmtD = s => { s = Math.round(s); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  const cls = c => String(c || '').replace(/\s+/g, '');
  const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
  const median = arr => { const s = [...arr].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : 0; };
  const topN = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n);
  const pctColor = p => { const t = Math.max(0, Math.min(1, p / 100)); return `rgb(${Math.round(60 + 160 * t)},${Math.round(180 - 120 * t)},70)`; };
  const parseCls = v => v >= 100 ? 'p-art' : v >= 99 ? 'p-leg' : v >= 95 ? 'p-ora' : v >= 75 ? 'p-pur' : v >= 50 ? 'p-blu' : v >= 25 ? 'p-gre' : 'p-gra';
  const TANKS = new Set(['Protection', 'Blood', 'Vengeance', 'Guardian', 'Brewmaster']);
  const HEALERS = new Set(['Holy', 'Discipline', 'Restoration', 'Mistweaver', 'Preservation']);
  const roleOf = spec => TANKS.has(spec) ? 'tank' : HEALERS.has(spec) ? 'healer' : 'dps';
  const ROLE_LABEL = { dps: 'DPS', healer: 'Healer', tank: 'Tank' };
  const playerCell = (name, cl, role, spec) => `<span class='player ${cls(cl)}'>${escH(name)}</span>${role ? `<span class='role'>${escH(ROLE_LABEL[role] || role)}</span>` : ''}${spec ? `<br><span class='spec'>${escH(spec)}${cl && !String(spec).endsWith(cl) ? ' ' + escH(clsLabel(cl)) : ''}</span>` : ''}`;
  // --- table helpers (quickjs-testable) ---
  // WCL class ids are CamelCase ('DemonHunter'); the spec line shows them as words ('Demon Hunter')
  const clsLabel = c => String(c).replace(/([a-z])([A-Z])/g, '$1 $2');
  const escH = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, '&#39;').replace(/"/g, '&quot;');
  const th = h => { const cls = h[1] === 'num' ? " class='right'" : ''; return h[1] === 'none' ? `<th scope='col' data-type='none'${cls}>${escH(h[0])}</th>` : `<th scope='col' data-type='${h[1]}'${cls}><button type='button' aria-label='Sort by ${escH(h[0])}'>${escH(h[0])}</button></th>`; };
  // rows after `limit` are hidden (class lowpart) behind a "Show all N" button at the end of the scroller
  const lowRow = r => { const m = /^<tr([^>]*?)\bclass=(?:'([^']*)'|"([^"]*)"|([^\s>'"]+))/.exec(r); return m ? `<tr${m[1]}class='${m[2] ?? m[3] ?? m[4]} lowpart'` + r.slice(m[0].length) : r.startsWith('<tr') ? "<tr class='lowpart'" + r.slice(3) : r; };
  const tbl = (heads, rows, extra, caption, limit) => {
    const cut = limit != null && rows.length > limit;
    const body = cut ? rows.slice(0, limit).concat(rows.slice(limit).map(lowRow)) : rows;
    return `<div class='scroller'><table class='sortable ${extra || ''}'${cut ? ` data-limit='${limit}'` : ''}>${caption ? `<caption>${escH(caption)}</caption>` : ''}<thead><tr>${heads.map(th).join('')}</tr></thead><tbody>${body.join('')}</tbody></table>${cut ? `<button type='button' class='show-all' aria-expanded='false'>Show all ${rows.length}</button>` : ''}</div>`;
  };
  const bar = (share, heal) => `<span class='bar${heal ? ' heal' : ''}' aria-hidden='true'><i style='width:${Math.max(0, Math.min(100, share)).toFixed(1)}%'></i></span>`;
  // shared empty state (mirrors empty_state() in dash/common.py)
  const emptyHtml = (what, why, action) => `<div class='empty' role='status'><strong>No ${escH(what)}</strong><span>${escH(why)}</span>${action ? `<span class='action'>${escH(action)}</span>` : ''}</div>`;
  // --- end table helpers ---
  const kpisHtml = (items, extra) => `<dl class='kpis${extra ? ' ' + extra : ''}'>${items.map(([l, v, c]) => `<div class='kpi${c ? ' ' + c : ''}'><dt>${escH(l)}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
  const resLabel = p => p.k ? 'KILL' : p.p.toFixed(1) + '%';
  // series are never told apart by hue alone
  const DASHES = ['solid', 'dash', 'dot', 'dashdot'], SYMBOLS = ['circle', 'square', 'diamond', 'triangle-up', 'x', 'star'];
  const lineStyle = i => ({ dash: DASHES[i % DASHES.length] });
  const symbolOf = i => SYMBOLS[i % SYMBOLS.length];

  // Plotly (dark, transparent) - charts are queued as placeholders and drawn once the HTML is in the DOM
  const GRID = TOK.border;
  const LAYOUT = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: TOK.ink, family: tok('font') }, margin: { l: 40, r: 20, t: 20, b: 40 },
    xaxis: { gridcolor: GRID, zerolinecolor: GRID }, yaxis: { gridcolor: GRID, zerolinecolor: GRID }, colorway: TOK.series };
  // --- pure chart helpers (quickjs-testable) ---
  // Merge the shared LAYOUT with a chart's own layout. Plotly does not grow the top margin for an
  // in-canvas title, so titled charts keep 50px there unless the caller set its own margin.
  function chartLayout(base, layout, h) {
    const lay = Object.assign({}, base, { height: h }, layout || {});
    if (lay.title && !(layout && layout.margin)) lay.margin = Object.assign({}, base.margin, { t: 50 });
    // axis labels (heatmap player names, rotated ability names) grow the margin instead of being clipped; a caller's
    // own xaxis/yaxis replaces the base axis wholesale, so this is added after the merge (the caller can still say false:
    // the phase chart does, its long diagonal phase names would squeeze a phone-width plot to a sliver)
    ['xaxis', 'yaxis'].forEach(k => { lay[k] = Object.assign({ automargin: true }, lay[k] || {}); });
    return lay;
  }
  // narrow screens (<= 700 px): legend below the plot, with 40 px more bottom margin for it. Used by drawCharts() for the
  // JS charts and by relayout for the Python-rendered ones (Home / Raid), whose legend otherwise sits over the plot
  function narrowLegend(lay) {
    return { legend: Object.assign({}, lay && lay.legend, { orientation: 'h', yanchor: 'top', y: -0.25 }),
             margin: Object.assign({}, lay && lay.margin, { b: ((lay && lay.margin && lay.margin.b) ?? 40) + 40 }) };
  }
  // Boss HP per pull (inline SVG): 6 colours x 7 dash patterns, so a colour + dash pair repeats only after 42 nights
  const SERIES_DASH = ['', '7 4', '2 3', '10 3 2 3', '1 3', '12 4', '6 2 1 2'];
  function seriesStyle(i) { return { color: TOK.series[i % TOK.series.length], dash: SERIES_DASH[i % SERIES_DASH.length] }; }
  function progScale(n, W, H) {
    const L = 52, R = 14, T = 16, B = 46, x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const sx = j => n <= 1 ? (x0 + x1) / 2 : x0 + j / (n - 1) * (x1 - x0);
    const sy = v => y0 + (100 - Math.max(0, Math.min(100, v))) / 100 * (y1 - y0);
    return { sx, sy, x0, x1, y0, y1 };
  }
  // SVG user width = the host's CSS width (capped at 920), so axis text keeps its CSS size on phones instead of
  // shrinking with a fixed 920-wide viewBox; hidden hosts (width 0) fall back to 920
  function progWidth(px) { return px > 0 ? Math.max(300, Math.min(920, Math.round(px))) : 920; }
  function bestWipe(S) {
    if (!S.length || S.some(p => p.k)) return null;
    let best = null; S.forEach(p => { if (!best || p.p < best.p) best = { i: p.i, p: p.p }; }); return best;
  }
  // HP bands shared with the pull grid legend (Task 11): kill, < 10 %, 10-40 %, >= 40 %
  function hpBand(pct, kill) { return kill ? 'kill' : pct < 10 ? 'near' : pct < 40 ? 'mid' : 'far'; }
  const BAND_COLOR = { kill: TOK.accent, near: TOK.good, mid: TOK.warn, far: TOK.bad };
  // Preparation cell: glyph (decorative) + visible have/pulls + screen-reader word, so the state never rests on colour alone
  const PREP_STATE = { 'prep-ok': ['&#10003;', 'ok'], 'prep-part': ['&#9680;', 'partial'], 'prep-fail': ['&#10005;', 'missing'] };
  function prepCell(have, pulls) {
    const c = have === pulls ? 'prep-ok' : have ? 'prep-part' : 'prep-fail', [glyph, word] = PREP_STATE[c];
    return `<td class='${c}' data-sort='${pulls ? have / pulls : 0}'><span aria-hidden='true'>${glyph}</span> ${have}/${pulls}<span class='sr-only'>${word}</span></td>`;
  }
  // "Avoidable" column: check mark when listed in avoidable.json, plus a visible review tag when it behaves like a raid mechanic
  function avoidCell(isA, review) { return `<td class='avoid'>${isA ? '&#10003;' : ''}${review ? " <span class='tag warn'>review</span>" : ''}</td>`; }
  function pointLabel(p) { return `Pull ${p.i} · ` + (p.k ? 'kill' : `${p.p.toFixed(1)} %` + (p.ph ? ` · ${p.ph}` : '')); }
  // Plotly charts: the title is an <h3> above the plot, never inside the canvas
  function chartTitle(layout) { const t = layout && layout.title; return !t ? '' : typeof t === 'string' ? t : (t.text || ''); }
  // nothing to compare: all bars and < 2 categories with a non-zero value (a phase chart whose first deaths all
  // fell in one phase), or every other trace - line, histogram (values), box (samples per box) - has < 4 values
  function shouldSkipChart(traces) {
    if (!traces || !traces.length) return true;
    if (traces.every(t => t.type === 'bar')) return new Set([].concat(...traces.map(t => (t.x || []).filter((_, i) => !t.y || t.y[i])))).size < 2;
    return traces.filter(t => t.type !== 'bar').every(t => (t.x || t.y || []).length < 4);
  }
  // the n entries ([name, {per: [...]}]) with the highest median of `per`, highest first; the input is not reordered
  function topByMedian(entries, n) {
    const med = a => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : 0; };
    return entries.map(e => [e, med(e[1].per || [])]).sort((a, b) => b[1] - a[1]).slice(0, n).map(x => x[0]);
  }
  // horizontal box plot: Plotly sets orientation per TRACE (values in x, names on y), the height goes on the layout.
  // The call site copies `orientation` onto every trace and `height` into chart().
  function boxLayout(n) { return { orientation: 'h', height: Math.max(320, 24 * n + 80) }; }
  // --- end pure chart helpers ---
  // inline SVG progression chart (DOM): progressionChartHtml() emits the figure, drawProgression() fills it after innerHTML
  const SVGNS = 'http://www.w3.org/2000/svg';
  const svgEl = (name, attrs) => { const n = document.createElementNS(SVGNS, name); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); return n; };
  function progressionChartHtml(tab, S) {
    const nights = [...new Set(S.map(p => p.n))];
    const legend = nights.map((n, i) => { const s = seriesStyle(i), c = S.filter(p => p.n === n).length; return `<li><span class='swatch' style='border-top-color:${s.color};border-top-style:${s.dash ? 'dashed' : 'solid'}'></span>${escH(n)}, ${c} pull${c === 1 ? '' : 's'}</li>`; }).join('');
    const best = bestWipe(S);
    return `<figure class='chart'><div class='chart-head'><div><h3>Boss HP remaining at the end of each pull</h3><p class='section-note'>Lower is better. ${S.length} pulls, ${nights.length} night${nights.length === 1 ? '' : 's'}.</p></div><ul class='legend' aria-label='Raid nights'>${legend}</ul></div><div class='plot-wrap' id='prog_${tab}'></div><figcaption>Each point is one pull, filled by how close it got: gold = kill (at 0%), green = under 10% left, amber = 10-40%, red = 40% or more. ${best ? `The gold dashed line is the best wipe so far, pull ${best.i} at ${best.p.toFixed(1)}%. ` : ''}Dashed vertical lines are breaks. Night is carried by line colour and dash pattern. Click a point (or Tab to it and press Enter) to inspect that pull, ctrl/shift to add it.</figcaption></figure>`;
  }
  function drawProgression(host, S, breaks, onPick) {
    const W = progWidth(host.clientWidth), H = 320, n = S.length; if (!n) { host.innerHTML = ''; return; }
    const sc = progScale(n, W, H), nights = [...new Set(S.map(p => p.n))], best = bestWipe(S);
    const svg = svgEl('svg', { 'class': 'plot', viewBox: `0 0 ${W} ${H}`, role: 'group',
      'aria-label': `Boss HP remaining at the end of each of ${n} pulls across ${nights.length} raid night${nights.length === 1 ? '' : 's'}. Lower is better.${best ? ` Best wipe ${best.p.toFixed(1)} per cent, pull ${best.i}.` : ' Includes a kill.'}` });
    [0, 20, 40, 60, 80, 100].forEach(v => { svg.appendChild(svgEl('line', { 'class': 'grid', x1: sc.x0, x2: sc.x1, y1: sc.sy(v), y2: sc.sy(v) }));
      const t = svgEl('text', { 'class': 'axis-text', x: sc.x0 - 8, y: sc.sy(v) + 4, 'text-anchor': 'end' }); t.textContent = v + '%'; svg.appendChild(t); });
    const step = n > 40 ? 6 : n > 20 ? 3 : n > 10 ? 2 : 1;
    S.forEach((p, j) => { if (j % step === 0 || j === n - 1) { const t = svgEl('text', { 'class': 'axis-text', x: sc.sx(j), y: sc.y1 + 18, 'text-anchor': 'middle' }); t.textContent = p.i; svg.appendChild(t); } });
    const xl = svgEl('text', { 'class': 'axis-title', x: (sc.x0 + sc.x1) / 2, y: H - 8, 'text-anchor': 'middle' }); xl.textContent = 'Pull number'; svg.appendChild(xl);
    // breaks: dashed vertical line between the two pulls (break.after is the pull number before the break)
    (breaks || []).forEach(br => { const j = S.findIndex(p => p.i === br.after); if (j < 0 || j >= n - 1) return; const x = (sc.sx(j) + sc.sx(j + 1)) / 2;
      svg.appendChild(svgEl('line', { 'class': 'break-line', x1: x, x2: x, y1: sc.y0, y2: sc.y1 }));
      const t = svgEl('text', { 'class': 'break-text', x: x + 4, y: sc.y0 + 10 }); t.textContent = `break ${Math.round(br.gap)}m`; svg.appendChild(t); });
    if (best) { svg.appendChild(svgEl('line', { 'class': 'best-line', x1: sc.x0, x2: sc.x1, y1: sc.sy(best.p), y2: sc.sy(best.p) }));
      const bt = svgEl('text', { 'class': 'best-text', x: sc.x0 + 8, y: sc.sy(best.p) - 8, 'text-anchor': 'start' }); bt.textContent = `Best ${best.p.toFixed(1)}% (pull ${best.i})`; svg.appendChild(bt); }
    const cross = svgEl('line', { 'class': 'crosshair', x1: 0, x2: 0, y1: sc.y0, y2: sc.y1, opacity: 0 });
    const hit = svgEl('rect', { 'class': 'hit', x: sc.x0, y: sc.y0, width: sc.x1 - sc.x0, height: sc.y1 - sc.y0 });
    const pointEls = [];
    nights.forEach((night, si) => { const st = seriesStyle(si), pts = []; S.forEach((p, j) => { if (p.n === night) pts.push([j, p]); });
      const line = { 'class': 'series', points: pts.map(([j, p]) => `${sc.sx(j)},${sc.sy(p.p)}`).join(' '), stroke: st.color };
      if (st.dash) line['stroke-dasharray'] = st.dash;
      svg.appendChild(svgEl('polyline', line));
      pts.forEach(([j, p]) => { const band = hpBand(p.p, p.k);
        const g = svgEl('g', { 'class': 'pt', role: 'button', tabindex: '0', 'aria-label': pointLabel(p) });
        g.appendChild(svgEl('circle', { 'class': `marker ${band}`, cx: sc.sx(j), cy: sc.sy(p.p), r: p.k ? 6.5 : 4.5, fill: BAND_COLOR[band], stroke: st.color, 'stroke-width': 2 }));
        pointEls.push([g, j]); }); });
    svg.appendChild(cross); svg.appendChild(hit);
    // points go above the hit rect so keyboard focus rings are visible; they pass the mouse through to the rect
    pointEls.forEach(([g]) => svg.appendChild(g));
    host.innerHTML = ''; host.appendChild(svg);
    const tip = document.createElement('div'); tip.className = 'tip'; tip.setAttribute('aria-hidden', 'true'); host.appendChild(tip);
    const nearest = evt => { const box = svg.getBoundingClientRect(); const px = (evt.clientX - box.left) / box.width * W; let bj = 0, bd = Infinity; S.forEach((p, j) => { const d = Math.abs(sc.sx(j) - px); if (d < bd) { bd = d; bj = j; } }); return bj; };
    const showTip = j => { const p = S[j];
      cross.setAttribute('x1', sc.sx(j)); cross.setAttribute('x2', sc.sx(j)); cross.setAttribute('opacity', 1);
      tip.innerHTML = `<div class='tip-pull'>Pull ${p.i} &middot; ${p.k ? 'KILL' : p.p.toFixed(1) + '% left'}</div><dl><dt>Night</dt><dd>${escH(p.n)}</dd><dt>Started</dt><dd>${escH(p.t)}</dd><dt>Duration</dt><dd>${fmtD(p.d)}</dd><dt>Deaths</dt><dd>${p.deaths.length}</dd>${p.ph ? `<dt>Ended in</dt><dd>${escH(p.ph)}</dd>` : ''}${!p.k && p.fp != null && Math.abs(p.fp - p.p) > 1 ? `<dt>Fight %</dt><dd>${p.fp.toFixed(1)}%</dd>` : ''}</dl>`;
      tip.dataset.show = '1'; const hb = host.getBoundingClientRect(); let left = sc.sx(j) / W * hb.width + 14; if (left + 230 > hb.width) left -= 244;
      tip.style.left = Math.max(0, left) + 'px'; tip.style.top = (sc.sy(p.p) / H * hb.height) + 'px'; };
    const hideTip = () => { tip.dataset.show = '0'; cross.setAttribute('opacity', 0); };
    const additive = evt => !!(evt.ctrlKey || evt.metaKey || evt.shiftKey);
    hit.addEventListener('mousemove', evt => showTip(nearest(evt)));
    hit.addEventListener('mouseleave', hideTip);
    hit.addEventListener('click', evt => { const p = S[nearest(evt)]; if (p) onPick(p.i, additive(evt)); });
    pointEls.forEach(([g, j]) => {
      g.addEventListener('focus', () => showTip(j));
      g.addEventListener('blur', hideTip);
      g.addEventListener('keydown', evt => { if (evt.key === 'Enter' || evt.key === ' ') { evt.preventDefault(); onPick(S[j].i, additive(evt)); } });
    });
  }
  function pullsTableHtml(S, tab) {
    return `<details class='table-view'><summary>Show the ${S.length} pull${S.length === 1 ? '' : 's'} as a table</summary>` + tbl([['Pull', 'num'], ['Night', 'str'], ['Started', 'str'], ['Result', 'num'], ['Duration', 'num'], ['Deaths', 'num'], ['Ended in', 'none']],
      S.map(p => `<tr><td class='right'>${p.i}</td><td>${escH(p.n)}</td><td>${escH(p.t)}</td><td class='right' data-sort='${p.k ? 0 : p.p}'>${resLabel(p)}</td><td class='right' data-sort='${p.d}'>${fmtD(p.d)}</td><td class='right'>${p.deaths.length}</td><td><span class='spec'>${escH(p.ph || '-')}</span></td></tr>`), '', `Every selected pull, the table behind the chart`) + `</details>`;
  }
  let chartSeq = 0;
  const charts = [];
  // chart(traces, layout, height, title?, fallback?): a <figure> card with the title as <h3>; with a fallback
  // sentence, a chart with nothing to compare (shouldSkipChart) becomes that sentence instead
  function chart(traces, layout, height, title, fallback) {
    if (fallback && shouldSkipChart(traces)) return `<p class='section-note'>${escH(fallback)}</p>`;
    const id = 'dyn_chart_' + (++chartSeq);
    const h = height || 380;
    const own = Object.assign({}, layout || {});
    const heading = title || chartTitle(own);
    delete own.title;
    charts.push([id, traces, chartLayout(LAYOUT, own, h)]);
    // reserved height: no layout shift while Plotly draws
    return `<figure class='chart'>${heading ? `<div class='chart-head'><h3>${escH(heading)}</h3></div>` : ''}<div class='plot' id='${id}' role='img' aria-label='${escH(heading)}' style='--h:${h}px'></div></figure>`;
  }
  function drawCharts() {
    while (charts.length) {
      const [id, tr, lay] = charts.shift(); const el = document.getElementById(id); if (!el || !window.Plotly) continue;
      // narrow screens: legend below the plot, with room for it
      if (window.matchMedia && window.matchMedia('(max-width:700px)').matches) { Object.assign(lay, narrowLegend(lay)); el.dataset.narrow = '1'; }
      try { Plotly.newPlot(el, tr, lay, { displayModeBar: false, responsive: true, displaylogo: false }); }
      catch (err) { el.innerHTML = `<p class='muted'>chart failed: ${escH(err && err.message || err)}</p>`; dashShowError(`chart "${el.getAttribute('aria-label') || id}": ${err && (err.stack || err.message) || err}`); }
    }
  }
  // note: Plotly's cleanData chokes on keys that are present but undefined, so only add marker/title when set
  const barTrace = (pairs, colors) => { const t = { type: 'bar', x: pairs.map(p => p[0]), y: pairs.map(p => p[1]), text: pairs.map(p => typeof p[1] === 'number' && p[1] >= 1000 ? fmtN(p[1]) : p[1]), textposition: 'outside', cliponaxis: false }; if (colors) t.marker = { color: colors }; return t; };
  const headroom = (pairs, title) => { const a = { range: [0, Math.max(...pairs.map(p => p[1]), 0) * 1.18], gridcolor: GRID }; if (title) a.title = title; return a; };
  const heatTrace = (z, x, y, unit) => ({ type: 'heatmap', z, x, y, colorscale: 'YlOrRd', texttemplate: '%{z}', textfont: { size: 10 }, colorbar: { title: unit }, hovertemplate: `%{y}<br>%{x}<br>%{z} ${unit}<extra></extra>` });

  // ---------------- payload loading ----------------
  const TAB_NAMES = JSON.parse(document.getElementById('tab_names').textContent);
  const bossTabs = Object.keys(TAB_NAMES);
  const PD = {};   // tab -> {data, sel:Set, player, dirty, rendered, phase}
  let playersDirty = false;   // Players tab needs a re-render (declared before the tab wiring that reads it)

  async function inflate(el) {
    if (el.type === 'application/json') return JSON.parse(el.textContent);
    const bin = atob(el.textContent.trim());
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const stream = new Blob([u8]).stream().pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(stream).text());
  }
  // static DOM wiring first: Python-rendered tables sort / right-align and the grid toggle works while payloads inflate
  wireSort(document); wireToggles(document);
  const mpOnly = document.getElementById('mpOnlyMissing');
  if (mpOnly) mpOnly.addEventListener('change', e => $$('table.mplus tbody tr').forEach(tr => { tr.style.display = (e.target.checked && tr.dataset.status === 'met') ? 'none' : ''; }));
  // compact pull grid (remembered)
  const compact = store.get('wcl_dash_compact') === '1';
  $$('input.compactGrid').forEach(cb => { cb.checked = compact; cb.addEventListener('change', () => { $$('.pull-grid').forEach(g => g.classList.toggle('compact', cb.checked)); $$('input.compactGrid').forEach(o => { o.checked = cb.checked; }); store.set('wcl_dash_compact', cb.checked ? '1' : '0'); }); });
  if (compact) $$('.pull-grid').forEach(g => g.classList.add('compact'));
  // ---------------- tabs (ARIA tablist + arrow keys + difficulty segment + mobile select) ----------------
  // wired before the payloads inflate: Home / Raid / Players / Mythic+ stay reachable even if every payload fails
  const tabButtons = $$('.tab-btn');
  const tabSelect = document.getElementById('tabSelect');
  function activateTab(id, focus) {
    tabButtons.forEach(b => { const on = b.dataset.tab === id; b.classList.toggle('active', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); });
    $$('.tab-panel').forEach(p => { const on = p.id === id; p.classList.toggle('active', on); p.hidden = !on; });
    if (tabSelect) tabSelect.value = id;
    // the desktop strip wraps; if it ever overflows (very long labels), keep the active tab in view
    const tabs = $('.tabs'), cur = tabButtons.find(b => b.dataset.tab === id);
    if (cur && tabs && tabs.scrollWidth > tabs.clientWidth) cur.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    renderIfDirty(id);
    window.dispatchEvent(new Event('resize'));  // hidden Plotly charts have zero width
  }
  tabButtons.forEach(btn => btn.addEventListener('click', () => activateTab(btn.dataset.tab, false)));
  $('.tabs').addEventListener('keydown', e => {
    const visible = tabButtons.filter(b => !b.classList.contains('diff-hidden'));
    const i = visible.indexOf(document.activeElement); if (i < 0) return;
    let j = null;
    if (e.key === 'ArrowRight') j = (i + 1) % visible.length; else if (e.key === 'ArrowLeft') j = (i - 1 + visible.length) % visible.length;
    else if (e.key === 'Home') j = 0; else if (e.key === 'End') j = visible.length - 1;
    if (j !== null) { e.preventDefault(); activateTab(visible[j].dataset.tab, true); }
  });
  const activeTab = () => $('.tab-panel.active')?.id;
  if (tabSelect) {
    // one <optgroup> per difficulty plus one for Home / Raid / Players / Mythic+; label "Name · Heroic · ✓"
    const groups = {};
    const group = label => groups[label] || (groups[label] = tabSelect.appendChild(Object.assign(document.createElement('optgroup'), { label })));
    group('Overview');
    tabButtons.forEach(b => {
      const text = el => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
      const name = b.dataset.name || text(b.firstChild);
      const parts = b.dataset.diff ? [name, b.dataset.diff, text(b.querySelector('.badge'))] : [name, text(b.querySelector('.sub'))];
      const o = document.createElement('option'); o.value = b.dataset.tab; o.textContent = parts.filter(Boolean).join(' · ');
      group(b.dataset.diff || 'Overview').appendChild(o);
    });
    tabSelect.addEventListener('change', () => activateTab(tabSelect.value, false));
  }
  // difficulty segment: show one difficulty's boss tabs at a time (default: all). Only clicks persist the choice.
  const diffBtns = $$('.diffbtn');
  function setDiff(d, persist = true) {
    diffBtns.forEach(b => b.setAttribute('aria-pressed', b.dataset.diff === d ? 'true' : 'false'));
    tabButtons.forEach(b => { if (b.dataset.diff) b.classList.toggle('diff-hidden', d !== 'all' && b.dataset.diff !== d); });
    if (persist) store.set('wcl_dash_diff', d);
    setNavH();   // hiding difficulties changes how many rows the strip wraps into
    const cur = $('.tab-btn.active');
    if (cur && cur.classList.contains('diff-hidden')) { const first = tabButtons.find(b => b.dataset.diff === d); if (first) activateTab(first.dataset.tab, false); }
  }
  if (diffBtns.length) {
    const present = diffBtns.map(b => b.dataset.diff).filter(d => d !== 'all');
    const saved = store.get('wcl_dash_diff');
    setDiff(saved && (saved === 'all' || present.includes(saved)) ? saved : 'all', false);
    diffBtns.forEach(b => b.addEventListener('click', () => setDiff(b.dataset.diff)));
  }

  // --tabnav-h (sticky section nav, scroll margins) = the measured nav, which wraps into several rows on a real build;
  // the CSS values are only the first-paint fallback
  function setNavH() { const nav = $('nav.tabnav'), main = $('main'); if (nav && main) main.style.setProperty('--tabnav-h', nav.offsetHeight + 'px'); }
  setNavH();
  if (window.ResizeObserver && $('nav.tabnav')) new ResizeObserver(setNavH).observe($('nav.tabnav'));
  else window.addEventListener('resize', setNavH);

  const needsDecompress = bossTabs.some(t => { const el = document.getElementById('data_' + t); return el && el.type !== 'application/json'; });
  if (needsDecompress && !window.DecompressionStream) { const b = document.getElementById('oldBrowser'); if (b) b.hidden = false; }
  else {
    // one undecodable payload empties that boss tab only (PD[tab] stays absent); the other tabs keep working
    await Promise.all(bossTabs.map(async tab => {
      const el = document.getElementById('data_' + tab); if (!el) return;
      try {
        const data = await inflate(el);
        data.avoidSet = new Set(data.avoidable); data.ignoreSet = new Set(data.ignored);
        data.nights = [...new Set(data.pulls.map(p => p.n))];
        PD[tab] = { data, sel: new Set(), player: '', dirty: true, rendered: false, phase: -1 };
      } catch (err) {
        const msg = err && err.message || String(err);
        const det = document.getElementById('detail_' + tab);
        if (det) { det.innerHTML = emptyHtml('data for this boss', `the payload could not be decoded: ${msg}`, ''); det.removeAttribute('aria-busy'); }
        const btn = $(`.tab-btn[data-tab='${tab}']`); if (btn) { btn.classList.add('empty'); btn.title = 'the data for this tab could not be decoded'; }
        dashShowError(`payload ${tab}: ${err && (err.stack || err.message) || err}`);
      }
    }));
  }
  const loadTab = tab => PD[tab] || null;

  // ---------------- sortable tables + toggles ----------------
  // data-limit='N': the first N rows that are not hidden by "Hide tanks" stay visible, the rest get lowpart
  function applyLimit(table) {
    const lim = parseInt(table.dataset.limit, 10), tbody = table.tBodies[0]; if (!(lim > 0) || !tbody) return;
    const hideT = table.classList.contains('hide-tanks'); let k = 0;
    Array.from(tbody.rows).forEach(tr => { if (hideT && tr.classList.contains('role-tank')) return; tr.classList.toggle('lowpart', k++ >= lim); });
  }
  function wireSort(root) {
    $$('table.sortable th button', root).forEach(btn => {
      const th = btn.closest('th');
      btn.addEventListener('click', () => {
        const table = th.closest('table'), tbody = table.tBodies[0];   // direct rows only: nested recap tables stay in their cells
        const type = th.dataset.type || 'str';
        const asc = th.getAttribute('aria-sort') !== 'ascending';
        table.querySelectorAll('th').forEach(h => h.removeAttribute('aria-sort'));
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        const idx = Array.from(th.parentNode.children).indexOf(th);
        const val = tr => {
          const td = tr.children[idx];
          if (!td) return type === 'num' ? Number.POSITIVE_INFINITY : '';
          const raw = td.dataset.sort !== undefined ? td.dataset.sort : td.textContent.trim();
          if (type === 'num') { const n = parseFloat(String(raw).replace('%', '').replace('KILL', '0').replace('+', '')); return isNaN(n) ? Number.POSITIVE_INFINITY : n; }
          return String(raw).toLowerCase();
        };
        Array.from(tbody.rows).sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); }).forEach(tr => tbody.appendChild(tr));
        // a limited table keeps showing its first N rows in the new order (.show-low still reveals all)
        applyLimit(table);
      });
    });
    // numeric columns: right-align the body cells under a th.right (callers only mark the header)
    $$('table.sortable', root).forEach(table => {
      const cols = $$('thead th', table).map((h, k) => h.classList.contains('right') ? k : -1).filter(k => k >= 0);
      if (cols.length) $$(':scope > tbody > tr', table).forEach(tr => cols.forEach(k => { const td = tr.children[k]; if (td) td.classList.add('right'); }));
    });
    // "Show all N" under a limited table
    $$('button.show-all', root).forEach(btn => {
      const total = btn.textContent;
      btn.addEventListener('click', () => {
        const table = btn.parentNode.querySelector('table');
        const open = btn.getAttribute('aria-expanded') !== 'true';
        if (table) table.classList.toggle('show-low', open);
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        btn.textContent = open ? 'Show fewer' : total;
      });
    });
  }
  function wireToggles(root) {
    // a label inside a .lowgroup toggles the whole group (all role tables); otherwise the next table after the label
    const nextTable = cb => { let el = cb.closest('label').nextElementSibling; while (el && !el.querySelector?.('table') && el.tagName !== 'TABLE') el = el.nextElementSibling; return el ? (el.tagName === 'TABLE' ? el : el.querySelector('table')) : null; };
    const target = cb => cb.closest('.lowgroup') || nextTable(cb);
    $$('input.showLow', root).forEach(cb => cb.addEventListener('change', () => { const t = target(cb); if (t) t.classList.toggle('show-low', cb.checked); }));
    $$('input.hideTanks', root).forEach(cb => cb.addEventListener('change', () => { const t = nextTable(cb); if (t) { t.classList.toggle('hide-tanks', cb.checked); applyLimit(t); } }));
  }

  // ---------------- shared analysis helpers ----------------
  function busyBetween(busy, night, s, e) { let t = 0; (busy[night] || []).forEach(([a, b]) => { const lo = Math.max(a, s), hi = Math.min(b, e); if (hi > lo) t += hi - lo; }); return t; }
  function detectBreaks(S, thr, busy) {
    const out = [];
    for (let j = 1; j < S.length; j++) {
      const prev = S[j - 1], nxt = S[j];
      if (prev.n !== nxt.n || prev.a === undefined) continue;
      const prevEnd = prev.a + prev.d * 1000;
      const gap = (nxt.a - prevEnd) / 60000, b = busyBetween(busy || {}, prev.n, prevEnd, nxt.a) / 60000, idle = gap - b;
      if (idle >= thr) { const night = S.filter(p => p.n === prev.n); const k = night.indexOf(prev);
        out.push({ after: prev.i, gap: idle, busy: b, night: prev.n, resume: nxt.t, before: night.slice(Math.max(0, k - 4), k + 1), afterPulls: night.slice(k + 1, k + 6) }); }
    }
    return out;
  }
  function rolesOf(S) {   // name -> dominant role over these pulls
    const c = {}; S.forEach(p => Object.entries(p.specs || {}).forEach(([n, sp]) => { const r = roleOf(sp); (c[n] || (c[n] = {}))[r] = ((c[n] || {})[r] || 0) + 1; }));
    const out = {}; Object.entries(c).forEach(([n, o]) => { out[n] = Object.entries(o).sort((x, y) => y[1] - x[1])[0][0]; }); return out;
  }
  function roleLabel(S, name) {
    const c = {}; S.forEach(p => { const sp = (p.specs || {})[name]; if (sp) { const r = roleOf(sp); c[r] = (c[r] || 0) + 1; } });
    const e = Object.entries(c).sort((x, y) => y[1] - x[1]); return e.length <= 1 ? (e[0] ? e[0][0] : '') : e.map(([r, n]) => `${r} ${n}`).join(' / ');
  }
  const phaseOrder = S => { const order = []; S.forEach(p => (p.pt || []).forEach(([name]) => { if (!order.includes(name)) order.push(name); })); return order; };
  const phaseAt = (p, s) => { let cur = null; (p.pt || []).forEach(([name, t]) => { if (t <= s) cur = name; }); return cur; };
  const defCell = d => {
    if (!d.hc) return "<span class='muted'>-</span>";
    const own = d.def && d.def.length ? d.def.map(x => escH(x[1])).join(', ') : '';
    const ext = d.ext && d.ext.length ? d.ext.map(x => `${escH(x[1])} <span class='muted'>from ${escH(x[2])}</span>`).join(', ') : '';
    if (!own && !ext) return "<span class='tag warn'>none</span>";
    return (own ? `<span class='tag good'>own</span> ${own}` : '') + (own && ext ? '<br>' : '') + (ext ? `<span class='tag'>received</span> ${ext}` : '');
  };
  const hadDef = d => !!(d.hc && ((d.def && d.def.length) || (d.ext && d.ext.length)));
  function recapHtml(d) {
    if (!d.recap.length && !(d.cs && d.cs.length)) return "<span class='muted'>-</span>";
    const max = Math.max(...d.recap.map(r => r[3]), 0);
    const rows = d.recap.map(r => `<tr${r[3] === max ? " class='big'" : ''}><td>-${r[0]}s</td><td>${escH(r[1])}${r[4] ? " <span class='tag'>self</span>" : ''}</td><td>${escH(r[2])}</td><td>${fmtN(r[3])}</td></tr>`).join('');
    const casts = d.cs && d.cs.length ? `<div class='casts'>Cast in that window: ${d.cs.map(c => `${escH(c[1])} <span class='muted'>(-${c[0]}s)</span>`).join(', ')}</div>` : (d.hc ? `<div class='casts'>No casts in that window.</div>` : '');
    const ext = d.ext && d.ext.length ? `<div class='casts'>Received: ${d.ext.map(x => `${escH(x[1])} from ${escH(x[2])} <span class='muted'>(-${x[0]}s)</span>`).join(', ')}</div>` : '';
    return `<details><summary>${d.recap.length} hits, ${fmtN(d.w)}</summary><table class='recap'><thead><tr><th>Before</th><th>Ability</th><th>Source</th><th>Amount</th></tr></thead><tbody>${rows}</tbody></table>${casts}${ext}</details>`;
  }

  // ---------------- boss tab sections ----------------
  function secPhaseStrip(S, n) {
    // prog boss: how deep do we get, at a glance
    const later = phaseOrder(S).slice(1); if (!later.length || S.some(p => p.k)) return '';
    return kpisHtml(later.map(name => { const times = S.map(p => (p.pt || []).find(x => x[0] === name)).filter(Boolean).map(x => x[1]);
      return [`${name}`, times.length ? `${times.length}/${n} pulls <span class='vs'>${pct(times.length, n)}% &middot; fastest ${fmtD(Math.min(...times))} &middot; median ${fmtD(median(times))}</span>` : `0/${n} pulls <span class='vs'>never reached</span>`]; }), 'kpi-strip');
  }
  function secProgress(D, S, n, tab) {
    let html = '';
    const wipes = S.filter(p => !p.k), selNights = [...new Set(S.map(p => p.n))];
    const breaks = detectBreaks(S, D.break_minutes || 4.5, D.busy);
    html += `<h2 id='sec_${tab}_prog'>Progression</h2>`;
    html += progressionChartHtml(tab, S);
    html += pullsTableHtml(S, tab);
    if (breaks.length) {
      const avg = ps => ps.length ? ps.reduce((a, p) => a + p.p, 0) / ps.length : 0, best = ps => ps.length ? Math.min(...ps.map(p => p.p)) : 0;
      html += `<h3>Breaks</h3><p class='section-note'>${breaks.length} break${breaks.length === 1 ? '' : 's'} in the selected pulls. Before/after compare the 5 pulls either side; lower % is better, so a negative change means the raid came back sharper.</p><details class='table-view'><summary>Show as table</summary>` + tbl([['Night', 'str'], ['Resumed', 'str'], ['Length', 'num'], ['Before break', 'num'], ['After break', 'num'], ['Change (avg %)', 'str'], ['First pull back', 'str']],
        breaks.map(br => { const d = br.before.length && br.afterPulls.length ? avg(br.afterPulls) - avg(br.before) : null; const f = br.afterPulls[0];
          return `<tr><td>${escH(br.night)}</td><td>${escH(br.resume)}</td><td data-sort='${br.gap}'>${Math.round(br.gap)} min${br.busy >= 1 ? ` <span class='muted'>(+${Math.round(br.busy)} min fighting in between)</span>` : ''}</td><td data-sort='${avg(br.before)}'>${br.before.length} pulls, avg ${avg(br.before).toFixed(1)}%, best ${best(br.before).toFixed(1)}%</td><td data-sort='${avg(br.afterPulls)}'>${br.afterPulls.length} pulls, avg ${avg(br.afterPulls).toFixed(1)}%, best ${best(br.afterPulls).toFixed(1)}%</td><td>${d === null ? '-' : `<span class='delta ${d < 0 ? 'better' : 'worse'}'>${d >= 0 ? '+' : ''}${d.toFixed(1)} pts ${d < 0 ? '(better)' : '(worse)'}</span>`}</td><td>${f ? resLabel(f) : '-'}</td></tr>`; }), '', 'Breaks in the selected pulls, with the pulls either side') + `</details>`;
    }
    // wipes by phase + time to reach each phase
    const ph = {}; wipes.forEach(p => { if (p.ph) ph[p.ph] = (ph[p.ph] || 0) + 1; });
    const order = phaseOrder(S);
    const later = order.slice(1);
    if (Object.keys(ph).length || later.length) html += `<h3>Phases</h3>`;
    const grid = [];
    const phWiped = order.filter(x => ph[x]);
    if (phWiped.length) grid.push(chart([barTrace(phWiped.map(x => [x, ph[x]]))], { title: 'Wipes by phase (phase the pull ended in)', yaxis: headroom(Object.entries(ph), 'Wipes') }, 320,
      '', `Every wipe was in ${phWiped[0]}.`));
    if (later.length) {
      const traces = later.map((name, i) => { const pts = S.map(p => { const e = (p.pt || []).find(x => x[0] === name); return e ? [p.i, e[1], p] : null; }).filter(Boolean);
        return { type: 'scatter', mode: 'lines+markers', name, line: lineStyle(i), marker: { symbol: symbolOf(i), size: 8 }, x: pts.map(x => x[0]), y: pts.map(x => x[1]), hovertext: pts.map(x => `Pull #${x[0]} (${escH(x[2].n)} ${x[2].t})<br>${escH(name)} at ${fmtD(x[1])}`), hoverinfo: 'text' }; });
      grid.push(chart(traces, { title: 'How fast do we reach each phase? (seconds into the pull)', xaxis: { title: 'Pull #', gridcolor: GRID }, yaxis: { title: 'Seconds', gridcolor: GRID }, legend: { orientation: 'h', yanchor: 'bottom', y: 1.06, x: 0 }, margin: { l: 45, r: 20, t: 50, b: 45 } }, 320,
        '', 'Fewer than four pulls reached a later phase; the table below has the times.'));
    }
    if (grid.length) html += `<div class='grid2'>${grid.map(g => `<div>${g}</div>`).join('')}</div>`;
    if (later.length) {
      html += `<details class='table-view'><summary>Show as table</summary>` + tbl([['Phase', 'str'], ['Reached in', 'num'], ['Median time', 'num'], ['Fastest', 'num'], ['Slowest', 'num'], ['Last pull that got there', 'str']],
        later.map(name => { const times = S.map(p => (p.pt || []).find(x => x[0] === name)).filter(Boolean).map(x => x[1]); const lastP = [...S].reverse().find(p => (p.pt || []).some(x => x[0] === name));
          return `<tr><td>${escH(name)}</td><td data-sort='${times.length / n}'>${times.length} of ${n} pulls (${pct(times.length, n)}%)</td><td data-sort='${median(times)}'>${times.length ? fmtD(median(times)) : '-'}</td><td data-sort='${Math.min(...times)}'>${times.length ? fmtD(Math.min(...times)) : '-'}</td><td data-sort='${Math.max(...times)}'>${times.length ? fmtD(Math.max(...times)) : '-'}</td><td>${lastP ? `#${lastP.i} (${escH(lastP.n.slice(4))} ${lastP.t})` : '-'}</td></tr>`; }), '', `Time to reach each later phase, ${n} pull${n === 1 ? '' : 's'}`) + `</details>`
        + `<p class='section-note'>Reaching a phase earlier, more often, is progress even when the end % does not move.</p>`;
    }
    if (selNights.length > 1) {
      html += `<h3>Per raid night</h3><details class='table-view'><summary>Show as table</summary>` + tbl([['Night', 'str'], ['Pulls', 'num'], ['Kills', 'num'], ['Best', 'num'], ['Avg duration', 'num'], ['Avg deaths / pull', 'num'], ['Median time to first death', 'num']],
        selNights.map(night => { const ps = S.filter(p => p.n === night); const kills = ps.filter(p => p.k).length; const bestV = kills ? 0 : Math.min(...ps.map(p => p.p)); const dur = ps.reduce((a, p) => a + p.d, 0) / ps.length; const fd = ps.filter(p => p.deaths.length).map(p => p.deaths[0].s);
          return `<tr><td>${escH(night)}</td><td>${ps.length}</td><td>${kills}</td><td data-sort='${bestV}'>${kills ? 'KILL' : bestV.toFixed(1) + '%'}</td><td data-sort='${dur}'>${fmtD(dur)}</td><td>${(ps.reduce((a, p) => a + p.deaths.length, 0) / ps.length).toFixed(1)}</td><td data-sort='${median(fd)}'>${fd.length ? fmtD(median(fd)) : '-'}</td></tr>`; }), '', `${selNights.length} raid nights in the selection`) + `</details>`;
    }
    return html;
  }

  function aggOutput(S, key, metric) {
    const specs = {}; S.forEach(p => (p[key] || []).forEach(([name, , spec]) => (specs[name] || (specs[name] = new Set())).add(spec)));
    const o = {};
    S.forEach(p => (p[key] || []).forEach(([name, c, spec, total, act]) => {
      const rk = specs[name].size > 1 && spec ? `${name} (${spec})` : name;
      const e = o[rk] || (o[rk] = { cl: c, spec, player: name, total: 0, secs: 0, act: 0, pulls: 0, per: [], parses: [], byNight: {} });
      e.total += total; e.secs += p.d; e.act += act; e.pulls++; e.per.push(p.d ? total / p.d : 0);
      (e.byNight[p.n] || (e.byNight[p.n] = [])).push(p.d ? total / p.d : 0);
      const pr = ((p.parses || {})[name] || {})[metric]; if (pr !== undefined && pr !== null) e.parses.push(pr);
    }));
    return o;
  }
  function secSummary(D, S, n, secs, IG, tab) {
    const list = (key, rate) => { const all = Object.entries(aggOutput(S, key, rate === 'DPS' ? 'dps' : 'hps')).sort((a, b) => b[1].total - a[1].total).slice(0, 10); if (!all.length) return emptyHtml(rate === 'DPS' ? 'damage done' : 'healing done', 'WCL returned no entries for these pulls', ''); const top = all[0][1].total || 1;
      return `<div class='scroller'><table class='summary'><tbody>${all.map(([name, e]) => `<tr><td class='${cls(e.cl)}'>${escH(name)}</td><td>${bar(e.total / top * 100, rate === 'HPS')}</td><td>${fmtN(e.total)}</td><td class='muted'>${fmtN(e.secs ? e.total / e.secs : 0)} ${rate}</td></tr>`).join('')}</tbody></table></div>`; };
    const byAb = {}; S.forEach(p => p.dt.forEach(([, a, , amt]) => { if (!IG.has(norm(a))) byAb[a] = (byAb[a] || 0) + amt; }));
    const items = topN(byAb, 10), top = items.length ? items[0][1] : 1;
    const taken = items.length ? `<div class='scroller'><table class='summary'><tbody>${items.map(([a, v]) => `<tr><td>${escH(a)}</td><td>${bar(v / top * 100)}</td><td>${fmtN(v)}</td><td class='muted'>${fmtN(v / (secs || 1))} DTPS</td></tr>`).join('')}</tbody></table></div>` : emptyHtml('damage taken', 'WCL returned no entries for these pulls', '');
    return `<h2 id='sec_${tab}_sum'>Summary</h2><div class='grid3'><div><h3>Damage done by source</h3>${list('dd', 'DPS')}</div><div><h3>Healing done by source</h3>${list('hd', 'HPS')}</div><div><h3>Damage taken by ability</h3>${taken}</div></div>
      <p class='section-note'>Totals across the selected pulls. DPS/HPS = total &divide; time in the pulls that player was in. Parse % (below) is only available for kills - WCL doesn't rank wipes.</p>`;
  }
  function secOutput(S, key, rate, metric, kind, tab) {
    const all = Object.entries(aggOutput(S, key, metric));
    let out = `<h2 id='sec_${tab}_${key}'>${kind === 'damage' ? 'Damage done' : 'Healing done'}</h2>`;
    if (!all.length) return out + emptyHtml(kind === 'damage' ? 'damage done' : 'healing done', 'the WCL tables did not return entries for these pulls', '');
    const grand = all.reduce((a, [, e]) => a + e.total, 0) || 1, maxP = Math.max(...all.map(([, e]) => e.pulls), 1);   // maxP: box-plot eligibility
    const groups = { dps: [], tank: [], healer: [] }; all.forEach(([name, e]) => groups[roleOf(e.spec)].push([name, e]));
    const order = kind === 'damage' ? [['dps', 'DPS'], ['tank', 'Tanks'], ['healer', 'Healers']] : [['healer', 'Healers'], ['dps', 'DPS'], ['tank', 'Tanks']];
    const ONE = { dps: 'DPS', tank: 'Tank', healer: 'Healer' };   // caption for a single row: "1 Healer"
    out += `<p class='section-note'>${rate} = total &divide; time in the pulls the player was in. <b>Active ${rate}</b> divides by the time WCL counts them as active, which stops at death - a big gap between the two means they die early, not that they play badly. <b>Median pull</b> ignores the one dead pull and the one lucky pull; <b>Best pull</b> is the ceiling. Parse (kills only) is the only number that is fair across specs.</p>`;
    order.forEach(([role, label]) => { const rows = groups[role]; if (!rows.length) return;
      const maxRate = Math.max(...rows.map(([, e]) => e.secs ? e.total / e.secs : 0), 1);
      out += `<h3>${label}</h3>` + tbl([['Parse', 'num'], ['Name', 'str'], ['Amount', 'num'], [rate, 'num'], [`Active ${rate}`, 'num'], ['Median pull', 'num'], ['Best pull', 'num'], ['Active', 'num'], ['Pulls', 'num']],
        rows.sort((x, y) => (y[1].secs ? y[1].total / y[1].secs : 0) - (x[1].secs ? x[1].total / x[1].secs : 0)).map(([name, e]) => { const r = e.secs ? e.total / e.secs : 0, ar = e.act ? e.total / e.act : 0;
          const pc = e.parses.length ? (() => { const v = e.parses.reduce((a, b) => a + b, 0) / e.parses.length; return `<td data-sort='${v}' class='${parseCls(v)}'>${Math.round(v)}</td>`; })() : `<td data-sort='-1' class='muted'>-</td>`;
          return `<tr data-player='${escH(e.player)}'>${pc}<td>${playerCell(name, e.cl, roleOf(e.spec), e.spec)}</td><td data-sort='${e.total}'>${bar(r / maxRate * 100, kind === 'healing')}${(e.total / grand * 100).toFixed(1)}% <span class='spec'>${fmtN(e.total)}</span></td><td data-sort='${r}'><b>${fmtN(r)}</b></td><td data-sort='${ar}'>${fmtN(ar)}</td><td data-sort='${median(e.per)}'>${fmtN(median(e.per))}</td><td data-sort='${Math.max(...e.per)}'>${fmtN(Math.max(...e.per))}</td><td data-sort='${e.secs ? e.act / e.secs : 0}'>${(e.secs ? e.act / e.secs * 100 : 0).toFixed(1)}%</td><td>${e.pulls}</td></tr>`; }), 'output', `${rows.length} ${rows.length === 1 ? ONE[role] : label}${rows.length > 10 ? ' · top 10 shown' : ''}`, 10); });
    if (kind === 'damage') {
      const elig = topByMedian(groups.dps.filter(([, e]) => e.pulls >= Math.max(2, 0.25 * maxP) && e.per.length >= 2), Infinity);
      if (elig.length >= 2) {
        // horizontal, highest median on top (Plotly draws the first y category at the bottom, hence the reversed axis)
        const shown = elig.slice(0, 15), BL = boxLayout(shown.length);
        out += chart(shown.map(([name, e]) => ({ type: 'box', x: e.per, name, orientation: BL.orientation, boxpoints: 'outliers', marker: { size: 4 }, line: { width: 1.2 } })),
          { title: `${rate} per pull - how consistent is each DPS? (box = middle half of their pulls, line = median${elig.length > 15 ? '; top 15 by median' : ''})`, xaxis: { title: `${rate} in a pull`, gridcolor: GRID }, showlegend: false, yaxis: { autorange: 'reversed', automargin: true, gridcolor: GRID }, margin: { l: 120, r: 20, t: 20, b: 45 } }, BL.height,
          '', 'Fewer than four pulls per DPS player in the selection, too few for a spread; median and best pull are in the tables above.');
        if (elig.length > 15) out += `<p class='section-note'>15 of ${elig.length} players shown (highest median); the table above has everyone.</p>`;
      }
      // trend across nights: is the raid getting better or just luckier?
      const nights = [...new Set(S.map(p => p.n))];
      if (nights.length > 1 && elig.length) {
        const traces = topByMedian(elig, 6).map(([name, e], i) => ({ type: 'scatter', mode: 'lines+markers', name, line: lineStyle(i), marker: { symbol: symbolOf(i), size: 8 },
          x: nights.map(nn => nn.slice(4)), y: nights.map(nn => e.byNight[nn] ? median(e.byNight[nn]) : null), connectgaps: true,
          hovertext: nights.map(nn => `${name}<br>${nn}<br>${e.byNight[nn] ? fmtN(median(e.byNight[nn])) + ' median ' + rate + ' over ' + e.byNight[nn].length + ' pulls' : 'absent'}`), hoverinfo: 'text' }));
        out += chart(traces, { title: `Median ${rate} per night - top ${traces.length} DPS by overall median (click legend entries to hide/show)`, yaxis: { title: rate, gridcolor: GRID }, xaxis: { title: 'Raid night', gridcolor: GRID }, legend: { orientation: 'h', y: -0.2, yanchor: 'top' }, margin: { l: 45, r: 20, t: 20, b: 110 } }, 420,
          '', 'Fewer than four raid nights in the selection; the tables above have the per-pull numbers.');
      }
    }
    return out;
  }
  function secDeaths(D, S, n, A, hasA, tab) {
    const roles = rolesOf(S);
    let html = `<h2 id='sec_${tab}_deaths'>Deaths</h2>`;
    if (n === 1) {
      const ds = S[0].deaths;
      html += `<h3>Deaths (${ds.length}) - how the pull unfolded</h3>`;
      if (!ds.length) return html + emptyHtml('deaths', 'nobody died in this pull', '');
      return html + `<p class='section-note'>Defensives (own casts and externals received) are only looked up for the first death of each pull.</p>` + tbl([['#', 'num'], ['Time', 'num'], ['Phase', 'str'], ['Player', 'str'], ['What killed them', 'str'], ['Killing blow', 'str'], ['Dmg last seconds', 'num'], ['Tags', 'str'], ['Defensives', 'str'], ['Last seconds', 'str']],
        ds.map((d, i) => `<tr><td>${i + 1}</td><td data-sort='${d.s}'>${fmtD(d.s)}</td><td class='muted'>${escH(phaseAt(S[0], d.s) || '-')}</td><td class='${cls(d.cl)}'>${escH(d.pl)}</td><td>${escH(d.tc)}</td><td class='muted'>${escH(d.kb)}</td><td data-sort='${d.w}'>${fmtN(d.w)}</td><td>${d.os ? "<span class='tag'>one-shot</span>" : ''}${hasA && d.recap.some(r => A.has(norm(r[1]))) ? " <span class='tag'>avoidable</span>" : ''}</td><td>${defCell(d)}</td><td>${recapHtml(d)}</td></tr>`), 'deathlog', 'Deaths in this pull');
    }
    const withD = S.filter(p => p.deaths.length);
    const firsts = withD.map(p => p.deaths[0]);
    if (!firsts.length) return html + emptyHtml('deaths', 'nobody died in the selected pulls', '');
    const byC = {}, byP = {};
    firsts.forEach(d => { byC[d.tc] = (byC[d.tc] || 0) + 1; byP[d.pl] = (byP[d.pl] || 0) + 1; });
    const times = firsts.map(d => d.s).sort((a, b) => a - b);
    const oneShots = firsts.filter(d => d.os).length;
    const avoidFirst = hasA ? firsts.filter(d => d.recap.some(r => A.has(norm(r[1])))).length : null;
    const withCasts = firsts.filter(d => d.hc), noDef = withCasts.filter(d => !hadDef(d)).length;
    // wipe anatomy: how fast the first death turns into a cascade
    const gaps = withD.filter(p => p.deaths.length >= 2).map(p => p.deaths[1].s - p.deaths[0].s);
    const within10 = withD.map(p => p.deaths.filter(d => d.s > p.deaths[0].s && d.s <= p.deaths[0].s + 10).length);
    const cascades = within10.filter(x => x >= 2).length;
    const dc = [['Pulls with a death', `${firsts.length} / ${n}`], ['Most common wipe-starter', escH(topN(byC, 1)[0][0])],
      ['Median time to first death', fmtD(median(times))], ['First death under 30s', `${times.filter(t => t < 30).length} pulls`],
      ['First death was a one-shot', `${pct(oneShots, firsts.length)}%`]];
    if (avoidFirst !== null) dc.push(['First death involved avoidable dmg', `${pct(avoidFirst, firsts.length)}%`]);
    if (withCasts.length) dc.push(['First death with no defensive', `${pct(noDef, withCasts.length)}% <span class='vs'>own cast or external received</span>`]);
    if (gaps.length) dc.push(['First to second death', `${median(gaps).toFixed(0)} s median <span class='vs'>${cascades} of ${withD.length} pulls lost 2+ more within 10 s (cascade)</span>`]);
    html += `<p class='section-note'>Only the first death of each pull counts here - everyone dies once the wipe is called. "What killed them" is the ability that did the most damage in the final seconds; the killing blow is often just melee.</p>`;
    html += kpisHtml(dc);
    // fallback sentences (the chart is skipped when there is nothing to compare, see shouldSkipChart)
    const fds = `${firsts.length} first death${firsts.length === 1 ? '' : 's'}`;
    const firstsNote = `Only ${fds} in the selection; the table below lists them.`;
    const oneC = topN(byC, 1)[0][0], oneP = topN(byP, 1)[0][0];
    const byCFallback = firsts.length === 1 ? `The only first death came from ${oneC}.` : `All ${fds} came from ${oneC}; the table below lists them.`;
    const byPFallback = firsts.length === 1 ? `The only first death was ${oneP}.` : `All ${fds} were ${oneP}; the table below lists them.`;
    html += `<div class='grid2'><div>${chart([barTrace(topN(byC, 12))], { title: 'First death - what did the damage', yaxis: headroom(topN(byC, 12), 'First deaths') }, 0, '', byCFallback)}</div><div>${chart([barTrace(topN(byP, 12))], { title: 'First death - who', yaxis: headroom(topN(byP, 12), 'First deaths') }, 0, '', byPFallback)}</div></div>`;
    // by phase: first deaths per phase, and per pull that reached the phase
    const order = phaseOrder(S);
    if (order.length > 1) {
      const reached = {}, died = {};
      S.forEach(p => (p.pt || []).forEach(([name]) => { reached[name] = (reached[name] || 0) + 1; }));
      withD.forEach(p => { const ph = phaseAt(p, p.deaths[0].s); if (ph) died[ph] = (died[ph] || 0) + 1; });
      const pairs = order.map(name => [name, died[name] || 0]);
      const rate = order.map(name => reached[name] ? `${pct(died[name] || 0, reached[name])}% of ${reached[name]} pulls that got there` : '');
      const nz = pairs.filter(q => q[1]);
      const phaseFallback = !nz.length ? 'None of the first deaths could be placed in a phase.'
        : `All ${nz[0][1]} first death${nz[0][1] === 1 ? '' : 's'} with a known phase happened in ${nz[0][0]}.`;
      html += `<div class='grid2'><div>${chart([Object.assign(barTrace(pairs), { text: pairs.map((p, i) => `${p[1]}${rate[i] ? ' (' + rate[i].split(' of ')[0] + ')' : ''}`) })], { title: 'First death - in which phase (count and % of pulls that reached it)', yaxis: headroom(pairs, 'First deaths'), xaxis: { automargin: false, gridcolor: GRID } }, 320, '', phaseFallback)}</div>
        <div>${chart([{ type: 'histogram', x: times, xbins: { size: 15 } }], { title: 'When does the first death happen? (15s buckets)', xaxis: { title: 'Seconds into fight', gridcolor: GRID }, yaxis: { title: 'Pulls', gridcolor: GRID } }, 320, '', firstsNote)}</div></div>`;
    } else {
      html += chart([{ type: 'histogram', x: times, xbins: { size: 15 } }], { title: 'When does the first death happen? (15s buckets)', xaxis: { title: 'Seconds into fight', gridcolor: GRID }, yaxis: { title: 'Pulls', gridcolor: GRID } }, 300, '', firstsNote);
    }
    const pst = {};
    S.forEach(p => { Object.entries(p.parts).forEach(([name, c]) => { const e = pst[name] || (pst[name] = { cl: c, pulls: 0, fd: 0, causes: {}, av: 0, nodef: 0, withc: 0 }); e.pulls++; });
      if (p.deaths.length) { const d = p.deaths[0]; const e = pst[d.pl] || (pst[d.pl] = { cl: d.cl, pulls: 0, fd: 0, causes: {}, av: 0, nodef: 0, withc: 0 }); e.fd++; e.causes[d.tc] = (e.causes[d.tc] || 0) + 1; if (d.hc) { e.withc++; if (!hadDef(d)) e.nodef++; } }
      if (hasA) p.dt.forEach(([name, a, h]) => { if (A.has(norm(a))) { const e = pst[name] || (pst[name] = { cl: '', pulls: 0, fd: 0, causes: {}, av: 0, nodef: 0, withc: 0 }); e.av += h; } }); });
    const heads = [['Player', 'str'], ['Pulls', 'num'], ['First death', 'num'], ['Started the wipe in % of pulls', 'num']].concat(hasA ? [['Avoidable hits / pull', 'num']] : []).concat(withCasts.length ? [['No defensive before death', 'str']] : []).concat([['What killed them', 'str']]);
    html += `<h3>Players</h3><p class='section-note'>"Started the wipe" is first deaths divided by pulls the player was in. Avoidable hits are separate occasions an avoidable ability caught them, per pull.</p>` + tbl(heads,
      Object.entries(pst).sort((x, y) => (y[1].fd / Math.max(y[1].pulls, 1)) - (x[1].fd / Math.max(x[1].pulls, 1))).map(([name, e]) => { const k = Math.max(e.pulls, 1);
        return `<tr data-player='${escH(name)}'><td>${playerCell(name, e.cl, roles[name] || '')}</td><td>${e.pulls}</td><td>${e.fd}</td><td data-sort='${e.fd / k}'>${pct(e.fd, k)}%</td>${hasA ? `<td data-sort='${e.av / k}'>${(e.av / k).toFixed(1)}</td>` : ''}${withCasts.length ? `<td data-sort='${e.withc ? e.nodef / e.withc : -1}'>${e.withc ? `${e.nodef} of ${e.withc}` : '-'}</td>` : ''}<td>${topN(e.causes, 2).map(([a, c]) => `${escH(a)} (${c})`).join(', ') || '-'}</td></tr>`; }), '', `${Object.keys(pst).length} players, most first deaths per pull first`, 15);
    html += `<h3>First death, every pull</h3><p class='section-note'>Expand "Last seconds" for the damage breakdown, what the player cast and what they received in that window. "Deaths ≤10 s" = how many more died within ten seconds of the first death.</p>` + tbl([['Pull', 'num'], ['When', 'str'], ['Result', 'num'], ['Phase', 'str'], ['Time', 'num'], ['Player', 'str'], ['What killed them', 'str'], ['Killing blow', 'str'], ['Defensives', 'str'], ['Deaths ≤10 s', 'num'], ['Deaths', 'num'], ['Last seconds', 'str']],
      S.map(p => { const d = p.deaths[0]; const res = `<td data-sort='${p.p}'>${resLabel(p)}</td>`; const w10 = d ? p.deaths.filter(x => x.s > d.s && x.s <= d.s + 10).length : 0; return d
        ? `<tr><td>${p.i}</td><td>${escH(p.n.slice(4))} ${p.t}</td>${res}<td>${escH(phaseAt(p, d.s) || p.ph || '-')}</td><td data-sort='${d.s}'>${fmtD(d.s)}</td><td class='${cls(d.cl)}'>${escH(d.pl)}</td><td>${escH(d.tc)}</td><td class='muted'>${escH(d.kb)}</td><td>${defCell(d)}</td><td>${w10}</td><td>${p.deaths.length}</td><td>${recapHtml(d)}</td></tr>`
        : `<tr><td>${p.i}</td><td>${escH(p.n.slice(4))} ${p.t}</td>${res}<td>${escH(p.ph || '-')}</td><td colspan='6' class='muted'>no deaths</td><td>0</td><td>0</td><td></td></tr>`; }), 'deathlog', `${S.length} pull${S.length === 1 ? '' : 's'}, in pull order`);
    return html;
  }
  function secDamageTaken(D, S, n, A, IG, hasA, tab, phaseIdx) {
    // phaseIdx >= 0 -> only hits that landed in that phase (per-phase counts come from the payload; amounts are per pull only)
    const order = phaseOrder(S);
    const hitsOf = row => phaseIdx < 0 ? row[2] : ((row[5] || [])[phaseIdx] || 0);
    const ab = {}, abPl = {}, pl = {}, avoidTimes = [];
    let totalDmg = 0, avoidDmg = 0, avoidHits = 0;
    S.forEach(p => { Object.entries(p.parts).forEach(([name, c]) => { const e = pl[name] || (pl[name] = { cl: c, pulls: 0, av: 0, avd: 0, hits: 0, dmg: 0 }); e.pulls++; });
      p.dt.forEach(row => { const [name, a, , amt, times] = row; if (IG.has(norm(a))) return; const h = hitsOf(row);
        const e = ab[a] || (ab[a] = { h: 0, amt: 0, pulls: new Set() }); e.h += h; e.amt += amt; e.pulls.add(p.i); totalDmg += amt;
        (abPl[a] || (abPl[a] = {}))[name] = ((abPl[a] || {})[name] || 0) + h;
        const q = pl[name] || (pl[name] = { cl: '', pulls: 0, av: 0, avd: 0, hits: 0, dmg: 0 }); q.hits += h; q.dmg += amt;
        if (A.has(norm(a))) { q.av += h; q.avd += amt; avoidDmg += amt; avoidHits += h; if (times && phaseIdx < 0) avoidTimes.push(...times); } }); });
    let html = `<h2 id='sec_${tab}_dt'>Damage taken</h2>`;
    if (order.length > 1) {
      html += `<div class='phasebar' role='group' aria-label='Phase filter for hits'><span class='muted'>Hits in:</span><button type='button' class='chip phasebtn' data-phase='-1' aria-pressed='${phaseIdx < 0}'>all phases</button>`
        + order.map((name, i) => `<button type='button' class='chip phasebtn' data-phase='${i}' aria-pressed='${phaseIdx === i}'>${escH(name)}</button>`).join('') + `</div>`;
      if (phaseIdx >= 0) html += `<p class='note'>Showing hits that landed in <b>${escH(order[phaseIdx])}</b>. Damage amounts are only known per pull, so amount columns and charts stay whole-pull.</p>`;
    }
    if (!Object.keys(ab).length) return html + emptyHtml('damage-taken data', 'no damage events were recorded for these pulls', '');
    const roles = rolesOf(S);
    const tc = [['Damage taken / pull', fmtN(totalDmg / n)], ['Distinct abilities', Object.keys(ab).length]];
    if (IG.size) tc.push(['Ignored abilities', IG.size]);
    if (hasA) tc.push(['Avoidable damage / pull', fmtN(avoidDmg / n)], ['Avoidable share', totalDmg ? pct(avoidDmg, totalDmg) + '%' : '-'], ['Avoidable hits / pull', (avoidHits / n).toFixed(1)]);
    html += kpisHtml(tc);
    const topAmt = topN(Object.fromEntries(Object.entries(ab).map(([a, e]) => [a, e.amt])), 15);
    const topHits = topN(Object.fromEntries(Object.entries(ab).filter(([, e]) => e.h > 0).map(([a, e]) => [a, e.h])), 15);
    const col = pairs => pairs.map(([a]) => A.has(norm(a)) ? TOK.accent : TOK.series[0]);
    const amtPairs = topAmt.map(([a, v]) => [a, v / n]), hitPairs = topHits.map(([a, v]) => [a, +(v / n).toFixed(1)]);
    html += `<div class='grid2'><div>${chart([barTrace(amtPairs, col(topAmt))], { title: 'Damage taken per pull - by ability' + (hasA ? ' (gold = avoidable)' : ''), yaxis: headroom(amtPairs, 'Damage / pull') })}</div>
      <div>${hitPairs.length ? chart([barTrace(hitPairs, col(topHits))], { title: 'Hits per pull - by ability', yaxis: headroom(hitPairs, 'Hits / pull') }) : emptyHtml('hits', 'nothing landed in this phase', 'pick all phases above')}</div></div>`;
    const heatAb = (hasA ? topHits.filter(([a]) => A.has(norm(a))) : topHits).slice(0, 12).map(([a]) => a);
    const plSorted = Object.entries(pl).sort((x, y) => ((hasA ? y[1].av : y[1].hits) / Math.max(y[1].pulls, 1)) - ((hasA ? x[1].av : x[1].hits) / Math.max(x[1].pulls, 1)));
    if (heatAb.length && plSorted.length) {
      const z = plSorted.map(([name, e]) => heatAb.map(a => +(((abPl[a] || {})[name] || 0) / Math.max(e.pulls, 1)).toFixed(1)));
      html += chart([heatTrace(z, heatAb, plSorted.map(([name]) => name), 'hits / pull')],
        { title: hasA ? 'Avoidable hits per pull - who is getting hit by what' : 'Hits per pull - who is getting hit by what (top abilities)', yaxis: { autorange: 'reversed' } }, Math.max(320, 22 * plSorted.length + 120));
    }
    if (avoidTimes.length > 1) html += chart([{ type: 'histogram', x: avoidTimes, xbins: { size: 10 } }], { title: 'When do avoidable hits land? (all selected pulls, 10s buckets)', xaxis: { title: 'Seconds into fight', gridcolor: GRID }, yaxis: { title: 'Avoidable hits', gridcolor: GRID } }, 300,
      '', `Only ${avoidTimes.length} avoidable hits in the selection, too few for a timing chart; the Players table below counts them per player.`);
    html += `<p class='section-note'>"Hits" = separate occasions the ability caught a player. A direct hit, the DoT it applies, and a pulsing puddle you stood in for 6 seconds each count once - WCL would show the puddle as 6 hits.</p>`;
    html += `<h3>Players</h3><p class='section-note'>Normalised by pulls participated. Sort by "Avoidable hits / pull" to find who needs a word. Tanks usually top this list because they stand where things land - compare tanks with tanks.</p><label class='filter'><input type='checkbox' class='hideTanks'> Hide tanks</label>`;
    html += tbl([['Player', 'str'], ['Role', 'str'], ['Pulls', 'num']].concat(hasA ? [['Avoidable hits / pull', 'num'], ['Avoidable dmg / pull', 'num']] : []).concat([['All hits / pull', 'num'], ['All dmg / pull', 'num']]),
      plSorted.map(([name, e]) => { const k = Math.max(e.pulls, 1); const role = roles[name] || ''; return `<tr class='role-${role}' data-player='${escH(name)}'><td class='${cls(e.cl)}'>${escH(name)}</td><td class='muted'>${escH(roleLabel(S, name) || role)}</td><td>${e.pulls}</td>${hasA ? `<td data-sort='${e.av / k}'>${(e.av / k).toFixed(1)}</td><td data-sort='${e.avd / k}'>${fmtN(e.avd / k)}</td>` : ''}<td data-sort='${e.hits / k}'>${(e.hits / k).toFixed(1)}</td><td data-sort='${e.dmg / k}'>${fmtN(e.dmg / k)}</td></tr>`; }), '', `${plSorted.length} players, most ${hasA ? 'avoidable ' : ''}hits per pull first`, 15);
    const regs = Object.entries(pl).filter(([, e]) => e.pulls >= 0.5 * n).map(([name]) => name);
    const regulars = regs.length ? regs : Object.keys(pl);
    const pattern = a => {
      const hits = abPl[a] || {}; const total = Object.values(hits).reduce((x, y) => x + y, 0); if (!total) return ['', ''];
      const rates = regulars.map(name => (hits[name] || 0) / Math.max(pl[name].pulls, 1));
      const mean = rates.reduce((x, y) => x + y, 0) / rates.length;
      const cv = mean ? Math.sqrt(rates.reduce((x, r) => x + (r - mean) ** 2, 0) / rates.length) / mean : 0;
      const top2 = topN(hits, 2), top2Share = top2.reduce((x, [, h]) => x + h, 0) / total, top2Tanks = top2.every(([name]) => roles[name] === 'tank');
      const hitShare = regulars.filter(name => hits[name]).length / regulars.length;
      if (top2Share >= 0.7 && top2Tanks) return ['tank', `${Math.round(top2Share * 100)}% of hits on the two tanks`];
      if (cv < 0.3 && hitShare >= 0.8 && mean >= 0.5) return ['raid-wide', `hits ${Math.round(hitShare * 100)}% of regulars about equally (${mean.toFixed(1)}/pull each, spread ${Math.round(cv * 100)}%)`];
      if (top2Share >= 0.6) return ['few', `${Math.round(top2Share * 100)}% of hits on two players`];
      return ['spread', `uneven across the raid (spread ${Math.round(cv * 100)}%)`];
    };
    const review = [];
    const rows = Object.entries(ab).sort((x, y) => y[1].amt - x[1].amt).map(([a, e]) => { const [pat, tip] = pattern(a); const isA = A.has(norm(a)); const warn = isA && (pat === 'raid-wide' || pat === 'tank'); if (warn) review.push(`${a} - ${pat}`);
      return `<tr><td>${escH(a)}</td><td class='muted'>${(D.src[a] || []).slice(0, 2).map(escH).join(', ')}</td><td class='pat-${pat}' title='${escH(tip)}'>${pat}<span class='sub'>${escH(tip)}</span></td>${avoidCell(isA, warn)}<td data-sort='${e.h}'>${e.h}</td><td data-sort='${e.h / n}'>${(e.h / n).toFixed(1)}</td><td data-sort='${e.amt}'>${fmtN(e.amt)}</td><td data-sort='${e.amt / n}'>${fmtN(e.amt / n)}</td><td data-sort='${e.amt / Math.max(e.h, 1)}'>${fmtN(e.amt / Math.max(e.h, 1))}</td><td>${topN(abPl[a] || {}, 3).map(([p, h]) => `${escH(p)} (${h})`).join(', ')}</td></tr>`; });
    html += `<h3>Abilities</h3>`;
    if (review.length) html += `<p class='note'><span class='tag warn'>review</span> ${review.length} avoidable-listed abilit${review.length === 1 ? 'y' : 'ies'} hit the raid like an unavoidable mechanic (${escH(review.join(', '))}). The "Who gets hit" column gives the reasoning. If these really are fail-triggered raid damage keep them; otherwise remove them from avoidable.json, because they are inflating every avoidable number on this tab.</p>`;
    html += `<p class='section-note'>"Who gets hit": <b>raid-wide</b> = everyone about equally (intended damage or a whole-raid punishment); <b>tank</b> = almost only the two tanks; <b>few</b> = concentrated on one or two players (a soak/assignment, or a repeat offender); <b>spread</b> = uneven across the raid - the pattern of genuinely dodgeable damage.</p>`;
    html += tbl([['Ability', 'str'], ['Cast by', 'str'], ['Who gets hit', 'str'], ['Avoidable', 'str'], ['Hits', 'num'], ['Hits / pull', 'num'], ['Total dmg', 'num'], ['Dmg / pull', 'num'], ['Avg per hit', 'num'], ['Hit most', 'str']], rows, '', `${rows.length} abilities, most damage first`, 12);
    return html;
  }
  function secPrep(D, S, n, tab) {
    const cats = D.cats || [], ucats = D.usecats || [];
    const head = `<h2 id='sec_${tab}_prep'>Preparation &amp; consumables</h2>`;
    if (!cats.length) return head + emptyHtml('consumable categories', 'none are configured (config/consumables.json)', '');
    if (!S.some(p => Object.keys(p.cons || {}).length)) return head + emptyHtml('consumable buffs', 'none were found in these pulls', '');
    const per = {}; let pp = 0; const catTot = cats.map(() => 0), useTot = ucats.map(() => 0);
    const mk = (name, p) => per[name] || (per[name] = { cl: p.parts[name] || '', pulls: 0, have: cats.map(() => 0), use: ucats.map(() => 0) });
    S.forEach(p => { Object.entries(p.cons || {}).forEach(([name, flags]) => { const e = mk(name, p); e.pulls++; pp++; flags.forEach((f, i) => { if (f) { e.have[i]++; catTot[i]++; } }); });
      Object.entries(p.use || {}).forEach(([name, counts]) => { const e = mk(name, p); counts.forEach((k, i) => { e.use[i] += k; useTot[i] += k; }); }); });
    const label = c => ({ flask: 'Flask', food: 'Food', vantus: 'Vantus rune', rune: 'Augment rune', prepot: 'Pre-pot', combat_potion: 'Combat potions', healing_potion: 'Healing potions', healthstone: 'Healthstones', mana_potion: 'Mana potions' })[c] || c;
    let html = head + `<p class='section-note'>Flask, food and runes = buffs active on each player when the pull started (WCL combatant info). Pre-pot = a combat potion cast in the 5 s before the pull. The potion and Healthstone columns count uses <em>during</em> the pull (the pre-pot is not included in combat potions).</p>`;
    html += kpisHtml(cats.map((c, i) => [`${label(c)} at pull start`, `${pct(catTot[i], pp)}% <span class='vs'>of ${pp} player-pulls</span>`])
      .concat(ucats.map((c, i) => [`${label(c)} / pull`, `${(useTot[i] / n).toFixed(1)} <span class='vs'>${useTot[i]} in ${n} pull${n === 1 ? '' : 's'}</span>`])));
    html += tbl([['Player', 'str'], ['Pulls', 'num']].concat(cats.map(c => [label(c), 'num'])).concat(ucats.map(c => [label(c), 'num'])).concat([['Missing (flask+food+pre-pot)', 'num']]),
      Object.entries(per).map(([name, e]) => { const core = cats.map((c, i) => ['flask', 'food', 'prepot'].includes(c) ? e.pulls - e.have[i] : 0).reduce((a, b) => a + b, 0);
        return [core, `<tr data-player='${escH(name)}'><td>${playerCell(name, e.cl)}</td><td>${e.pulls}</td>${cats.map((_, i) => prepCell(e.have[i], e.pulls)).join('')}${ucats.map((_, i) => `<td data-sort='${e.use[i]}'>${e.use[i]}${e.pulls > 1 ? ` <span class='muted'>(${(e.use[i] / e.pulls).toFixed(1)}/pull)</span>` : ''}</td>`).join('')}<td data-sort='${core}'>${core}</td></tr>`]; })
        .sort((x, y) => y[0] - x[0]).map(x => x[1]), '', `${Object.keys(per).length} player${Object.keys(per).length === 1 ? '' : 's'}, most missing first`, 15);
    return html;
  }
  function secUtility(S, n, tab) {
    const head = `<h2 id='sec_${tab}_util'>Interrupts &amp; dispels</h2>`;
    if (!S.some(p => p.hx)) return head + emptyHtml('interrupts or dispels', 'WCL returned no Interrupts/Dispels tables for these pulls', '');
    const per = {}; const roles = rolesOf(S);
    S.forEach(p => { if (!p.hx) return; Object.entries(p.parts).forEach(([name, c]) => { const e = per[name] || (per[name] = { cl: c, pulls: 0, ir: 0, ds: 0 }); e.pulls++; e.ir += (p.ir || {})[name] || 0; e.ds += (p.ds || {})[name] || 0; }); });
    const totI = Object.values(per).reduce((a, e) => a + e.ir, 0), totD = Object.values(per).reduce((a, e) => a + e.ds, 0);
    let html = head;
    html += kpisHtml([['Interrupts / pull', (totI / n).toFixed(1)], ['Dispels / pull', (totD / n).toFixed(1)]]);
    html += tbl([['Player', 'str'], ['Pulls', 'num'], ['Interrupts', 'num'], ['Interrupts / pull', 'num'], ['Dispels', 'num'], ['Dispels / pull', 'num']],
      Object.entries(per).sort((x, y) => (y[1].ir + y[1].ds) - (x[1].ir + x[1].ds)).map(([name, e]) => { const k = Math.max(e.pulls, 1); return `<tr data-player='${escH(name)}'><td>${playerCell(name, e.cl, roles[name] || '')}</td><td>${e.pulls}</td><td>${e.ir}</td><td data-sort='${e.ir / k}'>${(e.ir / k).toFixed(2)}</td><td>${e.ds}</td><td data-sort='${e.ds / k}'>${(e.ds / k).toFixed(2)}</td></tr>`; }), '', `${Object.keys(per).length} player${Object.keys(per).length === 1 ? '' : 's'} · counts per pull`, 15);
    html += `<p class='section-note'>Counts from WCL's Interrupts and Dispels tables. Whether a number is good depends on the assignment - use it to check that assigned players actually did the job.</p>`;
    return html;
  }

  // ---- the "player focus" block: one person's numbers against the rest of the raid, over the pulls they were in
  function playerFocus(D, S, P, A, IG, hasA, n, secs) {
    const others = {};
    const me = { av: 0, avd: 0, dmg: 0, hits: 0, fd: 0, deaths: [], byAb: {}, total: 0, heal: 0, act: 0, ir: 0, ds: 0 };
    const byRole = {};
    S.forEach(p => { const spec = (p.specs || {})[P]; if (!spec) return; const r = roleOf(spec); const e = byRole[r] || (byRole[r] = { pulls: 0, secs: 0, dmg: 0, heal: 0, act: 0, specs: new Set() });
      e.pulls++; e.secs += p.d; e.specs.add(spec);
      (p.dd || []).forEach(([name, , , total, act]) => { if (name === P) { e.dmg += total; e.act += act; } });
      (p.hd || []).forEach(([name, , , total]) => { if (name === P) e.heal += total; }); });
    const flex = Object.keys(byRole).length > 1;
    const raidAb = {}; let raidPP = 0;
    S.forEach(p => {
      Object.entries(p.parts).forEach(([name]) => { const o = others[name] || (others[name] = { pulls: 0, av: 0, dmg: 0, fd: 0, deaths: 0 }); o.pulls++; raidPP++; });
      p.dt.forEach(([name, a, h, amt]) => { if (IG.has(norm(a))) return;
        const o = others[name] || (others[name] = { pulls: 0, av: 0, dmg: 0, fd: 0, deaths: 0 }); o.dmg += amt; if (A.has(norm(a))) o.av += h;
        raidAb[a] = (raidAb[a] || 0) + h;
        if (name === P) { me.dmg += amt; me.hits += h; const e = me.byAb[a] || (me.byAb[a] = { h: 0, amt: 0 }); e.h += h; e.amt += amt; if (A.has(norm(a))) { me.av += h; me.avd += amt; } } });
      p.deaths.forEach((d, i) => { const o = others[d.pl] || (others[d.pl] = { pulls: 0, av: 0, dmg: 0, fd: 0, deaths: 0 }); o.deaths++; if (i === 0) o.fd++;
        if (d.pl === P) me.deaths.push(Object.assign({ pull: p.i, night: p.n, t: p.t, first: i === 0, res: resLabel(p), phase: phaseAt(p, d.s) }, d)); if (d.pl === P && i === 0) me.fd++; });
      (p.dd || []).forEach(([name, , , total, act]) => { if (name === P) { me.total += total; me.act += act; } });
      (p.hd || []).forEach(([name, , , total]) => { if (name === P) me.heal += total; });
      me.ir += (p.ir || {})[P] || 0; me.ds += (p.ds || {})[P] || 0;
    });
    const k = Math.max(n, 1);
    const rate = (o, key) => o[key] / Math.max(o.pulls, 1);
    const regulars = Object.entries(others).filter(([name, o]) => name !== P && o.pulls >= 0.5 * n);
    const medAv = median(regulars.map(([, o]) => rate(o, 'av'))), medDmg = median(regulars.map(([, o]) => rate(o, 'dmg'))), medFd = median(regulars.map(([, o]) => rate(o, 'fd')));
    const rankOf = key => { const arr = Object.entries(others).filter(([, o]) => o.pulls >= 0.5 * n).sort((x, y) => rate(y[1], key) - rate(x[1], key)); const i = arr.findIndex(([name]) => name === P); return i < 0 ? '-' : `#${i + 1} of ${arr.length}`; };
    const dps = me.total / (secs || 1), hps = me.heal / (secs || 1);
    const ddRank = (() => { const o = {}; S.forEach(p => (p.dd || []).forEach(([name, , , total]) => { o[name] = (o[name] || 0) + total; })); const arr = Object.entries(o).sort((x, y) => y[1] - x[1]); const i = arr.findIndex(([name]) => name === P); return i < 0 ? '' : ` (#${i + 1} of ${arr.length} by total)`; })();
    const vs = (val, med, fmt, lowerIsBetter = true) => { if (!isFinite(med) || med === 0) return ''; const r = val / med; const good = lowerIsBetter ? r <= 1 : r >= 1; return `<span class='vs delta ${good ? 'better' : 'worse'}'>raid median ${fmt(med)} (${r >= 1 ? '+' : ''}${Math.round((r - 1) * 100)}%, ${good ? 'better' : 'worse'})</span>`; };
    const cards = [['Pulls', n], ['Started the wipe', `${me.fd} <span class='vs'>${pct(me.fd, k)}% of pulls &middot; ${rankOf('fd')}</span>${vs(me.fd / k, medFd, x => Math.round(x * 100) + '%')}`],
      ['Died', `${me.deaths.length} <span class='vs'>${(me.deaths.length / k).toFixed(2)} per pull</span>`]];
    if (hasA) cards.push(['Avoidable hits / pull', `${(me.av / k).toFixed(1)} <span class='vs'>${rankOf('av')} (1 = worst)</span>${vs(me.av / k, medAv, x => x.toFixed(1))}`]);
    cards.push(['Damage taken / pull', `${fmtN(me.dmg / k)} <span class='vs'>${rankOf('dmg')}</span>${vs(me.dmg / k, medDmg, fmtN)}`]);
    if (flex) {
      Object.entries(byRole).sort((x, y) => y[1].pulls - x[1].pulls).forEach(([r, e]) => {
        const val = r === 'healer' ? `${fmtN(e.heal / (e.secs || 1))} HPS` : `${fmtN(e.dmg / (e.secs || 1))} DPS`;
        cards.push([`As ${r} (${[...e.specs].join('/')})`, `${val} <span class='vs'>${e.pulls} pulls &middot; ${(e.secs ? e.act / e.secs * 100 : 0).toFixed(0)}% active</span>`]);
      });
    } else {
      if (me.total) cards.push(['DPS', `${fmtN(dps)} <span class='vs'>${(secs ? me.act / secs * 100 : 0).toFixed(0)}% active${ddRank}</span>`]);
      if (me.heal && me.heal > me.total) cards.push(['HPS', fmtN(hps)]);
    }
    if (S.some(p => p.hx)) cards.push(['Interrupts / dispels', `${me.ir} / ${me.ds} <span class='vs'>${(me.ir / k).toFixed(2)} / ${(me.ds / k).toFixed(2)} per pull</span>`]);
    let html = `<div class='focus'>${kpisHtml(cards)}`;
    if (flex) html += `<p class='section-note'>${escH(P)} played more than one role in these pulls (${Object.entries(byRole).map(([r, e]) => `${r}: ${e.pulls}`).join(', ')}). Damage/healing tables below list each spec separately; deaths and avoidable damage are across all roles.</p>`;
    const mine = Object.entries(me.byAb).sort((x, y) => y[1].amt - x[1].amt).slice(0, 12);
    if (mine.length) {
      const x = mine.map(([a]) => a);
      html += chart([{ type: 'bar', name: P, x, y: mine.map(([, e]) => +(e.h / k).toFixed(2)), marker: { color: x.map(a => A.has(norm(a)) ? TOK.accent : TOK.series[0]) } },
                     { type: 'bar', name: 'raid average', x, y: mine.map(([a]) => +((raidAb[a] || 0) / Math.max(raidPP, 1)).toFixed(2)), marker: { color: TOK.borderControl } }],
                    { title: `${P}: hits per pull by ability vs the raid average${hasA ? ' (gold = avoidable)' : ''}`, barmode: 'group', yaxis: { title: 'Hits / pull', gridcolor: GRID } }, 340);
    }
    if (me.deaths.length) {
      html += `<h3>${escH(P)}'s deaths (${me.deaths.length})</h3>` + tbl([['Pull', 'num'], ['When', 'str'], ['Result', 'num'], ['Time', 'num'], ['Phase', 'str'], ['Tags', 'str'], ['What killed them', 'str'], ['Killing blow', 'str'], ['Defensives', 'str'], ['Last seconds', 'str']],
        me.deaths.map(d => `<tr><td>${d.pull}</td><td>${escH(d.night.slice(4))} ${d.t}</td><td>${d.res}</td><td data-sort='${d.s}'>${fmtD(d.s)}</td><td class='muted'>${escH(d.phase || '-')}</td><td>${d.first ? "<span class='tag'>first</span>" : ''}${d.os ? " <span class='tag'>one-shot</span>" : ''}</td><td>${escH(d.tc)}</td><td class='muted'>${escH(d.kb)}</td><td>${defCell(d)}</td><td>${recapHtml(d)}</td></tr>`), 'deathlog', `${me.deaths.length} death${me.deaths.length === 1 ? '' : 's'}, in pull order`);
    }
    return html + `</div>`;
  }

  // ---------------- render one boss tab for the current selection ----------------
  function renderSelection(tab) {
    const st = loadTab(tab); if (!st) return;
    const grid = $(`.pull-grid[data-tab='${tab}']`), panel = document.getElementById('detail_' + tab);
    const P = st.player, D = st.data;
    $$('.pull-box', grid).forEach(bx => { const on = st.sel.has(+bx.dataset.idx); bx.classList.toggle('sel', on); bx.setAttribute('aria-pressed', on ? 'true' : 'false');
      bx.classList.toggle('absent', !!P && !(P in D.pulls[+bx.dataset.idx - 1].parts)); });
    grid.classList.toggle('has-sel', st.sel.size > 0);
    grid.classList.toggle('has-player', !!P);
    $$('.chip[data-night]', grid.parentElement).forEach(ch => { const idxs = D.pulls.filter(p => p.n === ch.dataset.night).map(p => p.i); const on = idxs.length > 0 && idxs.every(i => st.sel.has(i)); ch.classList.toggle('sel', on); ch.setAttribute('aria-pressed', on ? 'true' : 'false'); });
    st.dirty = false; st.rendered = true;
    updateBadge(tab);

    const filtered = st.sel.size > 0 || !!P;
    panel.classList.toggle('filtered', filtered);
    const base = st.sel.size ? D.pulls.filter(p => st.sel.has(p.i)) : D.pulls;
    const S = P ? base.filter(p => P in p.parts) : base;
    const closeBtn = filtered ? `<button type='button' class='close'>&#10005; show everything</button>` : '';
    if (!S.length) { const why = P ? `${P} was not in any of the selected pulls` : `nothing on this boss in the selected night`;
      panel.innerHTML = `${closeBtn}<h2 class='panel-title'>${escH(D.boss)} <span class='sub'>${escH(D.diff)} &middot; ${escH(P || G.night || (G.ntype === 'open' ? 'Open nights' : 'Main nights'))}</span></h2>${emptyHtml('pulls', why, 'Esc clears the filters')}`;
      panel.querySelector('.close')?.addEventListener('click', clearAll); return; }
    const A = D.avoidSet, IG = D.ignoreSet, hasA = A.size > 0;
    const n = S.length, secs = S.reduce((a, p) => a + p.d, 0);
    const kills = S.filter(p => p.k).length, wipes = S.filter(p => !p.k);
    const best = kills ? 'KILL' : (wipes.length ? Math.min(...wipes.map(p => p.p)).toFixed(1) + '% left' : '-');
    const selNights = [...new Set(S.map(p => p.n))];

    let title = n === 1
      ? `Pull #${S[0].i} &middot; ${escH(S[0].n)} ${S[0].t} &middot; ${S[0].k ? 'KILL' : S[0].p.toFixed(1) + '% left'}${!S[0].k && Math.abs(S[0].fp - S[0].p) > 1 ? ` (fight ${S[0].fp.toFixed(1)}%)` : ''} &middot; ${fmtD(S[0].d)}${S[0].ph ? ' &middot; ended in ' + escH(S[0].ph) : ''}`
      : (selNights.length === 1 && S.length === D.pulls.filter(p => p.n === selNights[0]).length ? `${escH(selNights[0])} &middot; ${n} pulls`
        : (G.ntype && !G.night && !st.sel.size ? `${G.ntype === 'open' ? 'Open' : 'Main'} nights &middot; ${n} pulls` : filtered ? `${n} pulls selected` : `${n} pulls`));
    const wcl = n === 1 ? `<a class='wcl' target='_blank' rel='noopener' href='https://www.warcraftlogs.com/reports/${encodeURIComponent(S[0].code)}#fight=${S[0].fid}'>open on WCL &#8599;</a>` : '';
    if (P) title = `<span class='${cls(D.pulls.find(p => P in p.parts).parts[P])}'>${escH(P)}</span> &middot; ${n} of ${base.length} pulls` + (st.sel.size ? ` in selection` : '') + (n === 1 ? ` &middot; ${title}` : '');
    const secs_ = [['prog', 'Progression'], ['sum', 'Summary'], ['dd', 'Damage done'], ['hd', 'Healing done'], ['deaths', 'Deaths'], ['dt', 'Damage taken'], ['prep', 'Preparation'], ['util', 'Interrupts & dispels']];
    let html = `${closeBtn}<h2 class='panel-title'>${escH(D.boss)} <span class='sub'>${escH(D.diff)} &middot; ${title}${wcl}</span></h2>`;
    if (P) html += playerFocus(D, S, P, A, IG, hasA, n, secs);
    if (n > 1) html += kpisHtml([['Pulls', n], ['Kills', kills], ['Best pull', best], ['Avg duration', fmtD(secs / n)], ['Time in combat', fmtD(secs)], ['Raid nights', selNights.length]]) + secPhaseStrip(S, n);
    let body = '';
    if (n > 1) body += secProgress(D, S, n, tab);
    body += secSummary(D, S, n, secs, IG, tab);
    body += secOutput(S, 'dd', 'DPS', 'dps', 'damage', tab);
    body += secOutput(S, 'hd', 'HPS', 'hps', 'healing', tab);
    body += secDeaths(D, S, n, A, hasA, tab);
    body += secDamageTaken(D, S, n, A, IG, hasA, tab, st.phase);
    body += secPrep(D, S, n, tab);
    body += secUtility(S, n, tab);
    const present = secs_.filter(([k]) => body.includes(`id='sec_${tab}_${k}'`));
    html += `<nav class='secnav' aria-label='Sections'>${present.map(([k, l]) => `<a href='#sec_${tab}_${k}'>${l}</a>`).join('')}</nav>` + body;

    panel.innerHTML = html;
    const progHost = document.getElementById('prog_' + tab);
    if (progHost) drawProgression(progHost, S, detectBreaks(S, D.break_minutes || 4.5, D.busy), (i, additive) => {
      if (additive) { st.sel.has(i) ? st.sel.delete(i) : st.sel.add(i); } else { st.sel.clear(); st.sel.add(i); }
      renderSelection(tab); document.getElementById('detail_' + tab).scrollIntoView({ behavior: SCROLL, block: 'start' }); });
    panel.querySelector('.close')?.addEventListener('click', clearAll);
    $$('.phasebtn', panel).forEach(b => b.addEventListener('click', () => { st.phase = +b.dataset.phase; renderSelection(tab); document.getElementById(`sec_${tab}_dt`)?.scrollIntoView({ behavior: SCROLL, block: 'start' }); }));
    // player rows carry data-player; older markup falls back to the name span (not the whole cell, which also holds the role tag)
    if (P) $$('table.sortable tbody tr', panel).forEach(tr => { const nm = tr.children[0] && tr.children[0].querySelector('.player'); if (tr.dataset.player === P || (nm && nm.textContent.trim() === P)) tr.classList.add('me'); });
    wireSort(panel); wireToggles(panel);
    drawCharts();
    $$('.plot', panel).forEach(el => { if (el.on) el.on('plotly_click', ev => onChartClick(tab, ev)); });
  }
  function onChartClick(tab, ev) {
    // only charts whose x axis is the pull number map a click to a pull
    const st = loadTab(tab); if (!st || !ev.points.length) return;
    const xt = ev.points[0].xaxis && ev.points[0].xaxis.title && ev.points[0].xaxis.title.text;
    if (!xt || !/^Pull #/.test(xt)) return;
    const i = +ev.points[0].x; if (!Number.isInteger(i)) return;
    const mod = ev.event && (ev.event.ctrlKey || ev.event.metaKey || ev.event.shiftKey);
    if (mod) { st.sel.has(i) ? st.sel.delete(i) : st.sel.add(i); } else { st.sel.clear(); st.sel.add(i); }
    renderSelection(tab);
    document.getElementById('detail_' + tab).scrollIntoView({ behavior: SCROLL, block: 'start' });
  }

  // ---------------- pull grid interaction ----------------
  $$('.pull-grid').forEach(grid => {
    const tab = grid.dataset.tab;
    const mod = e => e.ctrlKey || e.metaKey || e.shiftKey;
    grid.addEventListener('click', e => {
      const bx = e.target.closest('.pull-box'); if (!bx) return;
      const st = loadTab(tab); if (!st) return;
      const i = +bx.dataset.idx;
      if (mod(e)) { st.sel.has(i) ? st.sel.delete(i) : st.sel.add(i); }
      else if (st.sel.size === 1 && st.sel.has(i)) st.sel.clear();
      else { st.sel.clear(); st.sel.add(i); }
      renderSelection(tab);
    });
    $$('.chip[data-night]', grid.parentElement).forEach(ch => ch.addEventListener('click', e => {
      const st = loadTab(tab); if (!st) return;
      const idxs = st.data.pulls.filter(p => p.n === ch.dataset.night).map(p => p.i);
      const all = idxs.every(i => st.sel.has(i));
      if (!mod(e)) st.sel.clear();
      idxs.forEach(i => (all && !mod(e)) ? st.sel.delete(i) : st.sel.add(i));
      renderSelection(tab);
    }));
  });

  // ---------------- global filters (toolbar above the tabs) ----------------
  const G = { night: '', player: '', ntype: '' };
  const gNight = document.getElementById('gNight'), gPlayer = document.getElementById('gPlayer'), gType = document.getElementById('gType'), toolbar = $('.toolbar');
  const typeOk = p => !G.ntype || (G.ntype === 'open') === !!p.o;
  // the filters are a <details>: open on desktop (CSS hides the summary), closed on phones; the summary counts active filters
  const filtersBox = $('details.filters'), filtersCount = filtersBox && filtersBox.querySelector('.count');
  if (filtersBox && window.matchMedia && window.matchMedia('(max-width:700px)').matches) filtersBox.open = false;
  function updateFilterCount() {
    if (!filtersCount) return;
    const n = [gType && !gType.hidden ? gType : null, gNight, gPlayer].filter(el => el && el.value).length;
    filtersCount.textContent = `(${n} active)`;
  }
  updateFilterCount();

  function applyGlobal() {
    G.night = gNight.value; G.player = gPlayer.value; G.ntype = gType ? gType.value : '';
    if (gType) [...gNight.options].forEach(o => { if (!o.value) return; const isOpen = o.value.endsWith(' open'); o.hidden = !!G.ntype && ((G.ntype === 'open') !== isOpen); });
    if (G.night && G.ntype && ((G.ntype === 'open') !== G.night.endsWith(' open'))) { gNight.value = ''; G.night = ''; }
    toolbar.classList.toggle('active', !!(G.night || G.player || G.ntype));
    updateFilterCount();
    bossTabs.forEach(tab => { const st = loadTab(tab); if (!st) return;
      st.sel.clear();
      if (G.night) st.data.pulls.filter(p => p.n === G.night).forEach(p => st.sel.add(p.i));
      else if (G.ntype) st.data.pulls.filter(typeOk).forEach(p => st.sel.add(p.i));
      st.player = G.player; st.dirty = true; updateBadge(tab);
    });
    playersDirty = true;
    const cur = activeTab();
    if (cur && /^tab\d+$/.test(cur) && !filteredPulls(cur).length) {
      const first = bossTabs.find(t => filteredPulls(t).length && !$(`.tab-btn[data-tab='${t}']`)?.classList.contains('diff-hidden')) || bossTabs.find(t => filteredPulls(t).length);
      if (first) { activateTab(first, false); return; }
    }
    renderIfDirty(cur);
  }
  function renderIfDirty(tab) {
    if (!tab) return;
    if (tab === 'tabPlayers') { if (playersDirty) renderPlayersTab(); return; }
    const st = PD[tab]; if (st && (st.dirty || !st.rendered)) renderSelection(tab);
  }
  function clearAll() {
    gNight.value = ''; gPlayer.value = ''; if (gType) gType.value = '';
    G.night = ''; G.player = ''; G.ntype = '';
    [...gNight.options].forEach(o => o.hidden = false);
    toolbar.classList.remove('active');
    updateFilterCount();
    bossTabs.forEach(tab => { const st = PD[tab]; if (!st) return; st.sel.clear(); st.player = ''; st.dirty = true; updateBadge(tab); });
    playersDirty = true;
    renderIfDirty(activeTab());
  }
  function filteredPulls(tab) {
    const st = loadTab(tab); if (!st) return [];
    let S = G.night ? st.data.pulls.filter(p => p.n === G.night) : st.data.pulls.filter(typeOk);
    if (G.player) S = S.filter(p => G.player in p.parts);
    return S;
  }
  function updateBadge(tab) {
    const st = PD[tab], tabBtn = $(`.tab-btn[data-tab='${tab}']`), btn = tabBtn && tabBtn.querySelector('.badge'); if (!st || !btn) return;
    if (!btn.dataset.orig) btn.dataset.orig = btn.textContent;
    if (!G.night && !G.player && !G.ntype) { btn.textContent = btn.dataset.orig; tabBtn.classList.remove('empty'); tabBtn.title = ''; return; }
    const S = filteredPulls(tab);
    if (!S.length) { btn.textContent = '-'; tabBtn.classList.add('empty'); tabBtn.title = G.night && G.player ? `${G.player} did not pull this boss on ${G.night}` : G.night ? `not pulled on ${G.night}` : `${G.player} was not in any pull on this boss`; return; }
    tabBtn.classList.remove('empty'); tabBtn.title = `${S.length} pull${S.length === 1 ? '' : 's'}`;
    btn.textContent = S.some(p => p.k) ? '✓ ' + S.length : Math.round(Math.min(...S.map(p => p.p))) + '% · ' + S.length;
  }
  document.addEventListener('click', e => {
    const a = e.target.closest('.gotab'); if (!a) return;
    e.preventDefault();
    const btn = $(`.tab-btn[data-tab='${a.dataset.tab}']`);
    if (btn && btn.dataset.diff && btn.classList.contains('diff-hidden')) setDiff(btn.dataset.diff);
    activateTab(a.dataset.tab, true); window.scrollTo({ top: 0, behavior: SCROLL });
  });
  // Plotly charts drawn inside a closed <details> (Home: Open nights) get the fallback size; resize them on open.
  // 'toggle' does not bubble, so listen in the capture phase.
  document.addEventListener('toggle', e => {
    const d = e.target;
    if (d instanceof HTMLDetailsElement && d.open && d.querySelector('.js-plotly-plot')) window.dispatchEvent(new Event('resize'));
  }, true);
  const gWide = document.getElementById('gWide');
  const setWide = on => { document.body.classList.toggle('wide', on); gWide.checked = on; window.dispatchEvent(new Event('resize')); };
  setWide(store.get('wcl_dash_wide') === '1');
  gWide.addEventListener('change', e => { setWide(e.target.checked); store.set('wcl_dash_wide', e.target.checked ? '1' : '0'); });
  if (gType) gType.addEventListener('change', applyGlobal);
  gNight.addEventListener('change', applyGlobal);
  gPlayer.addEventListener('change', applyGlobal);
  document.getElementById('gClear').addEventListener('click', clearAll);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && (G.night || G.player || G.ntype || bossTabs.some(t => PD[t] && PD[t].sel.size))) clearAll(); });

  // ---------------- Players tab under a global filter ----------------
  function renderPlayersTab() {
    const stat = document.getElementById('static_tabPlayers'), panel = document.getElementById('detail_tabPlayers');
    playersDirty = false;
    if (!G.night && !G.player && !G.ntype) { panel.classList.remove('open', 'filtered'); panel.innerHTML = ''; stat.classList.remove('hidden'); return; }
    stat.classList.add('hidden');
    const nightOk = p => G.night ? p.n === G.night : typeOk(p);
    let html = `<button type='button' class='close'>&#10005; show everything</button>`;
    if (G.player) {
      html += `<h2 class='panel-title'>${escH(G.player)} <span class='sub'>${G.night ? escH(G.night) + ' &middot; ' : ''}per boss</span></h2>`;
      const rows = [];
      bossTabs.forEach(tab => { const st = loadTab(tab); if (!st) return; const D = st.data, A = D.avoidSet, IG = D.ignoreSet;
        let S = D.pulls.filter(nightOk); S = S.filter(p => G.player in p.parts); if (!S.length) return;
        let fd = 0, deaths = 0, av = 0, dmg = 0, total = 0, heal = 0, secs = 0;
        S.forEach(p => { secs += p.d; p.deaths.forEach((d, i) => { if (d.pl === G.player) { deaths++; if (i === 0) fd++; } });
          p.dt.forEach(([name, a, h, amt]) => { if (name !== G.player || IG.has(norm(a))) return; dmg += amt; if (A.has(norm(a))) av += h; });
          (p.dd || []).forEach(([name, , , t]) => { if (name === G.player) total += t; }); (p.hd || []).forEach(([name, , , t]) => { if (name === G.player) heal += t; }); });
        const n = S.length;
        rows.push(`<tr><td><button type='button' class='gotab linklike' data-tab='${tab}'>${escH(TAB_NAMES[tab])}</button></td><td>${n}</td><td>${fd}</td><td data-sort='${fd / n}'>${pct(fd, n)}%</td><td>${deaths}</td>${A.size ? `<td data-sort='${av / n}'>${(av / n).toFixed(1)}</td>` : `<td class='muted'>-</td>`}<td data-sort='${dmg / n}'>${fmtN(dmg / n)}</td><td data-sort='${total / (secs || 1)}'>${fmtN(total / (secs || 1))}</td><td data-sort='${heal / (secs || 1)}'>${fmtN(heal / (secs || 1))}</td></tr>`);
      });
      html += rows.length ? tbl([['Boss', 'str'], ['Pulls', 'num'], ['First death', 'num'], ['Started the wipe', 'num'], ['Deaths', 'num'], ['Avoidable hits / pull', 'num'], ['Dmg taken / pull', 'num'], ['DPS', 'num'], ['HPS', 'num']], rows, '', `${rows.length} boss${rows.length === 1 ? '' : 'es'} with pulls in this selection`)
                          : emptyHtml('pulls', `${G.player} has no pulls in this selection`, 'Esc clears the filters');
      html += `<p class='section-note'>Click a boss name to open that tab with the same filters.</p>`;
    } else {
      html += `<h2 class='panel-title'>${escH(G.night || (G.ntype === 'open' ? 'Open nights' : 'Main nights'))} <span class='sub'>all bosses</span></h2>`;
      const o = {}; let anyA = false;
      bossTabs.forEach(tab => { const st = loadTab(tab); if (!st) return; const D = st.data, A = D.avoidSet, IG = D.ignoreSet; anyA = anyA || A.size > 0;
        D.pulls.filter(nightOk).forEach(p => {
          Object.entries(p.parts).forEach(([name, c]) => { const e = o[name] || (o[name] = { cl: c, pulls: 0, bosses: new Set(), fd: 0, av: 0, causes: {} }); e.pulls++; e.bosses.add(tab); });
          if (p.deaths.length) { const d = p.deaths[0]; const e = o[d.pl] || (o[d.pl] = { cl: d.cl, pulls: 0, bosses: new Set(), fd: 0, av: 0, causes: {} }); e.fd++; e.causes[d.tc] = (e.causes[d.tc] || 0) + 1; }
          p.dt.forEach(([name, a, h]) => { if (A.has(norm(a)) && !IG.has(norm(a))) { const e = o[name] || (o[name] = { cl: '', pulls: 0, bosses: new Set(), fd: 0, av: 0, causes: {} }); e.av += h; } }); }); });
      html += tbl([['Player', 'str'], ['Pulls', 'num'], ['Bosses', 'num'], ['First death', 'num'], ['Started the wipe in % of pulls', 'num']].concat(anyA ? [['Avoidable hits / pull', 'num']] : []).concat([['What killed them', 'str']]),
          Object.entries(o).sort((x, y) => (y[1].fd / Math.max(y[1].pulls, 1)) - (x[1].fd / Math.max(x[1].pulls, 1))).map(([name, e]) => { const k = Math.max(e.pulls, 1);
            return `<tr data-player='${escH(name)}'><td>${playerCell(name, e.cl)}</td><td>${e.pulls}</td><td>${e.bosses.size}</td><td>${e.fd}</td><td data-sort='${e.fd / k}'>${pct(e.fd, k)}%</td>${anyA ? `<td data-sort='${e.av / k}'>${(e.av / k).toFixed(1)}</td>` : ''}<td>${topN(e.causes, 2).map(([a, c]) => `${escH(a)} (${c})`).join(', ') || '-'}</td></tr>`; }), '', `${Object.keys(o).length} players, most first deaths per pull first`, 15);
    }
    panel.innerHTML = html; panel.classList.add('open', 'filtered');
    panel.querySelector('.close').addEventListener('click', clearAll);
    wireSort(panel); wireToggles(panel);
  }

  // deep links: dashboard.html#tab3 opens that tab, #tab3:deaths also scrolls to a section; the hash follows the active tab
  tabButtons.forEach(btn => btn.addEventListener('click', () => { try { history.replaceState(null, '', '#' + btn.dataset.tab); } catch (_) { /* ignore */ } }));
  const [wanted, wantedSec] = (location.hash || '').slice(1).split(':');
  if (wanted && document.getElementById(wanted) && $(`.tab-btn[data-tab='${wanted}']`)) {
    const btn = $(`.tab-btn[data-tab='${wanted}']`);
    if (btn.dataset.diff && btn.classList.contains('diff-hidden')) setDiff('all', false);   // show the tab; never persist a deep link
    activateTab(wanted, false);
    const sec = wantedSec && document.getElementById(`sec_${wanted}_${wantedSec}`);
    if (sec) sec.scrollIntoView({ behavior: 'auto', block: 'start' });
  } else renderIfDirty(activeTab());   // boss tabs render lazily when opened
  // loading state ends: tab strip usable, panels no longer busy, skeletons gone
  $('.tabs').removeAttribute('inert');
  $$('[aria-busy]').forEach(el => el.removeAttribute('aria-busy'));
  $$('.skeleton').forEach(el => el.remove());
  // Python-rendered charts with a legend get the same phone layout as the JS ones (drawCharts marks its own with data-narrow)
  if (window.Plotly && window.matchMedia && window.matchMedia('(max-width:700px)').matches)
    $$('.js-plotly-plot').forEach(el => { if (el.dataset.narrow || !(el._fullLayout && el._fullLayout.showlegend)) return;
      el.dataset.narrow = '1'; try { Plotly.relayout(el, narrowLegend(el.layout)); } catch (err) { dashShowError(err); } });
  document.body.dataset.dashReady = '1';
})().catch(dashShowError);
