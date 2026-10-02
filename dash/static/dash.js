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
  // role spec tokens come from specs.py via <script id='cfg'> (one table for Python and JS)
  const CFG = JSON.parse(document.getElementById('cfg').textContent);
  const TANKS = new Set(CFG.tanks || []), HEALERS = new Set(CFG.healers || []), SUPPORT = new Set(CFG.support || []);
  const roleOf = spec => TANKS.has(spec) ? 'tank' : HEALERS.has(spec) ? 'healer' : 'dps';
  const ROLE_LABEL = { dps: 'DPS', healer: 'Healer', tank: 'Tank' };
  const playerCell = (name, cl, role, spec) => `<span class='player ${cls(cl)}'>${escH(name)}</span>${role ? `<span class='role'>${escH(ROLE_LABEL[role] || role)}</span>` : ''}${spec ? `<br><span class='spec'>${escH(spec)}${cl && !String(spec).endsWith(cl) ? ' ' + escH(clsLabel(cl)) : ''}</span>` : ''}`;
  // --- table helpers (quickjs-testable) ---
  // WCL class ids are CamelCase ('DemonHunter'); the spec line shows them as words ('Demon Hunter')
  const clsLabel = c => String(c).replace(/([a-z])([A-Z])/g, '$1 $2');
  const escH = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, '&#39;').replace(/"/g, '&quot;');
  // heads are [label, kind] or [label, kind, full]: `full` (e.g. the whole boss title behind a short head) becomes the
  // header's title tooltip and the sort button's aria-label; without it the label is used as before
  const th = h => { const cls = h[1] === 'num' ? " class='right'" : '', full = h[2] || h[0], tip = h[2] ? ` title='${escH(h[2])}'` : ''; return h[1] === 'none' ? `<th scope='col' data-type='none'${cls}${tip}>${escH(h[0])}</th>` : `<th scope='col' data-type='${h[1]}'${cls}${tip}><button type='button' aria-label='Sort by ${escH(full)}'>${escH(h[0])}</button></th>`; };
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
  // Who pulled: pulls carry pb = [label, ability, offset_ms, 'd'|'c'] or null (unknown). Share is % of all given pulls
  // (one decimal), so the player rows plus the unknown count add up to the pull count. Order: pulls desc, then name.
  const byPullsThenName = (a, b) => b.pulls - a.pulls || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
  const share1 = (a, b) => b ? Math.round(a / b * 1000) / 10 : 0;
  function pullerRows(pulls) {
    const per = {}; let unknown = 0;
    (pulls || []).forEach(p => {
      const pb = p.pb; if (!pb || !pb[0]) { unknown++; return; }
      const e = per[pb[0]] || (per[pb[0]] = { name: pb[0], cl: (p.parts || {})[pb[0]] || '', pulls: 0, ab: {} });
      e.pulls++; if (!e.cl && p.parts && p.parts[pb[0]]) e.cl = p.parts[pb[0]];
      if (pb[1]) e.ab[pb[1]] = (e.ab[pb[1]] || 0) + 1;
    });
    const total = (pulls || []).length;
    const rows = Object.values(per).map(e => {
      const ab = Object.entries(e.ab).sort((x, y) => y[1] - x[1] || (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0))[0];
      return { name: e.name, cl: e.cl, pulls: e.pulls, share: share1(e.pulls, total), opener: ab ? ab[0] : '', openerCount: ab ? ab[1] : 0 };
    }).sort(byPullsThenName);
    return { rows, unknown, unknownShare: share1(unknown, total), total };
  }
  // players x boss tabs: lists = [{key, label, pulls}] in tab order; columns = the lists with at least one pull,
  // rows = every participant of the counted pulls (union of p.parts keys) with a count per column + total (0 for players
  // who never pulled), class = the one seen in most of their pulls (tie -> first seen); unknown = pulls without data;
  // participants / pullers = row count / players with at least one pull (caption)
  function pullerMatrix(lists) {
    const cols = [], per = {}, unknown = { counts: {}, total: 0 }; let total = 0;
    const row = n => per[n] || (per[n] = { name: n, cls: {}, counts: {}, pulls: 0 });
    (lists || []).forEach(l => {
      const ps = l.pulls || []; if (!ps.length) return;
      cols.push({ key: l.key, label: l.label }); total += ps.length;
      ps.forEach(p => {
        Object.entries(p.parts || {}).forEach(([n, c]) => { const e = row(n); if (c) e.cls[c] = (e.cls[c] || 0) + 1; });
        const pb = p.pb; if (!pb || !pb[0]) { unknown.counts[l.key] = (unknown.counts[l.key] || 0) + 1; unknown.total++; return; }
        const e = row(pb[0]); e.counts[l.key] = (e.counts[l.key] || 0) + 1; e.pulls++;
      });
    });
    // insertion order of e.cls is first-seen order, so the stable reduce keeps the first class on a tie
    const topCls = o => Object.entries(o).reduce((b, x) => x[1] > b[1] ? x : b, ['', 0])[0];
    const rows = Object.values(per).sort(byPullsThenName).map(e => ({ name: e.name, cl: topCls(e.cls), counts: e.counts, total: e.pulls }));
    return { cols, rows, unknown, total, participants: rows.length, pullers: rows.filter(e => e.total > 0).length };
  }
  // compact boss column head: "Nek'zali the Soulcoiler (Heroic)" -> "Nek'zali H". words = 1: first word of the name
  // (leading "The " dropped, apostrophes kept, capped at 10 characters); words = 2 adds the next word that is not
  // the/of/and/a, abbreviated to "X." when the head would get long (full = true keeps it whole, capped at 10).
  // Difficulty suffix N / H / M (LFR -> L).
  const SHORT_SKIP = new Set(['the', 'of', 'and', 'a']);
  const capWord = (w, n) => w.length > n ? w.slice(0, n - 1) + '.' : w;
  function shortBossHead(title, words, full) {
    const m = /^(.*?)\s*\(([^()]*)\)\s*$/.exec(String(title || ''));
    const name = (m ? m[1] : String(title || '')).trim().replace(/^the\s+/i, ''), diff = m ? m[2].trim() : '';
    const suffix = !diff ? '' : /^lfr$|looking for raid/i.test(diff) ? 'L' : diff[0].toUpperCase();
    const ws = name.split(/\s+/).filter(Boolean);
    let head = capWord(ws[0] || name, 10);
    if (words === 2) {
      const next = ws.slice(1).find(w => !SHORT_SKIP.has(w.toLowerCase()));
      if (next) head += ' ' + (!full && head.length + 1 + next.length > 14 ? next[0] + '.' : capWord(next, 10));
    }
    return suffix ? `${head} ${suffix}` : head;
  }
  // short heads for a list of titles, collision-aware (deterministic, order-independent): a head shared by several
  // titles is replaced for those titles by the next longer form - two words, two unabbreviated words, the full title
  function shortBossHeads(titles) {
    const ts = titles || [], count = a => a.reduce((o, h) => (o[h] = (o[h] || 0) + 1, o), {});
    const forms = [t => shortBossHead(t, 2), t => shortBossHead(t, 2, true), t => String(t)];
    let heads = ts.map(t => shortBossHead(t, 1));
    forms.forEach(f => { const c = count(heads); heads = heads.map((h, i) => c[h] > 1 ? f(ts[i]) : h); });
    return heads;
  }
  // matrix headers: Player, Total (visible without scrolling), then the boss columns in tab order with short heads
  // (full tab title as third element -> th title + sort-button aria-label)
  const pullerMatrixHeads = cols => { const cs = cols || [], sh = shortBossHeads(cs.map(c => c.label)); return [['Player', 'str'], ['Total', 'num']].concat(cs.map((c, i) => [sh[i], 'num', c.label])); };
  // every pull of every boss tab: lists = [{key, label, pulls}] in tab order -> [{tab, label, p}], chronological by the
  // pull's absolute start (payload key a, epoch ms); ties by tab order, then pull number p.i
  function allPullRows(lists) {
    const out = [];
    (lists || []).forEach((l, ti) => (l.pulls || []).forEach(p => out.push({ tab: l.key, label: l.label, p, ti })));
    out.sort((x, y) => ((x.p.a || 0) - (y.p.a || 0)) || (x.ti - y.ti) || ((x.p.i || 0) - (y.p.i || 0)));
    return out.map(r => ({ tab: r.tab, label: r.label, p: r.p }));
  }
  // Players deep link: '#tabPlayers?player=<label>'. encodeURIComponent keeps ' ( ) ! * ~ literal; ' and ( ) are
  // encoded too so pasted links survive chat clients (Discord). Labels may be 'Name-Realm' or contain spaces/unicode.
  const playerHash = name => '#tabPlayers' + (name ? '?player=' + encodeURIComponent(String(name)).replace(/['()!*~]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase()) : '');
  // the player label from a hash ('#tab?player=X', 'tab?a=1&player=X' or '?player=X'), null when there is none;
  // '+' reads as a space (form encoding), a malformed %-escape keeps the raw text
  function parsePlayerHash(hash) {
    const h = String(hash || ''), q = h.indexOf('?'); if (q < 0) return null;
    for (const kv of h.slice(q + 1).split('&')) {
      const eq = kv.indexOf('='); if ((eq < 0 ? kv : kv.slice(0, eq)) !== 'player' || eq < 0) continue;
      const raw = kv.slice(eq + 1).replace(/\+/g, ' ');
      let v; try { v = decodeURIComponent(raw); } catch (_) { v = raw; }
      return v.trim() ? v : null;
    }
    return null;
  }
  // KPI tiles: items [label, value html, extra class]
  const kpisHtml = (items, extra) => `<dl class='kpis${extra ? ' ' + extra : ''}'>${items.map(([l, v, c]) => `<div class='kpi${c ? ' ' + c : ''}'><dt>${escH(l)}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
  // --- end table helpers ---
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
  // --- card components (quickjs-testable) ---
  // Pure HTML/SVG string builders for the player card (no DOM). They use escH (table helpers) and TOK; status is a
  // CSS class plus a glyph and a word, so colour is never the only signal. Charts with < 4 values fall back to nothing
  // (sparkline) or a sentence (small multiples), like chart()'s skip rule.
  const cardNum = v => typeof v === 'number' && isFinite(v);
  const cardR1 = v => Math.round(v * 10) / 10;
  const cardFmt = f => typeof f === 'function' ? f : (v => String(cardR1(v)));
  const cardMedian = arr => { const s = arr.filter(cardNum).sort((a, b) => a - b), n = s.length; return !n ? null : n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };
  const cardPct = (v, max) => Math.max(0, Math.min(100, max > 0 ? v / max * 100 : 0)).toFixed(1);
  // values: numbers oldest first (non-numbers skipped); opts {w = 96, h = 28, label, fmt}. '' below 4 values.
  // The last point is marked; <title> + aria-label carry first -> last in words.
  function sparkline(values, opts) {
    const o = opts || {}, vs = (values || []).filter(cardNum);
    if (vs.length < 4) return '';
    const w = o.w || 96, h = o.h || 28, pad = 3, f = cardFmt(o.fmt);
    const lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1;
    const x = i => cardR1(pad + i / (vs.length - 1) * (w - 2 * pad));
    const y = v => cardR1(hi === lo ? h / 2 : h - pad - (v - lo) / span * (h - 2 * pad));
    const pts = vs.map((v, i) => `${x(i)},${y(v)}`).join(' '), last = vs.length - 1;
    const title = `${o.label ? o.label + ': ' : ''}${vs.length} nights, from ${f(vs[0])} to ${f(vs[last])} (range ${f(lo)} to ${f(hi)})`;
    return `<svg class='spark' viewBox='0 0 ${w} ${h}' width='${w}' height='${h}' role='img' aria-label='${escH(title)}'><title>${escH(title)}</title>` +
      `<polyline points='${pts}' fill='none' stroke='${TOK.series[0]}' stroke-width='1.5' stroke-linejoin='round' stroke-linecap='round'/>` +
      `<circle cx='${x(last)}' cy='${y(vs[last])}' r='2.5' fill='${TOK.ink}'/></svg>`;
  }
  // bullet bar (<= 24 px): value as the bar, target tick (role median), second tick (own median). labels:
  // {name, target = 'role median', own = 'your median', fmt}. Every mark is also written out as text in the legend;
  // null target / own drop that tick and its legend entry. max defaults to 110 % of the largest number given.
  function bulletBar(value, target, own, max, labels) {
    const l = labels || {}, f = cardFmt(l.fmt), nums = [value, target, own].filter(cardNum);
    if (!cardNum(value)) return '';
    const top = cardNum(max) && max > 0 ? max : Math.max(...nums) * 1.1 || 1;
    const tick = (v, c) => cardNum(v) ? `<i class='bullet-tick ${c}' style='left:${cardPct(v, top)}%'></i>` : '';
    const item = (c, name, v) => cardNum(v) ? `<li><span class='key ${c}' aria-hidden='true'></span>${escH(name)}: <strong>${f(v)}</strong></li>` : '';
    return `<div class='bullet'><div class='bullet-track' aria-hidden='true'><i class='bullet-fill' style='width:${cardPct(value, top)}%'></i>${tick(target, 'target')}${tick(own, 'own')}</div>` +
      `<ul class='bullet-legend'>${item('fill', l.name || 'This period', value)}${item('target', l.target || 'role median', target)}${item('own', l.own || 'your median', own)}</ul></div>`;
  }
  // status levels shared by box rows and status text: [glyph (decorative), word (screen readers + title)]
  const CARD_LEVEL = { good: ['&#10003;', 'Good'], watch: ['!', 'Watch'], note: ['&#8226;', 'Note'] };
  // items: [{level: 'good'|'watch'|'note', text (visible, optional), title (tooltip, optional), attrs {data-*: value}}]
  // -> a row of real buttons; an unknown level is shown as note
  function boxRow(items) {
    const box = (it, i) => {
      const lv = CARD_LEVEL[it.level] ? it.level : 'note', [glyph, word] = CARD_LEVEL[lv];
      const tip = it.title || (it.text ? `${word}: ${it.text}` : word);
      const attrs = Object.entries(it.attrs || {}).filter(([k, v]) => /^data-[a-z0-9-]+$/.test(k) && v != null).map(([k, v]) => ` ${k}='${escH(v)}'`).join('');
      return `<button type='button' class='box lvl-${lv}' title='${escH(tip)}' data-i='${i}'${attrs}><span class='glyph' aria-hidden='true'>${glyph}</span><span class='sr-only'>${word}</span>${it.text ? `<span class='box-text'>${escH(it.text)}</span>` : ''}</button>`;
    };
    return (items || []).length ? `<div class='boxrow'>${items.map(box).join('')}</div>` : '';
  }
  // status word with glyph: <span class='status-watch'>! Watch</span>
  function statusText(level) { const lv = CARD_LEVEL[level] ? level : 'note', [glyph, word] = CARD_LEVEL[lv]; return `<span class='status-${lv}'><span aria-hidden='true'>${glyph}</span> ${word}</span>`; }
  // consistency per boss. series: [{boss, label (metric), pulls: [{v, k (kill), i (pull number)}] chronological,
  // own (median, computed from v when absent), band [lo, hi] (grey reference band, e.g. role range) or null, fmt}].
  // A boss with < 4 numeric pulls gets a sentence instead of a plot.
  function smallMultiples(series) {
    const W = 160, H = 64, P = 6;
    const one = s => {
      const ps = (s.pulls || []).filter(p => p && cardNum(p.v)), f = cardFmt(s.fmt), boss = escH(s.boss || '');
      if (ps.length < 4) return `<p class='multiples-skip'>${boss}: ${ps.length} pull${ps.length === 1 ? '' : 's'} - too few to judge consistency (needs 4).</p>`;
      const own = cardNum(s.own) ? s.own : cardMedian(ps.map(p => p.v)), band = s.band && cardNum(s.band[0]) && cardNum(s.band[1]) ? s.band : null;
      const all = ps.map(p => p.v).concat(cardNum(own) ? [own] : [], band || []);
      const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
      const x = j => cardR1(P + j / (ps.length - 1) * (W - 2 * P)), y = v => cardR1(hi === lo ? H / 2 : H - P - (v - lo) / span * (H - 2 * P));
      const kills = ps.filter(p => p.k).length, vs = ps.map(p => p.v);
      const desc = `${s.boss || ''}${s.label ? ', ' + s.label : ''}: ${ps.length} pulls, median ${f(own)}, range ${f(Math.min(...vs))} to ${f(Math.max(...vs))}${band ? `, reference band ${f(band[0])} to ${f(band[1])}` : ''}${kills ? `, ${kills} kill${kills === 1 ? '' : 's'} (diamond)` : ''}`;
      const bandSvg = band ? `<rect class='band' x='${P}' y='${Math.min(y(band[0]), y(band[1]))}' width='${W - 2 * P}' height='${cardR1(Math.abs(y(band[1]) - y(band[0])) || 1)}' fill='${TOK.borderStrong}' fill-opacity='0.5'/>` : '';
      const dot = (p, j) => p.k
        ? `<rect x='${cardR1(x(j) - 3.5)}' y='${cardR1(y(p.v) - 3.5)}' width='7' height='7' transform='rotate(45 ${x(j)} ${y(p.v)})' fill='${TOK.accent}'><title>Pull ${escH(p.i ?? j + 1)}: ${f(p.v)}, kill</title></rect>`
        : `<circle cx='${x(j)}' cy='${y(p.v)}' r='2.5' fill='${TOK.series[0]}'><title>Pull ${escH(p.i ?? j + 1)}: ${f(p.v)}</title></circle>`;
      return `<figure class='multiple'><svg viewBox='0 0 ${W} ${H}' role='img' aria-label='${escH(desc)}'><title>${escH(desc)}</title>${bandSvg}` +
        `<line class='median' x1='${P}' x2='${W - P}' y1='${y(own)}' y2='${y(own)}' stroke='${TOK.ink}' stroke-width='1' stroke-dasharray='4 3'/>${ps.map(dot).join('')}</svg>` +
        `<figcaption>${boss} <span class='vs'>median ${f(own)}</span></figcaption></figure>`;
    };
    return (series || []).length ? `<div class='multiples'>${series.map(one).join('')}</div>` : '';
  }
  // mirrors _delta() in dash/home.py (same text and classes); period replaces "previous night" ("earlier nights")
  function deltaText(cur, prev, fmt, lowerIsBetter, period) {
    const per = escH(period || 'previous night'), f = cardFmt(fmt);
    if (prev == null) return "<span class='vs'>first night in range</span>";
    const diff = cur - prev;
    if (Math.abs(diff) < 1e-9) return `<span class='vs'>same as ${per}</span>`;
    const better = lowerIsBetter ? diff < 0 : diff > 0, word = better ? 'better' : 'worse';
    return `<span class='vs delta ${word}'>${diff > 0 ? '&#9650;' : '&#9660;'} ${diff > 0 ? '+' : ''}${f(diff)} vs ${per} (${f(prev)}) - ${word}</span>`;
  }
  // share 0-100 (null = no data) as a bar with the value written next to it (text defaults to "N%")
  function uptimeBar(share, text) {
    if (!cardNum(share)) return `<div class='uptime'><span class='uptime-text'>${escH(text || 'no data')}</span></div>`;
    return `<div class='uptime'><span class='uptime-bar' aria-hidden='true'><i style='width:${cardPct(share, 100)}%'></i></span><span class='uptime-text'>${escH(text || Math.round(share) + '%')}</span></div>`;
  }
  // ---- player card (Players tab under the Player filter): pure model + HTML ----
  // Inputs: lists = [{key, label, pulls, cols (boss pmcols), avoid (boss has an avoidable list), cats, usecats}] in tab
  // order with EVERY pull (the card applies the night / nights-type filter itself, so earlier nights stay available for
  // deltas); players = the Players-tab block (Contract E) or null; G = {night, ntype}. Pull `pm[name]` vectors follow
  // `cols` (PM_COLS). Python scores (sev); this code only selects, caps, orders and renders.
  const CARD_BKIND = { own: 'your earlier nights', role: 'role median', cotank: 'co-tank', band: 'reference' };
  const CARD_METRIC = { dth: 'Deaths per pull', fd: 'First death', avm: 'Avoidable hits / min alive', nodef: 'No defensive before the first death',
    am: 'Active mitigation at hit', prep: 'Flask, food and rune', prepot: 'Pre-pot', act: 'Active time', dps_ratio: 'Active DPS vs your role',
    hps: 'Active HPS', oh: 'Overheal', ilvl: 'Item level', rp: 'Parse on kills', bp: 'Bracket parse on kills', gap: 'Gear gaps', ir: 'Interrupts', ds: 'Dispels' };
  const CARD_PREP = { flask: 'Flask', food: 'Food', rune: 'Augment rune', prepot: 'Pre-pot', vantus: 'Vantus rune', combat_potion: 'Combat potions', healing_potion: 'Healing potions', healthstone: 'Healthstones', mana_potion: 'Mana potions' };
  const CARD_SHORT_S = 60;   // pulls under a minute are left out of the active-time / throughput medians (as in severity.py)
  const cardIdx = cols => { const o = {}; (cols || []).forEach((c, i) => { o[c] = i; }); return o; };
  const cardPl = (n, w, ws) => `${n} ${n === 1 ? w : (ws || w + 's')}`;
  const cardDur = s => { s = Math.round(s || 0); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  const cardK = v => !cardNum(v) ? '-' : Math.abs(v) >= 1000 ? (v / 1000).toFixed(2) + 'M' : Math.round(v) + 'k';
  const cardPc = v => !cardNum(v) ? '-' : Math.round(v) + '%';
  const cardR2 = v => !cardNum(v) ? '-' : String(Math.round(v * 100) / 100);
  const cardTypeOk = (G, p) => !G.ntype || (G.ntype === 'open') === !!p.o;
  const cardSelOk = (G, p) => G.night ? p.n === G.night : cardTypeOk(G, p);
  const cardQuart = (arr, q) => { const s = arr.filter(cardNum).sort((a, b) => a - b); if (!s.length) return null; const k = (s.length - 1) * q, lo = Math.floor(k); return s[lo] + (s[Math.min(lo + 1, s.length - 1)] - s[lo]) * (k - lo); };
  // the night the card scores ("this night"): the toolbar night when it is a known night, else the latest night of the
  // nights-type filter; `have` (optional: array / Set / object of nights) limits the choice to nights the player was in.
  // nights = [[night, type, startMs], ...] chronological (players.nights). null when nothing qualifies.
  function pickNight(nights, G, have) {
    const g = G || {}, ns = nights || [];
    const ok = n => !have || (Array.isArray(have) ? have.includes(n) : have instanceof Set ? have.has(n) : Object.prototype.hasOwnProperty.call(have, n));
    if (g.night) return ns.some(x => x[0] === g.night) && ok(g.night) ? g.night : null;
    const pick = ns.filter(x => (!g.ntype || x[1] === g.ntype) && ok(x[0]));
    return pick.length ? pick[pick.length - 1][0] : null;
  }
  // public cap (design 7.3): at most 3 Watch items (the engine's order = most important first), every Good (so >= 1 Good
  // whenever one exists) and every Note; named builds show everything. Order is kept.
  function capItems(items, named) {
    const all = (items || []).filter(Boolean);
    if (named) return all.slice();
    let w = 0;
    return all.filter(it => it[4] !== 'watch' || ++w <= 3);
  }
  // "One thing to work on": the first Watch item in the engine's order (level, tier, score desc); null when none
  function oneThing(items) { return (items || []).find(it => it && it[4] === 'watch') || null; }
  // the item with the highest score among the Good ones ("best Good"), null when none
  const bestGood = items => (items || []).filter(it => it && it[4] === 'good').reduce((b, it) => !b || (it[5] || 0) > (b[5] || 0) ? it : b, null);
  // ADVICE template -> plain text (escape at the call site): {value} {baseline} {n} (= affected) {pulls}
  const cardAdv = v => v == null || !cardNum(Number(v)) ? 'n/a' : Number.isInteger(Number(v)) ? String(Number(v)) : String(Math.round(Number(v) * (Math.abs(v) >= 10 ? 10 : 100)) / (Math.abs(v) >= 10 ? 10 : 100));
  function fillAdvice(tpl, item) {
    const it = item || [], map = { value: it[1], baseline: it[2], n: it[7], pulls: it[8] };
    return String(tpl || `${CARD_METRIC[it[0]] || it[0] || 'Value'}: {value} (reference {baseline}).`).replace(/\{(value|baseline|n|pulls)\}/g, (_, k) => cardAdv(map[k]));
  }
  // one pull record per pull the player was in: {tab, label, avoid, cats, usecats, p, v(col)}, chronological
  function cardRecs(lists, name, cols) {
    const out = [];
    (lists || []).forEach((l, ti) => {
      const ix = cardIdx(l.cols || cols);
      (l.pulls || []).forEach(p => {
        if (!p || !p.parts || !(name in p.parts)) return;
        const vec = (p.pm || {})[name] || [];
        out.push({ tab: l.key, label: l.label, avoid: !!l.avoid, cats: l.cats || [], usecats: l.usecats || [], p, ti,
          v: c => { const x = vec[ix[c]]; return cardNum(x) ? x : null; },
          of: (who, c) => { const x = ((p.pm || {})[who] || [])[ix[c]]; return cardNum(x) ? x : null; } });
      });
    });
    return out.sort((x, y) => ((x.p.a || 0) - (y.p.a || 0)) || (x.ti - y.ti) || ((x.p.i || 0) - (y.p.i || 0)));
  }
  // per boss tab (tab order): pulls, kills, deaths (dth, post-wipe deaths excluded), first deaths, avoidable hits per minute
  // alive (null when the boss has no avoidable list), median active %, median / best active DPS and HPS (k)
  function perBossRows(lists, name, cols) {
    const by = {};
    cardRecs(lists, name, cols).forEach(r => {
      const e = by[r.tab] || (by[r.tab] = { key: r.tab, label: r.label, ti: r.ti, avoid: r.avoid, pulls: 0, kills: 0, deaths: 0, fd: 0, avh: 0, alv: 0, avn: 0, act: [], dps: [], hps: [] });
      e.pulls++; if (r.p.k) e.kills++;
      e.deaths += r.v('dth') || 0; e.fd += r.v('fd') || 0;
      if (r.v('avh') != null) { e.avh += r.v('avh'); e.alv += Math.max(r.v('alv') || 0, 1); e.avn++; }
      const long = (r.p.d || 0) >= CARD_SHORT_S;
      ['act', 'dps', 'hps'].forEach(c => { if (long && r.v(c) != null) e[c].push(r.v(c)); });
    });
    return Object.values(by).sort((a, b) => a.ti - b.ti).map(e => ({ key: e.key, label: e.label, pulls: e.pulls, kills: e.kills, deaths: e.deaths, fd: e.fd,
      avm: e.avoid && e.avn ? Math.round(e.avh / (e.alv / 60) * 100) / 100 : null, act: cardMedian(e.act),
      dps: cardMedian(e.dps), bestDps: e.dps.length ? Math.max(...e.dps) : null, hps: cardMedian(e.hps), bestHps: e.hps.length ? Math.max(...e.hps) : null }));
  }
  // small-multiples input: one series per boss where the player has >= 4 pulls of at least a minute with `metric`
  // (pm column, e.g. 'dps'); band = the middle half (IQR) of the same boss's values in `history` (earlier pulls), when >= 4
  function consistencySeries(lists, name, cols, metric, history, label, fmt) {
    const vals = recs => recs.filter(r => (r.p.d || 0) >= CARD_SHORT_S && r.v(metric) != null);
    const past = {}; vals(cardRecs(history || [], name, cols)).forEach(r => (past[r.tab] || (past[r.tab] = [])).push(r.v(metric)));
    const by = {}; vals(cardRecs(lists, name, cols)).forEach(r => (by[r.tab] || (by[r.tab] = { boss: r.label, ti: r.ti, pulls: [] })).pulls.push({ v: r.v(metric), k: !!r.p.k, i: r.p.i }));
    return Object.entries(by).filter(([, s]) => s.pulls.length >= 4).sort((a, b) => a[1].ti - b[1].ti).map(([tab, s]) => {
      const h = past[tab] || [];
      return { boss: s.boss, label: label || metric, pulls: s.pulls, band: h.length >= 4 ? [cardQuart(h, 0.25), cardQuart(h, 0.75)] : null, fmt };
    });
  }
  // one night's numbers from pull records (mirrors severity.aggregate_night): dth / pull, fd % of pulls, avm, act and
  // throughput medians over pulls >= 60 s (throughput = hps for healers, dps otherwise), prep = % of pulls missing flask,
  // food or rune, rp / bp mean over kills, ilvl latest
  function cardNight(recs, role) {
    if (!recs.length) return null;
    const nums = c => recs.map(r => r.v(c)).filter(v => v != null), long = recs.filter(r => (r.p.d || 0) >= CARD_SHORT_S);
    const dth = nums('dth'), avh = recs.filter(r => r.avoid && r.v('avh') != null), prep = nums('prep'), kills = recs.filter(r => r.p.k);
    const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
    const alv = avh.reduce((a, r) => a + Math.max(r.v('alv') || 0, 1), 0);
    const ilvl = nums('ilvl');
    return { pulls: recs.length, dth: dth.length ? mean(dth) : null, fdN: recs.filter(r => r.v('fd') === 1).length, fd: 100 * recs.filter(r => r.v('fd') === 1).length / recs.length,
      avm: avh.length ? avh.reduce((a, r) => a + r.v('avh'), 0) / (alv / 60) : null,
      act: cardMedian(long.map(r => r.v('act'))), thr: cardMedian(long.map(r => r.v(role === 'healer' ? 'hps' : 'dps'))),
      prepN: prep.length, prepMiss: prep.filter(v => (v & 7) !== 7).length, prep: prep.length ? 100 * prep.filter(v => (v & 7) !== 7).length / prep.length : null,
      rp: mean(kills.map(r => r.v('rp')).filter(v => v != null)), bp: mean(kills.map(r => r.v('bp')).filter(v => v != null)), ilvl: ilvl.length ? ilvl[ilvl.length - 1] : null };
  }
  // the whole card. opts: {named, recap(death) -> html, roleOf(spec) -> role, support(spec) -> bool, copy (header html),
  // empty (html when the player has no pulls in the selection)}
  function playerCardHtml(name, lists, players, G, opts) {
    const o = opts || {}, g = G || {}, PL = players || {}, recap = o.recap || (() => ''), named = !!o.named;
    const cols = PL.cols || ((lists || []).find(l => l.cols) || {}).cols || [];
    const ro = (PL.roster || {})[name] || {};
    const all = cardRecs(lists, name, cols), sel = all.filter(r => cardSelOk(g, r.p));
    const roleOfSpec = sp => sp && o.roleOf ? o.roleOf(sp) : null;
    const roleAt = r => roleOfSpec((r.p.specs || {})[name]) || ro.role || 'dps';
    const count = (arr, f) => arr.reduce((m, x) => { const k = f(x); if (k) m[k] = (m[k] || 0) + 1; return m; }, {});
    const top = m => Object.entries(m).sort((a, b) => b[1] - a[1])[0];
    const role = (top(count(sel, roleAt)) || [ro.role || 'dps'])[0];
    const spec = (top(count(sel, r => (r.p.specs || {})[name])) || [ro.spec || ''])[0] || ro.spec || '';
    const cl = ro.cl || ((sel[0] || all[0] || { p: { parts: {} } }).p.parts || {})[name] || '';
    const head = sub => `<h2 class='panel-title'>${escH(name)} <span class='sub'>${sub}</span></h2>`;
    const scope = g.night ? escH(g.night) : g.ntype === 'open' ? 'open nights' : g.ntype ? 'main nights' : 'all nights';
    if (!sel.length) return `<div class='card player-card'>${head(scope)}${o.copy ? `<p class='card-counts'>${o.copy}</p>` : ''}${o.empty || emptyHtml('pulls', `${name} has no pulls in this selection`, 'Esc clears the filters')}</div>`;
    // nights: the Players block's chronological list, else first-seen order of the pulls
    const nightList = (PL.nights && PL.nights.length ? PL.nights : []).slice();
    all.forEach(r => { if (!nightList.some(x => x[0] === r.p.n)) nightList.push([r.p.n, r.p.o ? 'open' : 'main', r.p.a || 0]); });
    nightList.sort((a, b) => (a[2] || 0) - (b[2] || 0));
    const selNights = [...new Set(sel.map(r => r.p.n))];
    const night = pickNight(nightList, g, selNights) || selNights[selNights.length - 1];
    const ntype = (nightList.find(x => x[0] === night) || [night, ''])[1];
    const hist = nightList.filter(x => x[1] === ntype && all.some(r => r.p.n === x[0])).map(x => x[0]);
    const histUpTo = hist.slice(0, hist.indexOf(night) + 1).slice(-12), earlier = histUpTo.slice(0, -1);
    const nightAgg = {}; histUpTo.forEach(n => { nightAgg[n] = cardNight(all.filter(r => r.p.n === n), role); });
    const cur = nightAgg[night] || cardNight(sel.filter(r => r.p.n === night), role);
    const earlierRecs = all.filter(r => earlier.includes(r.p.n));
    // severity items of this night, public cap applied
    const items = capItems(((PL.sev || {})[name] || {})[night] || [], named), advice = PL.advice || {};
    const nLv = lv => items.filter(it => it[4] === lv).length;
    const roleWord = { dps: 'DPS', healer: 'Healer', tank: 'Tank' }[role] || role;
    let html = `<div class='card player-card'>`;
    html += `<p class='sr-only' role='status' aria-live='polite'>Card for ${escH(name)}, ${cardPl(selNights.length, 'night')}, ${cardPl(sel.length, 'pull')}</p>`;
    html += head(`${escH([spec, cl ? clsLabel(cl) : ''].filter(Boolean).join(' '))}${spec || cl ? ' &middot; ' : ''}${escH(roleWord)} &middot; ${cardPl(selNights.length, 'night')} &middot; ${cardPl(sel.length, 'pull')} &middot; ${scope}`);
    html += `<p class='card-counts'>${statusText('good')} ${nLv('good')} &middot; ${statusText('watch')} ${nLv('watch')} &middot; ${statusText('note')} ${nLv('note')} <span class='muted'>on ${escH(night)}</span>${o.copy ? ' ' + o.copy : ''}</p>`;
    // block 2: one thing to work on
    const itemLine = it => {
      const base = it[2] == null ? 'no reference yet' : `${CARD_BKIND[it[3]] || 'reference'} ${cardAdv(it[2])}`;
      const rank = named && it[9] ? ` &middot; rank ${escH(it[9])} in your role` : '';
      return `<li>${statusText(it[4])} <strong>${escH(CARD_METRIC[it[0]] || it[0])}</strong>: ${escH(fillAdvice(advice[it[6]] || advice[it[0]], it))} <span class='vs'>${escH(base)}${it[4] !== 'note' || it[7] ? ` &middot; ${it[7]} of ${cardPl(it[8], 'pull')}` : ''}${rank}</span></li>`;
    };
    const one = oneThing(items), good = bestGood(items);
    if (one) html += `<article class='insight warn'><h3><span class='badge'>Watch</span>One thing to work on: ${escH(CARD_METRIC[one[0]] || one[0])}</h3><p>${escH(fillAdvice(advice[one[6]] || advice[one[0]], one))}</p></article>`;
    else html += `<article class='insight good'><h3><span class='badge'>Good</span>One thing to work on: nothing stands out</h3><p>Nothing stands out on ${escH(night)} - keep going.${good ? ' ' + escH(fillAdvice(advice[good[6]] || advice[good[0]], good)) : ''}</p></article>`;
    const shown = items.filter(it => it[4] !== 'note'), notes = items.filter(it => it[4] === 'note');
    if (shown.length) html += `<ul class='card-items'>${shown.map(itemLine).join('')}</ul>`;
    if (notes.length) html += `<details class='card-notes'><summary>${cardPl(notes.length, 'note')} for ${escH(night)}</summary><ul class='card-items'>${notes.map(itemLine).join('')}</ul></details>`;
    if (!items.length) html += `<p class='section-note'>No Good / Watch / Note items for ${escH(night)}${PL.sev ? '' : ' (the Players data is missing from this build)'}.</p>`;
    if (!named && ((PL.sev || {})[name] || {})[night] && ((PL.sev[name][night]).filter(it => it[4] === 'watch').length > 3)) html += `<p class='section-note'>Showing the 3 most important Watch items.</p>`;
    // block 3: KPI tiles for this night, delta vs your earlier nights (same night type), sparkline over the nights
    const anyAvoid = sel.some(r => r.avoid);
    const thrLabel = role === 'healer' ? 'Median active HPS' : 'Median active DPS';
    const tiles = [
      ['Deaths / pull', a => a.dth, cardR2, true, a => cardR2(a.dth)],
      ['First death', a => a.fd, cardPc, true, a => `${a.fdN} of ${cardPl(a.pulls, 'pull')}`],
      anyAvoid ? ['Avoidable hits / min alive', a => a.avm, cardR2, true, a => cardR2(a.avm)] : null,
      ['Active time', a => a.act, cardPc, false, a => cardPc(a.act)],
      [thrLabel, a => a.thr, cardK, false, a => cardK(a.thr)],
      ['Prep misses (flask, food, rune)', a => a.prep, cardPc, true, a => a.prepN ? `${a.prepMiss} of ${cardPl(a.prepN, 'pull')}` : '-'],
      ['Kills: parse / bracket', a => a.rp, v => cardNum(v) ? String(Math.round(v)) : '-', false, a => a.rp == null && a.bp == null ? '-' : `${a.rp == null ? '-' : Math.round(a.rp)} &middot; ${a.bp == null ? '-' : Math.round(a.bp)}`],
      ['Item level', a => a.ilvl, v => cardNum(v) ? String(Math.round(v)) : '-', false, a => a.ilvl == null ? '-' : String(a.ilvl)],
    ].filter(Boolean);
    const trend = histUpTo.length >= 2;
    html += `<h3>${escH(night)}: key numbers</h3>`;
    html += kpisHtml(tiles.map(([label, get, fmt, lower, show]) => {
      const v = cur ? get(cur) : null;
      const prev = cardMedian(earlier.map(n => nightAgg[n] && get(nightAgg[n])).filter(cardNum));
      const nPrev = earlier.filter(n => nightAgg[n] && cardNum(get(nightAgg[n]))).length;
      const delta = !trend || v == null ? '' : prev == null ? "<span class='vs'>no earlier value</span>" : deltaText(v, prev, fmt, lower, `your ${cardPl(nPrev, 'earlier night')}`);
      const spark = sparkline(histUpTo.map(n => nightAgg[n] ? get(nightAgg[n]) : null), { label, fmt });
      return [label, `${cur ? show(cur) : '-'}${v == null ? " <span class='vs'>no data this night</span>" : ''}${delta}${spark}`];
    }), 'card-kpis');
    html += trend ? `<p class='section-note'>Deltas compare ${escH(night)} with the median of your earlier ${ntype === 'open' ? 'open' : 'main'} nights in this build; sparklines need 4 nights.</p>`
      : `<p class='section-note'>First nights &mdash; no trend yet. Deltas appear once you have an earlier ${ntype === 'open' ? 'open' : 'main'} night in this build, sparklines after 4 nights.</p>`;
    // block 4: per boss
    const selLists = (lists || []).map(l => Object.assign({}, l, { pulls: (l.pulls || []).filter(p => cardSelOk(g, p)) }));
    const rows = perBossRows(selLists, name, cols), heal = role === 'healer', thrKey = heal ? 'hps' : 'dps', bestKey = heal ? 'bestHps' : 'bestDps';
    const sortCell = (v, txt) => `<td data-sort='${cardNum(v) ? v : -1}'>${txt}</td>`;
    html += `<h3>Per boss</h3>` + tbl([['Boss', 'str'], ['Pulls', 'num'], ['Kills', 'num'], ['Deaths', 'num'], ['First deaths', 'num'], ['Avoidable / min alive', 'num'], ['Active', 'num'], [heal ? 'Median HPS' : 'Median DPS', 'num'], [heal ? 'Best HPS' : 'Best DPS', 'num']],
      rows.map(e => `<tr><td data-sort='${escH(e.label)}'><button type='button' class='gotab linklike' data-tab='${escH(e.key)}'>${escH(e.label)}</button></td><td>${e.pulls}</td><td>${e.kills}</td><td>${e.deaths}</td><td>${e.fd}</td>${sortCell(e.avm, e.avm == null ? "<span class='muted'>-</span>" : cardR2(e.avm))}${sortCell(e.act, cardPc(e.act))}${sortCell(e[thrKey], cardK(e[thrKey]))}${sortCell(e[bestKey], cardK(e[bestKey]))}</tr>`),
      '', `${cardPl(rows.length, 'boss', 'bosses')} in this selection; active and throughput use pulls of a minute or longer, active DPS / HPS = output per second of activity`);
    html += `<p class='section-note'>Click a boss name to open that tab with the same filters.</p>`;
    // block 5: consistency
    const metric = heal ? 'hps' : 'dps', mLabel = heal ? 'active HPS' : 'active DPS';
    const series = consistencySeries(selLists, name, cols, metric, (lists || []).map(l => Object.assign({}, l, { pulls: (l.pulls || []).filter(p => earlier.includes(p.n)) })), mLabel, cardK);
    html += `<h3>Consistency</h3>`;
    html += series.length ? smallMultiples(series) + `<p class='section-note'>Dots: your ${mLabel} per pull of a minute or longer (diamond = kill); dashed line: your median; grey band: the middle half of your earlier nights on that boss, when there are 4 such pulls.</p>`
      : `<p class='section-note'>No boss has 4 or more of your pulls (a minute or longer) in this selection, so there is nothing to judge consistency on yet.</p>`;
    // block 6: role section
    const roleSel = sel.filter(r => roleAt(r) === role), long = roleSel.filter(r => (r.p.d || 0) >= CARD_SHORT_S);
    const othersMed = (r, c, keep) => cardMedian(Object.keys(r.p.pm || {}).filter(n => n !== name && keep(n)).map(n => r.of(n, c)));
    const isRole = (r, want) => n => { const sp = (r.p.specs || {})[n]; const rr = roleOfSpec(sp) || ((PL.roster || {})[n] || {}).role; return rr === want && !(o.support && o.support(sp)); };
    const others = (c, want) => { const per = long.map(r => othersMed(r, c, isRole(r, want))).filter(cardNum); return per.length ? cardMedian(per) : null; };
    const othersN = want => Math.max(0, ...long.map(r => Object.keys(r.p.pm || {}).filter(n => n !== name && isRole(r, want)(n)).length));
    const mine = c => cardMedian(long.map(r => r.v(c)));
    const mineEarlier = c => cardMedian(earlierRecs.filter(r => roleAt(r) === role && (r.p.d || 0) >= CARD_SHORT_S).map(r => r.v(c)));
    html += `<h3>${escH(roleWord)}${spec ? ' (' + escH(spec) + ')' : ''}</h3>`;
    if (role === 'tank') {
      const am = mine('am'), amw = mine('amw'), mit = mine('mit');
      html += `<p class='card-line'>Active mitigation up at the moment of each hit taken (median of your pulls):</p>` +
        uptimeBar(am, am == null ? 'no aura data for your spec in these pulls (config/tank_mitigation.json)' : `${Math.round(am)}% of hits${amw == null ? '' : `, ${Math.round(amw)}% weighted by damage`}`);
      html += `<p class='card-line'>Mitigated share of incoming damage: <strong>${cardPc(mit)}</strong> <span class='muted'>(mitigated + absorbed / unmitigated, median per pull)</span></p>`;
      const pairs = roleSel.map(r => { const co = Object.keys(r.p.pm || {}).filter(n => n !== name && isRole(r, 'tank')(n)); return { r, me: r.v('dtps'), co: co.map(n => [n, r.of(n, 'dtps')]).filter(x => x[1] != null) }; }).filter(x => x.me != null);
      const mx = Math.max(1, ...pairs.map(x => Math.max(x.me, ...x.co.map(c => c[1]))));
      const kps = v => (v / 10).toFixed(1) + 'k';
      html += pairs.length ? tbl([['Boss', 'str'], ['Pull', 'num'], ['You (DTPS)', 'num'], ['Co-tank (DTPS)', 'num']],
        pairs.map(x => `<tr><td>${escH(x.r.label)}</td><td>${x.r.p.i}</td><td data-sort='${x.me}'>${bar(x.me / mx * 100)} ${kps(x.me)}</td><td data-sort='${x.co.length ? x.co[0][1] : -1}'>${x.co.length ? x.co.map(c => `${bar(c[1] / mx * 100)} ${kps(c[1])} <span class='muted'>${named ? escH(c[0]) : 'co-tank'}</span>`).join('<br>') : "<span class='muted'>no co-tank</span>"}</td></tr>`),
        '', `Damage taken per second alive (thousands), you and your co-tank on the same pull, ${cardPl(pairs.length, 'pull')}`, 15)
        : `<p class='section-note'>No damage-taken data for your pulls.</p>`;
      html += `<p class='section-note'>Death recaps below mark whether active mitigation was up on each of the last hits.</p>`;
    } else if (role === 'healer') {
      const hps = mine('hps'), oh = mine('oh'), ohRole = others('oh', 'healer'), nH = othersN('healer');
      const kills = sel.filter(r => r.p.k), mean = a => a.length ? Math.round(a.reduce((x, y) => x + y, 0) / a.length) : null;
      const rp = mean(kills.map(r => r.v('rp')).filter(cardNum)), bp = mean(kills.map(r => r.v('bp')).filter(cardNum));
      html += kpisHtml([['Median active HPS', cardK(hps)], ['HPS parse / bracket (kills)', rp == null && bp == null ? `- <span class='vs'>no kills in this selection</span>` : `${rp == null ? '-' : rp} &middot; ${bp == null ? '-' : bp}`]], 'card-kpis');
      html += cardNum(oh) ? bulletBar(oh, nH ? ohRole : 30, mineEarlier('oh'), 100, { name: 'Your median overheal', target: nH ? `healer median (${cardPl(nH, 'other')})` : 'reference', own: 'your earlier nights', fmt: cardPc }) + `<p class='section-note'>Lower overheal is better.</p>`
        : `<p class='section-note'>No overheal data in these pulls.</p>`;
      const dps = mine('dps'), dpsRole = others('dps', 'dps');
      html += cardNum(dps) ? `<p class='card-line'>${statusText('note')} Damage done: <strong>${cardK(dps)}</strong> active DPS${cardNum(dpsRole) && dpsRole > 0 ? `, ${Math.round(dps / dpsRole * 100)}% of the DPS players' median (${cardK(dpsRole)}); a quarter is excellent for a healer, per community guides` : ''}.</p>` : '';
    } else {
      const dps = mine('dps'), dpsRole = others('dps', 'dps'), nD = othersN('dps');
      html += cardNum(dps) ? bulletBar(dps, dpsRole, mineEarlier('dps'), null, { name: 'Your median active DPS', target: `DPS median (${cardPl(nD, 'other')})`, own: 'your earlier nights', fmt: cardK })
        : `<p class='section-note'>No active DPS data in these pulls.</p>`;
      if (named && spec) {
        const same = r => n => (r.p.specs || {})[n] === spec;
        const per = long.map(r => othersMed(r, 'dps', same(r))).filter(cardNum), nS = Math.max(0, ...long.map(r => Object.keys(r.p.pm || {}).filter(n => n !== name && same(r)(n)).length));
        html += `<p class='card-line'>Same spec (${escH(spec)}): ${per.length ? `median <strong>${cardK(cardMedian(per))}</strong> active DPS over ${cardPl(nS, 'other player')} in the same pulls` : 'no other player of your spec in these pulls'}.</p>`;
      }
      html += `<p class='section-note'>Active DPS = damage per second of your active time, so it does not punish time spent dead or moving.</p>`;
    }
    // block 7: deaths report card
    const deaths = [], wcAny = sel.some(r => r.p.wc != null); let afterWipe = 0;
    sel.forEach(r => (r.p.deaths || []).forEach((d, k) => { if (d.pl !== name) return; if (r.p.wc != null && d.s > r.p.wc) { afterWipe++; return; } deaths.push({ r, d, first: k === 0 }); }));
    const defWord = x => !x.first ? 'not tracked' : !x.d.hc ? 'unknown' : x.d.def && x.d.def.length ? 'used' : 'none';
    html += `<h3>Deaths (${deaths.length})</h3>`;
    if (deaths.length) {
      html += `<div class='card-deaths'>` + boxRow(deaths.map((x, i) => {
        const dw = defWord(x), ext = x.first && x.d.ext && x.d.ext.length;
        const lvl = x.d.av || (x.first && dw === 'none' && !ext) ? 'watch' : x.first && dw === 'used' ? 'good' : 'note';
        const tags = [x.first ? 'first' : '', x.d.av ? 'avoidable' : ''].filter(Boolean);
        const title = `${x.r.label} pull ${x.r.p.i}, ${cardDur(x.d.s)}: killed by ${x.d.kb || '?'}${x.first ? ', first death' : ''}${x.d.av ? ', avoidable' : ''}; defensive ${dw}${x.first ? `; external ${ext ? x.d.ext.map(e => e[1]).join(', ') : 'none'}` : ''}`;
        return { level: lvl, text: `${cardDur(x.d.s)}${tags.length ? ' ' + tags.join(' · ') : ''}`, title, attrs: { 'data-death': i } };
      })) + `</div>`;
      html += `<details class='table-view card-deathlog'><summary>Show the ${cardPl(deaths.length, 'death')} as a table (with the last seconds)</summary>` +
        tbl([['Boss', 'str'], ['Pull', 'num'], ['Time', 'num'], ['Tags', 'str'], ['Killed by', 'str'], ['Defensive (first death)', 'str'], ['External received', 'str'], ['Last seconds', 'none']],
          deaths.map((x, i) => `<tr id='cdeath_${i}'><td>${escH(x.r.label)}</td><td>${x.r.p.i}</td><td data-sort='${x.d.s}'>${cardDur(x.d.s)}</td><td>${x.first ? "<span class='tag'>first</span>" : ''}${x.d.av ? " <span class='tag warn'>avoidable</span>" : ''}${x.d.os ? " <span class='tag'>one-shot</span>" : ''}</td><td>${escH(x.d.kb || '-')}</td>` +
            `<td>${escH(defWord(x))}${x.first && x.d.def && x.d.def.length ? ': ' + escH(x.d.def.map(e => e[1]).join(', ')) : ''}</td><td>${x.first ? (x.d.ext && x.d.ext.length ? escH(x.d.ext.map(e => `${e[1]} from ${e[2]}`).join(', ')) : 'none') : "<span class='muted'>-</span>"}</td><td>${recap(x.d)}</td></tr>`),
          'deathlog', `${cardPl(deaths.length, 'death')} in pull order`) + `</details>`;
      html += `<p class='section-note'>Watch = avoidable (the killing blow or half the damage in the last seconds came from an avoidable ability) or a first death with no defensive and no external. Defensives are known for the first death of each pull only. Click a box for the recap.</p>`;
    } else html += `<p class='section-note'>No deaths in ${cardPl(sel.length, 'pull')}${afterWipe ? ' (not counting deaths after the wipe started)' : ''}.</p>`;
    if (wcAny) html += `<p class='section-note'>Deaths and hits after the wipe started are not counted (a wipe starts at the first death of a run of 3+ deaths within 10 s that runs to the end of the pull)${afterWipe ? `; ${cardPl(afterWipe, 'death')} of yours fell after that point` : ''}.</p>`;
    // block 8: preparation
    const cats = [], ucats = [];
    sel.forEach(r => { r.cats.forEach(c => { if (c !== 'vantus' && !cats.includes(c)) cats.push(c); }); r.usecats.forEach(c => { if (!ucats.includes(c)) ucats.push(c); }); });
    const consRecs = sel.filter(r => (r.p.cons || {})[name]);
    html += `<h3>Preparation</h3>`;
    if (consRecs.length && cats.length) {
      html += `<ul class='prep-rows'>` + cats.map(c => {
        const marks = consRecs.map(r => { const k = r.cats.indexOf(c); return k < 0 ? null : !!r.p.cons[name][k]; }).filter(x => x !== null);
        const miss = marks.filter(x => !x).length;
        const glyphs = marks.map(x => x ? "<span class='prep-ok'>&#10003;</span>" : "<span class='prep-fail'>&#10005;</span>").join('');
        return `<li><span class='prep-name'>${escH(CARD_PREP[c] || c)}${c === 'prepot' ? " <span class='tag'>under-reported</span>" : ''}</span><span class='prep-glyphs' aria-hidden='true'>${glyphs}</span><span class='prep-count'>${miss ? `missed on ${miss} of ${cardPl(marks.length, 'pull')}` : `on all ${cardPl(marks.length, 'pull')}`}</span></li>`;
      }).join('') + `</ul>`;
      const uses = ucats.map(c => { let t = 0, m = 0; sel.forEach(r => { const k = r.usecats.indexOf(c), u = (r.p.use || {})[name]; if (k >= 0) { m++; if (u) t += u[k] || 0; } }); return m ? `${escH(CARD_PREP[c] || c)}: ${t} in ${cardPl(m, 'pull')}` : ''; }).filter(Boolean);
      if (uses.length) html += `<p class='card-line'>Used during the pull: ${uses.join(' &middot; ')}.</p>`;
      html += `<p class='section-note'>Glyphs are your pulls oldest first (&#10003; present at the pull start, &#10005; missing). Pre-pot is under-reported: WCL only sees potions pressed after the pull starts.</p>`;
    } else html += `<p class='section-note'>No consumable data for your pulls in this selection.</p>`;
    // block 9: gear (latest gear in the build)
    const gear = (PL.gear || {})[name];
    html += `<h3>Gear</h3>`;
    if (gear) {
      const range = cardNum(gear.ilvl_min) && cardNum(gear.ilvl_max) ? ` <span class='muted'>(raid ${gear.ilvl_min}&ndash;${gear.ilvl_max})</span>` : '';
      html += `<p class='card-line'>Item level <strong>${gear.ilvl == null ? '-' : escH(gear.ilvl)}</strong>${range} from your latest pull in this build.</p>`;
      html += (gear.gaps || []).length ? `<ul class='card-gear'>${gear.gaps.map(x => `<li>${statusText('note')} ${escH(x)}</li>`).join('')}</ul>`
        : `<p class='section-note'>No gear gaps: enchants and sockets match the slots most of the raid fills.</p>`;
    } else html += `<p class='section-note'>No gear data for ${escH(name)} in this build.</p>`;
    return html + `</div>`;
  }
  // --- end card components ---
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
  // "Pulled by" cell: player (class colour) + opener ability and its offset from the pull start; a dash when unknown
  const fmtOffset = ms => (ms / 1000).toFixed(1) + ' s';
  const pulledByCell = p => p.pb && p.pb[0]
    ? `<td data-sort='${escH(p.pb[0])}'>${playerCell(p.pb[0], (p.parts || {})[p.pb[0]] || '')}<br><span class='spec'>${escH([p.pb[1], fmtOffset(p.pb[2] || 0)].filter(Boolean).join(', '))}</span></td>`
    : `<td data-sort=''><span class='muted'>&ndash;</span></td>`;
  // shared pull-row cells: Started | Result | Duration | Deaths | Pulled by | Ended in (pull table and Players-tab "All pulls")
  const PULL_CELL_HEADS = [['Started', 'str'], ['Result', 'num'], ['Duration', 'num'], ['Deaths', 'num'], ['Pulled by', 'str'], ['Ended in', 'none']];
  const pullCells = p => `<td>${escH(p.t)}</td><td class='right' data-sort='${p.k ? 0 : p.p}'>${resLabel(p)}</td><td class='right' data-sort='${p.d}'>${fmtD(p.d)}</td><td class='right'>${p.deaths.length}</td>${pulledByCell(p)}<td><span class='spec'>${escH(p.ph || '-')}</span></td>`;
  function pullsTableHtml(S, tab) {
    return `<details class='table-view'><summary>Show the ${S.length} pull${S.length === 1 ? '' : 's'} as a table</summary>` + tbl([['Pull', 'num'], ['Night', 'str']].concat(PULL_CELL_HEADS),
      S.map(p => `<tr><td class='right'>${p.i}</td><td>${escH(p.n)}</td>${pullCells(p)}</tr>`), '', `Every selected pull, the table behind the chart`) + `</details>`;
  }
  // "Who pulled" table (boss tab Summary): the selected pulls S, already narrowed by the global filters and the pull selection
  function whoPulledHtml(S) {
    const r = pullerRows(S);
    if (!r.rows.length) return emptyHtml('puller data', r.total ? 'no friendly action on an enemy was found at the start of these pulls' : 'no pulls in this selection', '');
    const rows = r.rows.map(e => `<tr data-player='${escH(e.name)}'><td>${playerCell(e.name, e.cl)}</td><td>${e.pulls}</td><td data-sort='${e.share}'>${e.share.toFixed(1)}%</td><td>${e.opener ? `${escH(e.opener)} <span class='muted'>(${e.openerCount})</span>` : '-'}</td></tr>`);
    if (r.unknown) rows.push(`<tr class='unknown'><td>Unknown</td><td>${r.unknown}</td><td data-sort='${r.unknownShare}'>${r.unknownShare.toFixed(1)}%</td><td>-</td></tr>`);
    return tbl([['Player', 'str'], ['Pulls', 'num'], ['Share', 'num'], ['Most used opener', 'str']], rows, '',
      `${r.rows.length} player${r.rows.length === 1 ? '' : 's'} started ${r.total - r.unknown} of the ${r.total} selected pull${r.total === 1 ? '' : 's'}, most pulls first`, 15);
  }
  // "Who pulls first" matrix (Players tab): Player, Total, then one column per boss tab in tab order, filtered by `keep`;
  // class pull-matrix keeps the Player column sticky while the scroller scrolls sideways
  // boss tabs in tab order with their pulls filtered by `keep` (input of pullerMatrix / allPullRows)
  const bossPullLists = keep => bossTabs.map(tab => { const st = loadTab(tab); return { key: tab, label: TAB_NAMES[tab], pulls: st ? st.data.pulls.filter(keep) : [] }; });
  function whoPullsFirstHtml(keep) {
    const lists = bossPullLists(keep);
    const m = pullerMatrix(lists);
    let html = `<h2 id='sec_tabPlayers_pull'>Who pulls first</h2>`;
    if (!m.pullers) return html + emptyHtml('puller data', m.total ? 'no friendly action on an enemy was found at the start of these pulls' : 'no boss pulls in this selection', '');
    const cell = n => `<td data-sort='${n || 0}'>${n ? n : "<span class='muted'>-</span>"}</td>`;
    const rows = m.rows.map(e => `<tr data-player='${escH(e.name)}'><td>${playerCell(e.name, e.cl)}</td>${cell(e.total)}${m.cols.map(c => cell(e.counts[c.key])).join('')}</tr>`);
    if (m.unknown.total) rows.push(`<tr class='unknown'><td>Unknown</td><td>${m.unknown.total}</td>${m.cols.map(c => cell(m.unknown.counts[c.key])).join('')}</tr>`);
    html += tbl(pullerMatrixHeads(m.cols), rows, 'pull-matrix',
      `${m.pullers} of ${m.participants} player${m.participants === 1 ? '' : 's'} started ${m.total - m.unknown.total} of ${m.total} boss pull${m.total === 1 ? '' : 's'}, most pulls first`, 15);
    return html + `<p class='section-note'>Columns: boss, N / H / M = Normal / Heroic / Mythic (hover a column head for the full name). The puller is whoever (pet counted for its owner) hit or cast on an enemy first at the start of the pull. A body pull is credited to the first player who then hit the boss.</p>`;
  }
  // "All pulls" (Players tab, under the matrix): every pull of every boss tab and difficulty, one row each, chronological
  function allPullsHtml(keep) {
    const rows = allPullRows(bossPullLists(keep));
    let html = `<h2 id='sec_tabPlayers_allpulls'>All pulls</h2>`;
    if (!rows.length) return html + emptyHtml('pulls', 'no boss pulls in this selection', 'Esc clears the filters');
    const bosses = new Set(rows.map(r => r.tab)).size;
    return html + tbl([['Boss', 'str'], ['Night', 'str'], ['Pull', 'num']].concat(PULL_CELL_HEADS),
      rows.map(({ tab, label, p }) => `<tr><td data-sort='${escH(label)}'><button type='button' class='gotab linklike' data-tab='${tab}'>${escH(label)}</button></td><td data-sort='${p.a || 0}'>${escH(p.n)}</td><td class='right'>${p.i}</td>${pullCells(p)}</tr>`),
      '', `${rows.length} pull${rows.length === 1 ? '' : 's'} across ${bosses} boss${bosses === 1 ? '' : 'es'}, oldest first`, 25);
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
  // Players-tab block (Contract E: cols, roster, nights, sev, gear, advice, named); its own try/catch, so a bad block
  // empties only the player card (boss tabs, Who pulls first and All pulls keep working). data stays null when absent.
  const PLAYERS = { data: null, error: '' };
  {
    const el = document.getElementById('data_tabPlayers');
    if (el && (el.type === 'application/json' || window.DecompressionStream)) {
      try { PLAYERS.data = await inflate(el); }
      catch (err) { PLAYERS.error = err && err.message || String(err); dashShowError(`payload tabPlayers: ${err && (err.stack || err.message) || err}`); }
    }
  }
  const loadTab = tab => PD[tab] || null;
  playersDirty = true;   // the Players tab's "Who pulls first" matrix needs the inflated payloads, also without a filter

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
    // dying tank: 6th element = active mitigation up on that hit (1 / 0 / null = no aura data)
    const am = d.recap.some(r => r.length > 5);
    const amCell = r => !am ? '' : `<td>${r[5] === 1 ? "<span class='tag good'>AM up</span>" : r[5] === 0 ? "<span class='tag warn'>AM down</span>" : "<span class='muted'>unknown</span>"}</td>`;
    const rows = d.recap.map(r => `<tr${r[3] === max ? " class='big'" : ''}><td>-${r[0]}s</td><td>${escH(r[1])}${r[4] ? " <span class='tag'>self</span>" : ''}</td><td>${escH(r[2])}</td><td>${fmtN(r[3])}</td>${amCell(r)}</tr>`).join('');
    const casts = d.cs && d.cs.length ? `<div class='casts'>Cast in that window: ${d.cs.map(c => `${escH(c[1])} <span class='muted'>(-${c[0]}s)</span>`).join(', ')}</div>` : (d.hc ? `<div class='casts'>No casts in that window.</div>` : '');
    const ext = d.ext && d.ext.length ? `<div class='casts'>Received: ${d.ext.map(x => `${escH(x[1])} from ${escH(x[2])} <span class='muted'>(-${x[0]}s)</span>`).join(', ')}</div>` : '';
    return `<details><summary>${d.recap.length} hits, ${fmtN(d.w)}</summary><table class='recap'><thead><tr><th>Before</th><th>Ability</th><th>Source</th><th>Amount</th>${am ? '<th>Mitigation</th>' : ''}</tr></thead><tbody>${rows}</tbody></table>${casts}${ext}</details>`;
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
      <p class='section-note'>Totals across the selected pulls. DPS/HPS = total &divide; time in the pulls that player was in. Parse % (below) is only available for kills - WCL doesn't rank wipes.</p>
      <h3>Who pulled</h3>${whoPulledHtml(S)}`;
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
    if (G.player) store.set('wcl_dash_player', G.player);   // remembered for "Show my card"
    syncPlayerHash();
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
  // the hash follows the Players filter only while the Players tab is open (#tabPlayers?player=X); elsewhere it keeps
  // the #tabN form the tab buttons write. strip = true (clearAll) also drops a ?player= left on any other tab.
  function syncPlayerHash(strip) {
    try {
      const h = location.hash || '', q = h.indexOf('?');
      if (activeTab() === 'tabPlayers') { const want = playerHash(G.player); if (h !== want) history.replaceState(null, '', want); }
      else if (strip && q >= 0) history.replaceState(null, '', h.slice(0, q) || location.pathname + location.search);
    } catch (_) { /* file:// or sandboxed frame without history */ }
  }
  const hasPlayerOption = name => !!name && [...gPlayer.options].some(o => o.value && o.value === name);
  const pickPlayer = name => { if (!hasPlayerOption(name) || G.player === name) return false; gPlayer.value = name; applyGlobal(); return true; };
  // click-your-name: a name in any player row (tr[data-player] .player) or any [data-player-pick] control (#showMyCard,
  // T6's card) sets the toolbar Player filter
  document.addEventListener('click', e => {
    const el = e.target.closest && e.target.closest("tr[data-player] .player, [data-player-pick]"); if (!el) return;
    const name = el.hasAttribute('data-player-pick') ? el.getAttribute('data-player-pick') : el.closest('tr[data-player]').dataset.player;
    if (hasPlayerOption(name)) { e.preventDefault(); pickPlayer(name); }
  });
  // .copy-link (data-player = label, else the current filter): copies page URL + playerHash(name); when the clipboard
  // is unavailable (file://, old browser, denied) the link is shown as selectable text next to the button
  document.addEventListener('click', e => {
    const btn = e.target.closest && e.target.closest('.copy-link'); if (!btn) return;
    e.preventDefault();
    const name = btn.dataset.player || G.player; if (!name) return;
    const url = location.href.split('#')[0] + playerHash(name);
    const fallback = () => {
      let out = btn.nextElementSibling;
      if (!out || !out.classList.contains('copy-url')) { out = document.createElement('code'); out.className = 'copy-url'; btn.after(out); }
      out.textContent = url;
      try { const r = document.createRange(); r.selectNodeContents(out); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); } catch (_) { /* selection is a convenience */ }
    };
    const done = () => { btn.textContent = 'Link copied'; setTimeout(() => { btn.textContent = 'Copy link'; }, 2000); };
    try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, fallback); else fallback(); } catch (_) { fallback(); }
  });
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
    syncPlayerHash(true);
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
  // the player card (filtered Players tab): every pull of every boss tab goes in, playerCardHtml applies the toolbar's
  // night / nights-type filter itself (earlier nights feed the deltas); copy = the header's copy-link button
  function renderPlayerCard(name, copy) {
    if (PLAYERS.error) return `<div class='card player-card'><h2 class='panel-title'>${escH(name)}</h2><p class='card-counts'>${copy || ''}</p>${emptyHtml('player card', `the Players data could not be decoded: ${PLAYERS.error}`, 'the tables below still work')}</div>`;
    const lists = bossTabs.map(tab => { const st = loadTab(tab); return st ? { key: tab, label: TAB_NAMES[tab], pulls: st.data.pulls, cols: st.data.pmcols, avoid: st.data.avoidSet.size > 0, cats: st.data.cats, usecats: st.data.usecats } : null; }).filter(Boolean);
    try {
      return playerCardHtml(name, lists, PLAYERS.data, G, { named: !!CFG.named, recap: recapHtml, roleOf, support: sp => SUPPORT.has(sp), copy,
        empty: emptyHtml('pulls', `${name} has no pulls in this selection`, 'Esc clears the filters') });
    } catch (err) {
      dashShowError(`player card ${name}: ${err && (err.stack || err.message) || err}`);
      return `<div class='card player-card'><h2 class='panel-title'>${escH(name)}</h2><p class='card-counts'>${copy || ''}</p>${emptyHtml('player card', `it could not be built: ${err && err.message || err}`, '')}</div>`;
    }
  }
  // a box in the card's deaths row opens the death table and that death's recap
  document.addEventListener('click', e => {
    const box = e.target.closest && e.target.closest('.card-deaths .box[data-death]'); if (!box) return;
    const row = document.getElementById('cdeath_' + box.dataset.death); if (!row) return;
    const log = row.closest('details.card-deathlog'); if (log) log.open = true;
    const rd = row.querySelector('details'); if (rd) rd.open = true;
    row.scrollIntoView({ block: 'nearest', behavior: SCROLL });
    const sum = rd && rd.querySelector('summary'); if (sum) sum.focus();
  });
  function renderPlayersTab() {
    const stat = document.getElementById('static_tabPlayers'), panel = document.getElementById('detail_tabPlayers');
    playersDirty = false;
    // unfiltered: the static (Python) view stays and the panel carries only the "Who pulls first" matrix over every pull
    if (!G.night && !G.player && !G.ntype) { stat.classList.remove('hidden'); panel.classList.remove('filtered'); panel.classList.add('open');
      const mine = store.get('wcl_dash_player');
      const myCard = hasPlayerOption(mine) ? `<p class='my-card'><button type='button' id='showMyCard' data-player-pick='${escH(mine)}'>Show my card (${escH(mine)})</button></p>` : '';
      panel.innerHTML = myCard + whoPullsFirstHtml(() => true) + allPullsHtml(() => true); wireSort(panel); wireToggles(panel); return; }
    stat.classList.add('hidden');
    const nightOk = p => G.night ? p.n === G.night : typeOk(p);
    let html = `<button type='button' class='close'>&#10005; show everything</button>`;
    if (G.player) {
      html += renderPlayerCard(G.player, `<button type='button' class='copy-link linklike' data-player='${escH(G.player)}'>Copy link</button>`);
      html += whoPullsFirstHtml(p => nightOk(p) && G.player in p.parts);
      html += allPullsHtml(p => nightOk(p) && G.player in p.parts);
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
      html += whoPullsFirstHtml(nightOk);
      html += allPullsHtml(nightOk);
    }
    panel.innerHTML = html; panel.classList.add('open', 'filtered');
    panel.querySelector('.close').addEventListener('click', clearAll);
    wireSort(panel); wireToggles(panel);
  }

  // deep links: dashboard.html#tab3 opens that tab, #tab3:deaths also scrolls to a section; the hash follows the active tab
  // #tabPlayers?player=X (playerHash) pre-selects that player; the query is split off before the ':' section split
  tabButtons.forEach(btn => btn.addEventListener('click', () => { try { history.replaceState(null, '', btn.dataset.tab === 'tabPlayers' && G.player ? playerHash(G.player) : '#' + btn.dataset.tab); } catch (_) { /* ignore */ } }));
  const rawHash = (location.hash || '').slice(1), qAt = rawHash.indexOf('?');
  const [wanted, wantedSec] = (qAt < 0 ? rawHash : rawHash.slice(0, qAt)).split(':');
  const wantedPlayer = parsePlayerHash(rawHash);
  if (hasPlayerOption(wantedPlayer)) { gPlayer.value = wantedPlayer; applyGlobal(); }   // before the tab opens: one render
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
