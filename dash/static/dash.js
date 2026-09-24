/* WCL raid dashboard - client side.
   Boss tabs are rendered entirely here from the compressed per-boss payload
   (one <script type="application/gzip+base64" id="data_tabN"> per boss). */
function dashShowError(err) {
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
  const TOK = { ink: tok('ink'), inkDim: tok('ink-dim'), border: tok('border'), borderStrong: tok('border-strong'),
    surfaceCard: tok('surface-card'), surfaceRaised: tok('surface-raised'), accent: tok('accent'),
    good: tok('good'), warn: tok('warn'), bad: tok('bad'), series: [1, 2, 3, 4, 5, 6].map(i => tok('series-' + i)) };

  // ---------------- small helpers ----------------
  const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
  const fmtN = n => n >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : Math.round(n).toString();
  const fmtD = s => { s = Math.round(s); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  const escH = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, '&#39;').replace(/"/g, '&quot;');
  const cls = c => String(c || '').replace(/\s+/g, '');
  const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
  const median = arr => { const s = [...arr].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : 0; };
  const topN = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n);
  const pctColor = p => { const t = Math.max(0, Math.min(1, p / 100)); return `rgb(${Math.round(60 + 160 * t)},${Math.round(180 - 120 * t)},70)`; };
  const parseCls = v => v >= 100 ? 'p-art' : v >= 99 ? 'p-leg' : v >= 95 ? 'p-ora' : v >= 75 ? 'p-pur' : v >= 50 ? 'p-blu' : v >= 25 ? 'p-gre' : 'p-gra';
  const TANKS = new Set(['Protection', 'Blood', 'Vengeance', 'Guardian', 'Brewmaster']);
  const HEALERS = new Set(['Holy', 'Discipline', 'Restoration', 'Mistweaver', 'Preservation']);
  const roleOf = spec => TANKS.has(spec) ? 'tank' : HEALERS.has(spec) ? 'healer' : 'dps';
  const tbl = (heads, rows, extra, caption) => `<div class='tw'><table class='sortable ${extra || ''}'>${caption ? `<caption class='sr-only'>${escH(caption)}</caption>` : ''}<thead><tr>${heads.map(h => `<th scope='col' data-type='${h[1]}' tabindex='0' aria-sort='none'>${escH(h[0])}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
  const cardsHtml = (items, extra) => `<div class='cards ${extra || ''}'>${items.map(([l, v]) => `<div class='card'><div class='card-value'>${v}</div><div class='card-label'>${escH(l)}</div></div>`).join('')}</div>`;
  const lowLabel = (hidden, maxP, what) => hidden ? `<label class='filter'><input type='checkbox' class='showLow'> Show ${hidden} hidden player${hidden === 1 ? '' : 's'} with under 25% ${what || 'participation'} (fewer than ${Math.round(0.25 * maxP)} of ${maxP} pulls)</label>` : '';
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
    return lay;
  }
  // --- end pure chart helpers ---
  let chartSeq = 0;
  const charts = [];
  function chart(traces, layout, height) {
    const id = 'dyn_chart_' + (++chartSeq);
    const h = height || 380;
    charts.push([id, traces, chartLayout(LAYOUT, layout, h)]);
    return `<div class='chart' id='${id}' role='img' style='--h:${h}px'></div>`;   // reserved height: no layout shift while Plotly draws
  }
  function drawCharts() {
    while (charts.length) {
      const [id, tr, lay] = charts.shift(); const el = document.getElementById(id); if (!el || !window.Plotly) continue;
      try { Plotly.newPlot(el, tr, lay, { responsive: true, displaylogo: false }); }
      catch (err) { el.innerHTML = `<p class='muted'>chart failed: ${escH(err && err.message || err)}</p>`; dashShowError(`chart "${lay.title && (lay.title.text || lay.title) || id}": ${err && (err.stack || err.message) || err}`); }
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

  async function inflate(el) {
    if (el.type === 'application/json') return JSON.parse(el.textContent);
    const bin = atob(el.textContent.trim());
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const stream = new Blob([u8]).stream().pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(stream).text());
  }
  const needsDecompress = bossTabs.some(t => { const el = document.getElementById('data_' + t); return el && el.type !== 'application/json'; });
  if (needsDecompress && !window.DecompressionStream) { const b = document.getElementById('oldBrowser'); if (b) b.hidden = false; }
  else {
    await Promise.all(bossTabs.map(async tab => {
      const el = document.getElementById('data_' + tab); if (!el) return;
      const data = await inflate(el);
      data.avoidSet = new Set(data.avoidable); data.ignoreSet = new Set(data.ignored);
      data.nights = [...new Set(data.pulls.map(p => p.n))];
      PD[tab] = { data, sel: new Set(), player: '', dirty: true, rendered: false, phase: -1 };
    }));
  }
  const loadTab = tab => PD[tab] || null;

  // ---------------- tabs (ARIA tablist + arrow keys + difficulty segment + mobile select) ----------------
  const tabButtons = $$('.tab-btn');
  const tabSelect = document.getElementById('tabSelect');
  function activateTab(id, focus) {
    tabButtons.forEach(b => { const on = b.dataset.tab === id; b.classList.toggle('active', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); });
    $$('.tab-panel').forEach(p => { const on = p.id === id; p.classList.toggle('active', on); p.hidden = !on; });
    if (tabSelect) tabSelect.value = id;
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
    tabButtons.forEach(b => { const o = document.createElement('option'); o.value = b.dataset.tab; o.textContent = b.textContent.replace(/\s+/g, ' ').trim(); tabSelect.appendChild(o); });
    tabSelect.addEventListener('change', () => activateTab(tabSelect.value, false));
  }
  // difficulty segment: show one difficulty's boss tabs at a time (default: the highest difficulty present)
  const diffBtns = $$('.diffbtn');
  function setDiff(d) {
    diffBtns.forEach(b => b.setAttribute('aria-pressed', b.dataset.diff === d ? 'true' : 'false'));
    tabButtons.forEach(b => { if (b.dataset.diff) b.classList.toggle('diff-hidden', d !== 'all' && b.dataset.diff !== d); });
    store.set('wcl_dash_diff', d);
    const cur = $('.tab-btn.active');
    if (cur && cur.classList.contains('diff-hidden')) { const first = tabButtons.find(b => b.dataset.diff === d); if (first) activateTab(first.dataset.tab, false); }
  }
  if (diffBtns.length) {
    const present = diffBtns.map(b => b.dataset.diff).filter(d => d !== 'all');
    const saved = store.get('wcl_dash_diff');
    setDiff(saved && (saved === 'all' || present.includes(saved)) ? saved : present[present.length - 1]);
    diffBtns.forEach(b => b.addEventListener('click', () => setDiff(b.dataset.diff)));
  }

  // ---------------- sortable tables + toggles ----------------
  function wireSort(root) {
    $$('table.sortable th', root).forEach(th => {
      const sort = () => {
        const table = th.closest('table'), tbody = table.querySelector('tbody');
        const type = th.dataset.type || 'str';
        const asc = !th.classList.contains('sorted-asc');
        table.querySelectorAll('th').forEach(h => { h.classList.remove('sorted-asc', 'sorted-desc'); h.setAttribute('aria-sort', 'none'); });
        th.classList.add(asc ? 'sorted-asc' : 'sorted-desc'); th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        const idx = Array.from(th.parentNode.children).indexOf(th);
        const val = tr => {
          const td = tr.children[idx];
          if (!td) return type === 'num' ? Number.POSITIVE_INFINITY : '';
          const raw = td.dataset.sort !== undefined ? td.dataset.sort : td.textContent.trim();
          if (type === 'num') { const n = parseFloat(String(raw).replace('%', '').replace('KILL', '0').replace('+', '')); return isNaN(n) ? Number.POSITIVE_INFINITY : n; }
          return String(raw).toLowerCase();
        };
        Array.from(tbody.querySelectorAll('tr')).sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); }).forEach(tr => tbody.appendChild(tr));
      };
      th.addEventListener('click', sort);
      th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(); } });
    });
  }
  function wireToggles(root) {
    // a label inside a .lowgroup toggles the whole group (all role tables); otherwise the next table after the label
    const nextTable = cb => { let el = cb.closest('label').nextElementSibling; while (el && !el.querySelector?.('table') && el.tagName !== 'TABLE') el = el.nextElementSibling; return el ? (el.tagName === 'TABLE' ? el : el.querySelector('table')) : null; };
    const target = cb => cb.closest('.lowgroup') || nextTable(cb);
    $$('input.showLow', root).forEach(cb => cb.addEventListener('change', () => { const t = target(cb); if (t) t.classList.toggle('show-low', cb.checked); }));
    $$('input.hideTanks', root).forEach(cb => cb.addEventListener('change', () => { const t = nextTable(cb); if (t) t.classList.toggle('hide-tanks', cb.checked); }));
  }
  wireSort(document); wireToggles(document);
  const mpOnly = document.getElementById('mpOnlyMissing');
  if (mpOnly) mpOnly.addEventListener('change', e => $$('table.mplus tbody tr').forEach(tr => { tr.style.display = (e.target.checked && tr.dataset.status === 'met') ? 'none' : ''; }));
  // compact pull grid (remembered)
  const compact = store.get('wcl_dash_compact') === '1';
  $$('input.compactGrid').forEach(cb => { cb.checked = compact; cb.addEventListener('change', () => { $$('.pull-grid').forEach(g => g.classList.toggle('compact', cb.checked)); $$('input.compactGrid').forEach(o => { o.checked = cb.checked; }); store.set('wcl_dash_compact', cb.checked ? '1' : '0'); }); });
  if (compact) $$('.pull-grid').forEach(g => g.classList.add('compact'));

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
    return cardsHtml(later.map(name => { const times = S.map(p => (p.pt || []).find(x => x[0] === name)).filter(Boolean).map(x => x[1]);
      return [`${name}`, times.length ? `${times.length}/${n} pulls <span class='vs'>${pct(times.length, n)}% &middot; fastest ${fmtD(Math.min(...times))} &middot; median ${fmtD(median(times))}</span>` : `0/${n} pulls <span class='vs'>never reached</span>`]; }), 'kpi-strip');
  }
  function secProgress(D, S, n, tab) {
    let html = '';
    const wipes = S.filter(p => !p.k), selNights = [...new Set(S.map(p => p.n))];
    const breaks = detectBreaks(S, D.break_minutes || 4.5, D.busy);
    const shapes = [], annotations = [];
    S.forEach((p, j) => { if (j && p.n !== S[j - 1].n) shapes.push({ type: 'line', x0: S[j - 1].i + 0.5, x1: S[j - 1].i + 0.5, y0: 0, y1: 1, yref: 'paper', line: { color: '#3a3f4a', width: 1 } }); });
    breaks.forEach(br => { const x = br.after + 0.5; shapes.push({ type: 'line', x0: x, x1: x, y0: 0, y1: 1, yref: 'paper', line: { color: '#d4ad2f', width: 1, dash: 'dash' } });
      annotations.push({ x, y: 1, yref: 'paper', text: `break ${Math.round(br.gap)}m`, showarrow: false, yanchor: 'bottom', font: { color: '#d4ad2f', size: 11 } }); });
    const traces = selNights.map((night, i) => { const ps = S.filter(p => p.n === night); return { type: 'scatter', mode: 'lines+markers', name: night, line: lineStyle(i),
      x: ps.map(p => p.i), y: ps.map(p => p.p), marker: { size: 9, symbol: ps.map(p => p.k ? 'star' : symbolOf(i)) },
      hovertext: ps.map(p => `Pull #${p.i} @ ${p.t}<br>${p.k ? 'KILL' : p.p.toFixed(1) + '% boss HP left'}${!p.k && Math.abs(p.fp - p.p) > 1 ? `<br>fight progress left ${p.fp.toFixed(1)}%` : ''}${p.ph ? '<br>' + p.ph : ''}<br>${fmtD(p.d)} - ${p.deaths.length} deaths`), hoverinfo: 'text' }; });
    html += `<h2 id='sec_${tab}_prog'>Progression</h2>`;
    html += chart(traces, { title: { text: 'Boss HP remaining at end of each pull (lower = closer to kill)', y: 0.98 }, xaxis: { title: 'Pull # (chronological)', gridcolor: GRID, range: [Math.min(...S.map(p => p.i)) - 0.7, Math.max(...S.map(p => p.i)) + 0.7] },
      yaxis: { title: '% HP remaining', range: [-4, 104], tickvals: [0, 20, 40, 60, 80, 100], gridcolor: GRID }, legend: { orientation: 'h', yanchor: 'bottom', y: 1.06, x: 0 }, margin: { l: 45, r: 20, t: 95, b: 45 }, shapes, annotations }, 430);
    html += `<p class='muted'>Click a point to inspect that pull. Dashed gold lines are breaks (${(D.break_minutes || 4.5)}+ idle minutes; trash or other bosses fought in the gap do not count). Nights differ by colour, line style and marker.</p>`;
    if (breaks.length) {
      const avg = ps => ps.length ? ps.reduce((a, p) => a + p.p, 0) / ps.length : 0, best = ps => ps.length ? Math.min(...ps.map(p => p.p)) : 0;
      html += `<h5>Breaks</h5><p class='muted'>Before/after compare the 5 pulls either side; lower % is better, so a negative change means the raid came back sharper.</p>` + tbl([['Night', 'str'], ['Resumed', 'str'], ['Length', 'num'], ['Before break', 'num'], ['After break', 'num'], ['Change (avg %)', 'str'], ['First pull back', 'str']],
        breaks.map(br => { const d = br.before.length && br.afterPulls.length ? avg(br.afterPulls) - avg(br.before) : null; const f = br.afterPulls[0];
          return `<tr><td>${escH(br.night)}</td><td>${escH(br.resume)}</td><td data-sort='${br.gap}'>${Math.round(br.gap)} min${br.busy >= 1 ? ` <span class='muted'>(+${Math.round(br.busy)} min fighting in between)</span>` : ''}</td><td data-sort='${avg(br.before)}'>${br.before.length} pulls, avg ${avg(br.before).toFixed(1)}%, best ${best(br.before).toFixed(1)}%</td><td data-sort='${avg(br.afterPulls)}'>${br.afterPulls.length} pulls, avg ${avg(br.afterPulls).toFixed(1)}%, best ${best(br.afterPulls).toFixed(1)}%</td><td>${d === null ? '-' : `<span style='color:${d < 0 ? '#8ce0a8' : '#e08a8a'}'>${d >= 0 ? '+' : ''}${d.toFixed(1)} pts ${d < 0 ? '(better)' : '(worse)'}</span>`}</td><td>${f ? resLabel(f) : '-'}</td></tr>`; }), '', 'Breaks');
    }
    // wipes by phase + time to reach each phase
    const ph = {}; wipes.forEach(p => { if (p.ph) ph[p.ph] = (ph[p.ph] || 0) + 1; });
    const order = phaseOrder(S);
    const later = order.slice(1);
    if (Object.keys(ph).length || later.length) html += `<h5>Phases</h5>`;
    const grid = [];
    if (Object.keys(ph).length) grid.push(chart([barTrace(order.filter(x => ph[x]).map(x => [x, ph[x]]))], { title: 'Wipes by phase (phase the pull ended in)', yaxis: headroom(Object.entries(ph), 'Wipes') }, 320));
    if (later.length) {
      const traces = later.map((name, i) => { const pts = S.map(p => { const e = (p.pt || []).find(x => x[0] === name); return e ? [p.i, e[1], p] : null; }).filter(Boolean);
        return { type: 'scatter', mode: 'lines+markers', name, line: lineStyle(i), marker: { symbol: symbolOf(i), size: 8 }, x: pts.map(x => x[0]), y: pts.map(x => x[1]), hovertext: pts.map(x => `Pull #${x[0]} (${escH(x[2].n)} ${x[2].t})<br>${escH(name)} at ${fmtD(x[1])}`), hoverinfo: 'text' }; });
      grid.push(chart(traces, { title: 'How fast do we reach each phase? (seconds into the pull)', xaxis: { title: 'Pull #', gridcolor: GRID }, yaxis: { title: 'Seconds', gridcolor: GRID }, legend: { orientation: 'h', yanchor: 'bottom', y: 1.06, x: 0 }, margin: { l: 45, r: 20, t: 95, b: 45 } }, 320));
    }
    if (grid.length) html += `<div class='grid2'>${grid.map(g => `<div>${g}</div>`).join('')}</div>`;
    if (later.length) {
      html += tbl([['Phase', 'str'], ['Reached in', 'num'], ['Median time', 'num'], ['Fastest', 'num'], ['Slowest', 'num'], ['Last pull that got there', 'str']],
        later.map(name => { const times = S.map(p => (p.pt || []).find(x => x[0] === name)).filter(Boolean).map(x => x[1]); const lastP = [...S].reverse().find(p => (p.pt || []).some(x => x[0] === name));
          return `<tr><td>${escH(name)}</td><td data-sort='${times.length / n}'>${times.length} of ${n} pulls (${pct(times.length, n)}%)</td><td data-sort='${median(times)}'>${times.length ? fmtD(median(times)) : '-'}</td><td data-sort='${Math.min(...times)}'>${times.length ? fmtD(Math.min(...times)) : '-'}</td><td data-sort='${Math.max(...times)}'>${times.length ? fmtD(Math.max(...times)) : '-'}</td><td>${lastP ? `#${lastP.i} (${escH(lastP.n.slice(4))} ${lastP.t})` : '-'}</td></tr>`; }), '', 'Time to reach each phase')
        + `<p class='muted'>Reaching a phase earlier, more often, is progress even when the end % does not move.</p>`;
    }
    if (selNights.length > 1) {
      html += `<h5>Per raid night</h5>` + tbl([['Night', 'str'], ['Pulls', 'num'], ['Kills', 'num'], ['Best', 'num'], ['Avg duration', 'num'], ['Avg deaths / pull', 'num'], ['Median time to first death', 'num']],
        selNights.map(night => { const ps = S.filter(p => p.n === night); const kills = ps.filter(p => p.k).length; const bestV = kills ? 0 : Math.min(...ps.map(p => p.p)); const dur = ps.reduce((a, p) => a + p.d, 0) / ps.length; const fd = ps.filter(p => p.deaths.length).map(p => p.deaths[0].s);
          return `<tr><td>${escH(night)}</td><td>${ps.length}</td><td>${kills}</td><td data-sort='${bestV}'>${kills ? 'KILL' : bestV.toFixed(1) + '%'}</td><td data-sort='${dur}'>${fmtD(dur)}</td><td>${(ps.reduce((a, p) => a + p.deaths.length, 0) / ps.length).toFixed(1)}</td><td data-sort='${median(fd)}'>${fd.length ? fmtD(median(fd)) : '-'}</td></tr>`; }), '', 'Per raid night');
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
    const list = (key, rate) => { const all = Object.entries(aggOutput(S, key, rate === 'DPS' ? 'dps' : 'hps')).sort((a, b) => b[1].total - a[1].total).slice(0, 10); if (!all.length) return `<p class='muted'>No data.</p>`; const top = all[0][1].total || 1;
      return `<div class='tw'><table class='summary'><tbody>${all.map(([name, e]) => `<tr><td class='${cls(e.cl)}'>${escH(name)}</td><td><div class='bar'><span style='width:${(e.total / top * 100).toFixed(1)}%'></span></div></td><td>${fmtN(e.total)}</td><td class='muted'>${fmtN(e.secs ? e.total / e.secs : 0)} ${rate}</td></tr>`).join('')}</tbody></table></div>`; };
    const byAb = {}; S.forEach(p => p.dt.forEach(([, a, , amt]) => { if (!IG.has(norm(a))) byAb[a] = (byAb[a] || 0) + amt; }));
    const items = topN(byAb, 10), top = items.length ? items[0][1] : 1;
    const taken = items.length ? `<div class='tw'><table class='summary'><tbody>${items.map(([a, v]) => `<tr><td>${escH(a)}</td><td><div class='bar'><span style='width:${(v / top * 100).toFixed(1)}%'></span></div></td><td>${fmtN(v)}</td><td class='muted'>${fmtN(v / (secs || 1))} DTPS</td></tr>`).join('')}</tbody></table></div>` : `<p class='muted'>No data.</p>`;
    return `<h2 id='sec_${tab}_sum'>Summary</h2><div class='grid3'><div><h3>Damage done by source</h3>${list('dd', 'DPS')}</div><div><h3>Healing done by source</h3>${list('hd', 'HPS')}</div><div><h3>Damage taken by ability</h3>${taken}</div></div>
      <p class='muted'>Totals across the selected pulls. DPS/HPS = total &divide; time in the pulls that player was in. Parse % (below) is only available for kills - WCL doesn't rank wipes.</p>`;
  }
  function secOutput(S, key, rate, metric, kind, tab) {
    const all = Object.entries(aggOutput(S, key, metric));
    let out = `<h2 id='sec_${tab}_${key}'>${kind === 'damage' ? 'Damage done' : 'Healing done'}</h2>`;
    if (!all.length) return out + `<p class='muted'>No data (WCL tables did not return entries).</p>`;
    const grand = all.reduce((a, [, e]) => a + e.total, 0) || 1, maxP = Math.max(...all.map(([, e]) => e.pulls), 1);
    const groups = { dps: [], tank: [], healer: [] }; all.forEach(([name, e]) => groups[roleOf(e.spec)].push([name, e]));
    const order = kind === 'damage' ? [['dps', 'DPS'], ['tank', 'Tanks'], ['healer', 'Healers']] : [['healer', 'Healers'], ['dps', 'DPS'], ['tank', 'Tanks']];
    out += `<div class='lowgroup'>` + lowLabel(all.filter(([, e]) => e.pulls < 0.25 * maxP).length, maxP);
    out += `<p class='muted'>${rate} = total &divide; time in the pulls the player was in. <b>Active ${rate}</b> divides by the time WCL counts them as active, which stops at death - a big gap between the two means they die early, not that they play badly. <b>Median pull</b> ignores the one dead pull and the one lucky pull; <b>Best pull</b> is the ceiling. Parse (kills only) is the only number that is fair across specs.</p>`;
    order.forEach(([role, label]) => { const rows = groups[role]; if (!rows.length) return;
      const maxRate = Math.max(...rows.map(([, e]) => e.secs ? e.total / e.secs : 0), 1);
      out += `<h3>${label}</h3>` + tbl([['Parse', 'num'], ['Name', 'str'], ['Spec', 'str'], ['Amount', 'num'], [rate, 'num'], [`Active ${rate}`, 'num'], ['Median pull', 'num'], ['Best pull', 'num'], ['Active', 'num'], ['Pulls', 'num']],
        rows.sort((x, y) => (y[1].secs ? y[1].total / y[1].secs : 0) - (x[1].secs ? x[1].total / x[1].secs : 0)).map(([name, e]) => { const r = e.secs ? e.total / e.secs : 0, ar = e.act ? e.total / e.act : 0;
          const pc = e.parses.length ? (() => { const v = e.parses.reduce((a, b) => a + b, 0) / e.parses.length; return `<td data-sort='${v}' class='${parseCls(v)}'>${Math.round(v)}</td>`; })() : `<td data-sort='-1' class='muted'>-</td>`;
          return `<tr${e.pulls < 0.25 * maxP ? " class='lowpart'" : ''} data-player='${escH(e.player)}'>${pc}<td class='${cls(e.cl)}'>${escH(name)}</td><td class='muted'>${escH(e.spec)}</td><td data-sort='${e.total}'>${(e.total / grand * 100).toFixed(1)}% <div class='bar'><span style='width:${(r / maxRate * 100).toFixed(1)}%'></span></div> ${fmtN(e.total)}</td><td data-sort='${r}'><b>${fmtN(r)}</b></td><td data-sort='${ar}'>${fmtN(ar)}</td><td data-sort='${median(e.per)}'>${fmtN(median(e.per))}</td><td data-sort='${Math.max(...e.per)}'>${fmtN(Math.max(...e.per))}</td><td data-sort='${e.secs ? e.act / e.secs : 0}'>${(e.secs ? e.act / e.secs * 100 : 0).toFixed(1)}%</td><td>${e.pulls}</td></tr>`; }), 'output', `${label} ${kind}`); });
    out += `</div>`;
    if (kind === 'damage') {
      const elig = groups.dps.filter(([, e]) => e.pulls >= Math.max(2, 0.25 * maxP) && e.per.length >= 2).sort((x, y) => median(y[1].per) - median(x[1].per));
      if (elig.length >= 2) out += chart(elig.map(([name, e]) => ({ type: 'box', y: e.per, name, boxpoints: 'outliers', marker: { size: 4 }, line: { width: 1.2 } })),
        { title: `${rate} per pull - how consistent is each DPS? (box = middle half of their pulls, line = median)`, yaxis: { title: `${rate} in a pull`, gridcolor: GRID }, showlegend: false, xaxis: { tickangle: -35, gridcolor: GRID }, margin: { l: 45, r: 20, t: 50, b: 90 } }, 420);
      // trend across nights: is the raid getting better or just luckier?
      const nights = [...new Set(S.map(p => p.n))];
      if (nights.length > 1 && elig.length) {
        const traces = elig.slice(0, 10).map(([name, e], i) => ({ type: 'scatter', mode: 'lines+markers', name, line: lineStyle(i), marker: { symbol: symbolOf(i), size: 8 },
          x: nights.map(nn => nn.slice(4)), y: nights.map(nn => e.byNight[nn] ? median(e.byNight[nn]) : null), connectgaps: true,
          hovertext: nights.map(nn => `${name}<br>${nn}<br>${e.byNight[nn] ? fmtN(median(e.byNight[nn])) + ' median ' + rate + ' over ' + e.byNight[nn].length + ' pulls' : 'absent'}`), hoverinfo: 'text' }));
        out += chart(traces, { title: `Median ${rate} per night - top ${traces.length} DPS (click legend entries to hide/show)`, yaxis: { title: rate, gridcolor: GRID }, xaxis: { title: 'Raid night', gridcolor: GRID }, legend: { orientation: 'h', yanchor: 'bottom', y: 1.06, x: 0 }, margin: { l: 45, r: 20, t: 95, b: 45 } }, 380);
      }
    }
    return out;
  }
  function secDeaths(D, S, n, A, hasA, tab) {
    let html = `<h2 id='sec_${tab}_deaths'>Deaths</h2>`;
    if (n === 1) {
      const ds = S[0].deaths;
      html += `<h5>Deaths (${ds.length}) - how the pull unfolded</h5>`;
      if (!ds.length) return html + `<p class='muted'>No deaths.</p>`;
      return html + `<p class='muted'>Defensives (own casts and externals received) are only looked up for the first death of each pull.</p>` + tbl([['#', 'num'], ['Time', 'num'], ['Phase', 'str'], ['Player', 'str'], ['What killed them', 'str'], ['Killing blow', 'str'], ['Dmg last seconds', 'num'], ['Tags', 'str'], ['Defensives', 'str'], ['Last seconds', 'str']],
        ds.map((d, i) => `<tr><td>${i + 1}</td><td data-sort='${d.s}'>${fmtD(d.s)}</td><td class='muted'>${escH(phaseAt(S[0], d.s) || '-')}</td><td class='${cls(d.cl)}'>${escH(d.pl)}</td><td>${escH(d.tc)}</td><td class='muted'>${escH(d.kb)}</td><td data-sort='${d.w}'>${fmtN(d.w)}</td><td>${d.os ? "<span class='tag'>one-shot</span>" : ''}${hasA && d.recap.some(r => A.has(norm(r[1]))) ? " <span class='tag'>avoidable</span>" : ''}</td><td>${defCell(d)}</td><td>${recapHtml(d)}</td></tr>`), 'deathlog', 'Deaths in this pull');
    }
    const withD = S.filter(p => p.deaths.length);
    const firsts = withD.map(p => p.deaths[0]);
    if (!firsts.length) return html + `<p class='muted'>No deaths in these pulls.</p>`;
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
    html += `<p class='muted'>Only the first death of each pull counts here - everyone dies once the wipe is called. "What killed them" is the ability that did the most damage in the final seconds; the killing blow is often just melee.</p>`;
    html += cardsHtml(dc);
    html += `<div class='grid2'><div>${chart([barTrace(topN(byC, 12))], { title: 'First death - what did the damage', yaxis: headroom(topN(byC, 12), 'First deaths') })}</div><div>${chart([barTrace(topN(byP, 12))], { title: 'First death - who', yaxis: headroom(topN(byP, 12), 'First deaths') })}</div></div>`;
    // by phase: first deaths per phase, and per pull that reached the phase
    const order = phaseOrder(S);
    if (order.length > 1) {
      const reached = {}, died = {};
      S.forEach(p => (p.pt || []).forEach(([name]) => { reached[name] = (reached[name] || 0) + 1; }));
      withD.forEach(p => { const ph = phaseAt(p, p.deaths[0].s); if (ph) died[ph] = (died[ph] || 0) + 1; });
      const pairs = order.map(name => [name, died[name] || 0]);
      const rate = order.map(name => reached[name] ? `${pct(died[name] || 0, reached[name])}% of ${reached[name]} pulls that got there` : '');
      html += `<div class='grid2'><div>${chart([Object.assign(barTrace(pairs), { text: pairs.map((p, i) => `${p[1]}${rate[i] ? ' (' + rate[i].split(' of ')[0] + ')' : ''}`) })], { title: 'First death - in which phase (count and % of pulls that reached it)', yaxis: headroom(pairs, 'First deaths') }, 320)}</div>
        <div>${chart([{ type: 'histogram', x: times, xbins: { size: 15 } }], { title: 'When does the first death happen? (15s buckets)', xaxis: { title: 'Seconds into fight', gridcolor: GRID }, yaxis: { title: 'Pulls', gridcolor: GRID } }, 320)}</div></div>`;
    } else {
      html += chart([{ type: 'histogram', x: times, xbins: { size: 15 } }], { title: 'When does the first death happen? (15s buckets)', xaxis: { title: 'Seconds into fight', gridcolor: GRID }, yaxis: { title: 'Pulls', gridcolor: GRID } }, 300);
    }
    const pst = {};
    S.forEach(p => { Object.entries(p.parts).forEach(([name, c]) => { const e = pst[name] || (pst[name] = { cl: c, pulls: 0, fd: 0, causes: {}, av: 0, nodef: 0, withc: 0 }); e.pulls++; });
      if (p.deaths.length) { const d = p.deaths[0]; const e = pst[d.pl] || (pst[d.pl] = { cl: d.cl, pulls: 0, fd: 0, causes: {}, av: 0, nodef: 0, withc: 0 }); e.fd++; e.causes[d.tc] = (e.causes[d.tc] || 0) + 1; if (d.hc) { e.withc++; if (!hadDef(d)) e.nodef++; } }
      if (hasA) p.dt.forEach(([name, a, h]) => { if (A.has(norm(a))) { const e = pst[name] || (pst[name] = { cl: '', pulls: 0, fd: 0, causes: {}, av: 0, nodef: 0, withc: 0 }); e.av += h; } }); });
    const heads = [['Player', 'str'], ['Pulls', 'num'], ['First death', 'num'], ['Started the wipe in % of pulls', 'num']].concat(hasA ? [['Avoidable hits / pull', 'num']] : []).concat(withCasts.length ? [['No defensive before death', 'str']] : []).concat([['What killed them', 'str']]);
    html += `<h5>Players</h5><p class='muted'>"Started the wipe" is first deaths divided by pulls the player was in. Avoidable hits are separate occasions an avoidable ability caught them, per pull.</p>` + tbl(heads,
      Object.entries(pst).sort((x, y) => (y[1].fd / Math.max(y[1].pulls, 1)) - (x[1].fd / Math.max(x[1].pulls, 1))).map(([name, e]) => { const k = Math.max(e.pulls, 1);
        return `<tr><td class='${cls(e.cl)}'>${escH(name)}</td><td>${e.pulls}</td><td>${e.fd}</td><td data-sort='${e.fd / k}'>${pct(e.fd, k)}%</td>${hasA ? `<td data-sort='${e.av / k}'>${(e.av / k).toFixed(1)}</td>` : ''}${withCasts.length ? `<td data-sort='${e.withc ? e.nodef / e.withc : -1}'>${e.withc ? `${e.nodef} of ${e.withc}` : '-'}</td>` : ''}<td>${topN(e.causes, 2).map(([a, c]) => `${escH(a)} (${c})`).join(', ') || '-'}</td></tr>`; }), '', 'Players - first deaths');
    html += `<h5>First death, every pull</h5><p class='muted'>Expand "Last seconds" for the damage breakdown, what the player cast and what they received in that window. "Deaths ≤10 s" = how many more died within ten seconds of the first death.</p>` + tbl([['Pull', 'num'], ['When', 'str'], ['Result', 'num'], ['Phase', 'str'], ['Time', 'num'], ['Player', 'str'], ['What killed them', 'str'], ['Killing blow', 'str'], ['Defensives', 'str'], ['Deaths ≤10 s', 'num'], ['Deaths', 'num'], ['Last seconds', 'str']],
      S.map(p => { const d = p.deaths[0]; const res = `<td data-sort='${p.p}'>${resLabel(p)}</td>`; const w10 = d ? p.deaths.filter(x => x.s > d.s && x.s <= d.s + 10).length : 0; return d
        ? `<tr><td>${p.i}</td><td>${escH(p.n.slice(4))} ${p.t}</td>${res}<td>${escH(phaseAt(p, d.s) || p.ph || '-')}</td><td data-sort='${d.s}'>${fmtD(d.s)}</td><td class='${cls(d.cl)}'>${escH(d.pl)}</td><td>${escH(d.tc)}</td><td class='muted'>${escH(d.kb)}</td><td>${defCell(d)}</td><td>${w10}</td><td>${p.deaths.length}</td><td>${recapHtml(d)}</td></tr>`
        : `<tr><td>${p.i}</td><td>${escH(p.n.slice(4))} ${p.t}</td>${res}<td>${escH(p.ph || '-')}</td><td colspan='6' class='muted'>no deaths</td><td>0</td><td>0</td><td></td></tr>`; }), 'deathlog', 'First death of every pull');
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
    if (!Object.keys(ab).length) return html + `<p class='muted'>No damage-taken data.</p>`;
    const roles = rolesOf(S);
    const tc = [['Damage taken / pull', fmtN(totalDmg / n)], ['Distinct abilities', Object.keys(ab).length]];
    if (IG.size) tc.push(['Ignored abilities', IG.size]);
    if (hasA) tc.push(['Avoidable damage / pull', fmtN(avoidDmg / n)], ['Avoidable share', totalDmg ? pct(avoidDmg, totalDmg) + '%' : '-'], ['Avoidable hits / pull', (avoidHits / n).toFixed(1)]);
    html += cardsHtml(tc);
    const topAmt = topN(Object.fromEntries(Object.entries(ab).map(([a, e]) => [a, e.amt])), 15);
    const topHits = topN(Object.fromEntries(Object.entries(ab).filter(([, e]) => e.h > 0).map(([a, e]) => [a, e.h])), 15);
    const col = pairs => pairs.map(([a]) => A.has(norm(a)) ? '#d4ad2f' : '#4a6fa5');
    const amtPairs = topAmt.map(([a, v]) => [a, v / n]), hitPairs = topHits.map(([a, v]) => [a, +(v / n).toFixed(1)]);
    html += `<div class='grid2'><div>${chart([barTrace(amtPairs, col(topAmt))], { title: 'Damage taken per pull - by ability' + (hasA ? ' (gold = avoidable)' : ''), yaxis: headroom(amtPairs, 'Damage / pull') })}</div>
      <div>${hitPairs.length ? chart([barTrace(hitPairs, col(topHits))], { title: 'Hits per pull - by ability', yaxis: headroom(hitPairs, 'Hits / pull') }) : `<p class='muted'>No hits in this phase.</p>`}</div></div>`;
    const heatAb = (hasA ? topHits.filter(([a]) => A.has(norm(a))) : topHits).slice(0, 12).map(([a]) => a);
    const plSorted = Object.entries(pl).sort((x, y) => ((hasA ? y[1].av : y[1].hits) / Math.max(y[1].pulls, 1)) - ((hasA ? x[1].av : x[1].hits) / Math.max(x[1].pulls, 1)));
    if (heatAb.length && plSorted.length) {
      const z = plSorted.map(([name, e]) => heatAb.map(a => +(((abPl[a] || {})[name] || 0) / Math.max(e.pulls, 1)).toFixed(1)));
      html += chart([heatTrace(z, heatAb, plSorted.map(([name]) => name), 'hits / pull')],
        { title: hasA ? 'Avoidable hits per pull - who is getting hit by what' : 'Hits per pull - who is getting hit by what (top abilities)', yaxis: { autorange: 'reversed' } }, Math.max(320, 22 * plSorted.length + 120));
    }
    if (avoidTimes.length > 1) html += chart([{ type: 'histogram', x: avoidTimes, xbins: { size: 10 } }], { title: 'When do avoidable hits land? (all selected pulls, 10s buckets)', xaxis: { title: 'Seconds into fight', gridcolor: GRID }, yaxis: { title: 'Avoidable hits', gridcolor: GRID } }, 300);
    html += `<p class='muted'>"Hits" = separate occasions the ability caught a player. A direct hit, the DoT it applies, and a pulsing puddle you stood in for 6 seconds each count once - WCL would show the puddle as 6 hits.</p>`;
    html += `<h5>Players</h5><p class='muted'>Normalised by pulls participated. Sort by "Avoidable hits / pull" to find who needs a word. Tanks usually top this list because they stand where things land - compare tanks with tanks.</p><label class='filter'><input type='checkbox' class='hideTanks'> Hide tanks</label>`;
    html += tbl([['Player', 'str'], ['Role', 'str'], ['Pulls', 'num']].concat(hasA ? [['Avoidable hits / pull', 'num'], ['Avoidable dmg / pull', 'num']] : []).concat([['All hits / pull', 'num'], ['All dmg / pull', 'num']]),
      plSorted.map(([name, e]) => { const k = Math.max(e.pulls, 1); const role = roles[name] || ''; return `<tr class='role-${role}'><td class='${cls(e.cl)}'>${escH(name)}</td><td class='muted'>${escH(roleLabel(S, name) || role)}</td><td>${e.pulls}</td>${hasA ? `<td data-sort='${e.av / k}'>${(e.av / k).toFixed(1)}</td><td data-sort='${e.avd / k}'>${fmtN(e.avd / k)}</td>` : ''}<td data-sort='${e.hits / k}'>${(e.hits / k).toFixed(1)}</td><td data-sort='${e.dmg / k}'>${fmtN(e.dmg / k)}</td></tr>`; }), '', 'Damage taken per player');
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
    const rows = Object.entries(ab).sort((x, y) => y[1].amt - x[1].amt).map(([a, e]) => { const [pat, tip] = pattern(a); const isA = A.has(norm(a)); let warn = ''; if (isA && (pat === 'raid-wide' || pat === 'tank')) { warn = ' &#9888;'; review.push(`${a} - ${pat}`); }
      return `<tr><td>${escH(a)}</td><td class='muted'>${(D.src[a] || []).slice(0, 2).map(escH).join(', ')}</td><td class='pat-${pat}' title='${escH(tip)}'>${pat}</td><td class='avoid'>${isA ? '&#10003;' : ''}${warn}</td><td data-sort='${e.h}'>${e.h}</td><td data-sort='${e.h / n}'>${(e.h / n).toFixed(1)}</td><td data-sort='${e.amt}'>${fmtN(e.amt)}</td><td data-sort='${e.amt / n}'>${fmtN(e.amt / n)}</td><td data-sort='${e.amt / Math.max(e.h, 1)}'>${fmtN(e.amt / Math.max(e.h, 1))}</td><td>${topN(abPl[a] || {}, 3).map(([p, h]) => `${escH(p)} (${h})`).join(', ')}</td></tr>`; });
    html += `<h5>Abilities</h5>`;
    if (review.length && phaseIdx < 0) html += `<p class='note'>&#9888; ${review.length} avoidable-listed abilit${review.length === 1 ? 'y' : 'ies'} hit the raid like an unavoidable mechanic (${escH(review.join(', '))}). Hover "Who gets hit" for the reasoning. If these really are fail-triggered raid damage keep them; otherwise remove them from avoidable.json, because they are inflating every avoidable number on this tab.</p>`;
    html += `<p class='muted'>"Who gets hit": <b>raid-wide</b> = everyone about equally (intended damage or a whole-raid punishment); <b>tank</b> = almost only the two tanks; <b>few</b> = concentrated on one or two players (a soak/assignment, or a repeat offender); <b>spread</b> = uneven across the raid - the pattern of genuinely dodgeable damage.</p>`;
    html += tbl([['Ability', 'str'], ['Cast by', 'str'], ['Who gets hit', 'str'], ['Avoidable', 'str'], ['Hits', 'num'], ['Hits / pull', 'num'], ['Total dmg', 'num'], ['Dmg / pull', 'num'], ['Avg per hit', 'num'], ['Hit most', 'str']], rows, '', 'Damage taken per ability');
    return html;
  }
  function secPrep(D, S, n, tab) {
    const cats = D.cats || [], ucats = D.usecats || []; if (!cats.length || !S.some(p => Object.keys(p.cons || {}).length)) return '';
    const per = {}; let pp = 0; const catTot = cats.map(() => 0), useTot = ucats.map(() => 0);
    const mk = (name, p) => per[name] || (per[name] = { cl: p.parts[name] || '', pulls: 0, have: cats.map(() => 0), use: ucats.map(() => 0) });
    S.forEach(p => { Object.entries(p.cons || {}).forEach(([name, flags]) => { const e = mk(name, p); e.pulls++; pp++; flags.forEach((f, i) => { if (f) { e.have[i]++; catTot[i]++; } }); });
      Object.entries(p.use || {}).forEach(([name, counts]) => { const e = mk(name, p); counts.forEach((k, i) => { e.use[i] += k; useTot[i] += k; }); }); });
    const label = c => ({ flask: 'Flask', food: 'Food', vantus: 'Vantus rune', rune: 'Augment rune', prepot: 'Pre-pot', combat_potion: 'Combat potions', healing_potion: 'Healing potions', healthstone: 'Healthstones', mana_potion: 'Mana potions' })[c] || c;
    let html = `<h2 id='sec_${tab}_prep'>Preparation &amp; consumables</h2><p class='muted'>Flask, food and runes = buffs active on each player when the pull started (WCL combatant info). Pre-pot = a combat potion cast in the 5 s before the pull. The potion and Healthstone columns count uses <em>during</em> the pull (the pre-pot is not included in combat potions).</p>`;
    html += cardsHtml(cats.map((c, i) => [`${label(c)} at pull start`, `${pct(catTot[i], pp)}% <span class='vs'>of ${pp} player-pulls</span>`])
      .concat(ucats.map((c, i) => [`${label(c)} / pull`, `${(useTot[i] / n).toFixed(1)} <span class='vs'>${useTot[i]} in ${n} pull${n === 1 ? '' : 's'}</span>`])));
    const cell = (have, pulls) => { const c = have === pulls ? 'prep-ok' : have ? 'prep-part' : 'prep-fail'; return `<td class='${c}' data-sort='${pulls ? have / pulls : 0}'>${have}/${pulls}</td>`; };
    html += tbl([['Player', 'str'], ['Pulls', 'num']].concat(cats.map(c => [label(c), 'num'])).concat(ucats.map(c => [label(c), 'num'])).concat([['Missing (flask+food+pre-pot)', 'num']]),
      Object.entries(per).map(([name, e]) => { const core = cats.map((c, i) => ['flask', 'food', 'prepot'].includes(c) ? e.pulls - e.have[i] : 0).reduce((a, b) => a + b, 0);
        return [core, `<tr><td class='${cls(e.cl)}'>${escH(name)}</td><td>${e.pulls}</td>${cats.map((_, i) => cell(e.have[i], e.pulls)).join('')}${ucats.map((_, i) => `<td data-sort='${e.use[i]}'>${e.use[i]}${e.pulls > 1 ? ` <span class='muted'>(${(e.use[i] / e.pulls).toFixed(1)}/pull)</span>` : ''}</td>`).join('')}<td data-sort='${core}'>${core}</td></tr>`]; })
        .sort((x, y) => y[0] - x[0]).map(x => x[1]), '', 'Consumables per player');
    return html;
  }
  function secUtility(S, n, tab) {
    if (!S.some(p => p.hx)) return '';
    const per = {}; const roles = rolesOf(S);
    S.forEach(p => { if (!p.hx) return; Object.entries(p.parts).forEach(([name, c]) => { const e = per[name] || (per[name] = { cl: c, pulls: 0, ir: 0, ds: 0 }); e.pulls++; e.ir += (p.ir || {})[name] || 0; e.ds += (p.ds || {})[name] || 0; }); });
    const totI = Object.values(per).reduce((a, e) => a + e.ir, 0), totD = Object.values(per).reduce((a, e) => a + e.ds, 0);
    let html = `<h2 id='sec_${tab}_util'>Interrupts &amp; dispels</h2>`;
    html += cardsHtml([['Interrupts / pull', (totI / n).toFixed(1)], ['Dispels / pull', (totD / n).toFixed(1)]]);
    html += tbl([['Player', 'str'], ['Role', 'str'], ['Pulls', 'num'], ['Interrupts', 'num'], ['Interrupts / pull', 'num'], ['Dispels', 'num'], ['Dispels / pull', 'num']],
      Object.entries(per).sort((x, y) => (y[1].ir + y[1].ds) - (x[1].ir + x[1].ds)).map(([name, e]) => { const k = Math.max(e.pulls, 1); return `<tr><td class='${cls(e.cl)}'>${escH(name)}</td><td class='muted'>${escH(roles[name] || '')}</td><td>${e.pulls}</td><td>${e.ir}</td><td data-sort='${e.ir / k}'>${(e.ir / k).toFixed(2)}</td><td>${e.ds}</td><td data-sort='${e.ds / k}'>${(e.ds / k).toFixed(2)}</td></tr>`; }), '', 'Interrupts and dispels per player');
    html += `<p class='muted'>Counts from WCL's Interrupts and Dispels tables. Whether a number is good depends on the assignment - use it to check that assigned players actually did the job.</p>`;
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
    const vs = (val, med, fmt, lowerIsBetter = true) => { if (!isFinite(med) || med === 0) return ''; const r = val / med; const good = lowerIsBetter ? r <= 1 : r >= 1; return `<span class='vs' style='color:${good ? '#8ce0a8' : '#e08a8a'}'>raid median ${fmt(med)} (${r >= 1 ? '+' : ''}${Math.round((r - 1) * 100)}%, ${good ? 'better' : 'worse'})</span>`; };
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
    let html = `<div class='focus'>${cardsHtml(cards)}`;
    if (flex) html += `<p class='muted'>${escH(P)} played more than one role in these pulls (${Object.entries(byRole).map(([r, e]) => `${r}: ${e.pulls}`).join(', ')}). Damage/healing tables below list each spec separately; deaths and avoidable damage are across all roles.</p>`;
    const mine = Object.entries(me.byAb).sort((x, y) => y[1].amt - x[1].amt).slice(0, 12);
    if (mine.length) {
      const x = mine.map(([a]) => a);
      html += chart([{ type: 'bar', name: P, x, y: mine.map(([, e]) => +(e.h / k).toFixed(2)), marker: { color: x.map(a => A.has(norm(a)) ? '#d4ad2f' : '#7aa2e3') } },
                     { type: 'bar', name: 'raid average', x, y: mine.map(([a]) => +((raidAb[a] || 0) / Math.max(raidPP, 1)).toFixed(2)), marker: { color: '#3a3f4a' } }],
                    { title: `${P}: hits per pull by ability vs the raid average${hasA ? ' (gold = avoidable)' : ''}`, barmode: 'group', yaxis: { title: 'Hits / pull', gridcolor: GRID } }, 340);
    }
    if (me.deaths.length) {
      html += `<h5>${escH(P)}'s deaths (${me.deaths.length})</h5>` + tbl([['Pull', 'num'], ['When', 'str'], ['Result', 'num'], ['Time', 'num'], ['Phase', 'str'], ['Tags', 'str'], ['What killed them', 'str'], ['Killing blow', 'str'], ['Defensives', 'str'], ['Last seconds', 'str']],
        me.deaths.map(d => `<tr><td>${d.pull}</td><td>${escH(d.night.slice(4))} ${d.t}</td><td>${d.res}</td><td data-sort='${d.s}'>${fmtD(d.s)}</td><td class='muted'>${escH(d.phase || '-')}</td><td>${d.first ? "<span class='tag'>first</span>" : ''}${d.os ? " <span class='tag'>one-shot</span>" : ''}</td><td>${escH(d.tc)}</td><td class='muted'>${escH(d.kb)}</td><td>${defCell(d)}</td><td>${recapHtml(d)}</td></tr>`), 'deathlog', `${P}'s deaths`);
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
    if (!S.length) { const why = P ? `${escH(P)} was not in any of the selected pulls.` : `No pulls on this boss in the selected night.`;
      panel.innerHTML = `${closeBtn}<h4>${escH(P || G.night)}</h4><p class='muted'>${why}</p>`;
      panel.querySelector('.close')?.addEventListener('click', clearAll); return; }
    const A = D.avoidSet, IG = D.ignoreSet, hasA = A.size > 0;
    const n = S.length, secs = S.reduce((a, p) => a + p.d, 0);
    const kills = S.filter(p => p.k).length, wipes = S.filter(p => !p.k);
    const best = kills ? 'KILL' : (wipes.length ? Math.min(...wipes.map(p => p.p)).toFixed(1) + '% left' : '-');
    const selNights = [...new Set(S.map(p => p.n))];

    let title = n === 1
      ? `Pull #${S[0].i} &middot; ${escH(S[0].n)} ${S[0].t} &middot; ${S[0].k ? 'KILL' : S[0].p.toFixed(1) + '% left'}${!S[0].k && Math.abs(S[0].fp - S[0].p) > 1 ? ` (fight ${S[0].fp.toFixed(1)}%)` : ''} &middot; ${fmtD(S[0].d)}${S[0].ph ? ' &middot; ended in ' + escH(S[0].ph) : ''}`
      : (selNights.length === 1 && S.length === D.pulls.filter(p => p.n === selNights[0]).length ? `${escH(selNights[0])} &middot; ${n} pulls`
        : (G.ntype && !G.night && !st.sel.size ? `${G.ntype === 'open' ? 'Open' : 'Main'} nights &middot; ${n} pulls` : filtered ? `${n} pulls selected` : `All pulls &middot; ${n}`));
    const wcl = n === 1 ? `<a class='wcl' target='_blank' rel='noopener' href='https://www.warcraftlogs.com/reports/${encodeURIComponent(S[0].code)}#fight=${S[0].fid}'>open on WCL &#8599;</a>` : '';
    if (P) title = `<span class='${cls(D.pulls.find(p => P in p.parts).parts[P])}'>${escH(P)}</span> &middot; ${n} of ${base.length} pulls` + (st.sel.size ? ` in selection` : '') + (n === 1 ? ` &middot; ${title}` : '');
    const secs_ = [['prog', 'Progression'], ['sum', 'Summary'], ['dd', 'Damage done'], ['hd', 'Healing done'], ['deaths', 'Deaths'], ['dt', 'Damage taken'], ['prep', 'Preparation'], ['util', 'Interrupts & dispels']];
    let html = `${closeBtn}<h4>${title}${wcl}</h4>`;
    if (P) html += playerFocus(D, S, P, A, IG, hasA, n, secs);
    if (n > 1) html += cardsHtml([['Pulls', n], ['Kills', kills], ['Best pull', best], ['Avg duration', fmtD(secs / n)], ['Time in combat', fmtD(secs)], ['Raid nights', selNights.length]]) + secPhaseStrip(S, n);
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
    panel.querySelector('.close')?.addEventListener('click', clearAll);
    $$('.phasebtn', panel).forEach(b => b.addEventListener('click', () => { st.phase = +b.dataset.phase; renderSelection(tab); document.getElementById(`sec_${tab}_dt`)?.scrollIntoView({ behavior: SCROLL, block: 'start' }); }));
    if (P) $$('table.sortable tbody tr', panel).forEach(tr => { const td = tr.children[0]; if (tr.dataset.player === P || (td && td.textContent.trim() === P)) tr.classList.add('me'); });
    wireSort(panel); wireToggles(panel);
    drawCharts();
    $$('.chart', panel).forEach(el => { if (el.on) el.on('plotly_click', ev => onChartClick(tab, ev)); });
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
  let playersDirty = false;

  function applyGlobal() {
    G.night = gNight.value; G.player = gPlayer.value; G.ntype = gType ? gType.value : '';
    if (gType) [...gNight.options].forEach(o => { if (!o.value) return; const isOpen = o.value.endsWith(' open'); o.hidden = !!G.ntype && ((G.ntype === 'open') !== isOpen); });
    if (G.night && G.ntype && ((G.ntype === 'open') !== G.night.endsWith(' open'))) { gNight.value = ''; G.night = ''; }
    toolbar.classList.toggle('active', !!(G.night || G.player || G.ntype));
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
      html += `<h4>${escH(G.player)}${G.night ? ' &middot; ' + escH(G.night) : ''} &middot; per boss</h4>`;
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
      html += rows.length ? tbl([['Boss', 'str'], ['Pulls', 'num'], ['First death', 'num'], ['Started the wipe', 'num'], ['Deaths', 'num'], ['Avoidable hits / pull', 'num'], ['Dmg taken / pull', 'num'], ['DPS', 'num'], ['HPS', 'num']], rows, '', `${G.player} per boss`)
                          : `<p class='muted'>${escH(G.player)} has no pulls in this selection.</p>`;
      html += `<p class='muted'>Click a boss name to open that tab with the same filters.</p>`;
    } else {
      html += `<h4>${escH(G.night || (G.ntype === 'open' ? 'Open nights' : 'Main nights'))} &middot; all bosses</h4>`;
      const o = {}; let anyA = false;
      bossTabs.forEach(tab => { const st = loadTab(tab); if (!st) return; const D = st.data, A = D.avoidSet, IG = D.ignoreSet; anyA = anyA || A.size > 0;
        D.pulls.filter(nightOk).forEach(p => {
          Object.entries(p.parts).forEach(([name, c]) => { const e = o[name] || (o[name] = { cl: c, pulls: 0, bosses: new Set(), fd: 0, av: 0, causes: {} }); e.pulls++; e.bosses.add(tab); });
          if (p.deaths.length) { const d = p.deaths[0]; const e = o[d.pl] || (o[d.pl] = { cl: d.cl, pulls: 0, bosses: new Set(), fd: 0, av: 0, causes: {} }); e.fd++; e.causes[d.tc] = (e.causes[d.tc] || 0) + 1; }
          p.dt.forEach(([name, a, h]) => { if (A.has(norm(a)) && !IG.has(norm(a))) { const e = o[name] || (o[name] = { cl: '', pulls: 0, bosses: new Set(), fd: 0, av: 0, causes: {} }); e.av += h; } }); }); });
      const maxP = Math.max(...Object.values(o).map(e => e.pulls), 1);
      html += `<div class='lowgroup'>` + lowLabel(Object.values(o).filter(e => e.pulls < 0.25 * maxP).length, maxP) +
        tbl([['Player', 'str'], ['Class', 'str'], ['Pulls', 'num'], ['Bosses', 'num'], ['First death', 'num'], ['Started the wipe in % of pulls', 'num']].concat(anyA ? [['Avoidable hits / pull', 'num']] : []).concat([['What killed them', 'str']]),
          Object.entries(o).sort((x, y) => (y[1].fd / Math.max(y[1].pulls, 1)) - (x[1].fd / Math.max(x[1].pulls, 1))).map(([name, e]) => { const k = Math.max(e.pulls, 1);
            return `<tr${e.pulls < 0.25 * maxP ? " class='lowpart'" : ''}><td class='${cls(e.cl)}'>${escH(name)}</td><td>${escH(e.cl)}</td><td>${e.pulls}</td><td>${e.bosses.size}</td><td>${e.fd}</td><td data-sort='${e.fd / k}'>${pct(e.fd, k)}%</td>${anyA ? `<td data-sort='${e.av / k}'>${(e.av / k).toFixed(1)}</td>` : ''}<td>${topN(e.causes, 2).map(([a, c]) => `${escH(a)} (${c})`).join(', ') || '-'}</td></tr>`; }), '', 'Players in this selection') + `</div>`;
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
    if (btn.dataset.diff && btn.classList.contains('diff-hidden')) setDiff(btn.dataset.diff);
    activateTab(wanted, false);
    const sec = wantedSec && document.getElementById(`sec_${wanted}_${wantedSec}`);
    if (sec) sec.scrollIntoView({ behavior: 'auto', block: 'start' });
  } else renderIfDirty(activeTab());   // boss tabs render lazily when opened
  document.body.dataset.dashReady = '1';
})().catch(dashShowError);
