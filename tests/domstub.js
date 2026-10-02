// Minimal DOM stub for running the whole dash.js under quickjs (tests/test_players_runtime.py). Not a faithful DOM: enough tree, selectors and events to catch
// ReferenceError / TypeError in the dashboard's own code. Globals: window (= globalThis), document, location, history,
// localStorage, navigator, Event, HTMLDetailsElement, setTimeout/requestAnimationFrame (queued; __drainTimers runs them),
// matchMedia, getComputedStyle, getSelection, console. __HTML (string) must be set before __buildDocument() is called.
'use strict';
var __log = [];
var console = { log: (...a) => __log.push(a.map(String).join(' ')), warn: (...a) => __log.push('WARN ' + a.map(String).join(' ')), error: (...a) => __log.push('ERR ' + a.map(String).join(' ')) };
var window = globalThis;
var self = globalThis;

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
const RAW = new Set(['script', 'style']);

class EventTarget_ {
  constructor() { this.__listeners = {}; }
  addEventListener(type, fn, opts) { (this.__listeners[type] || (this.__listeners[type] = [])).push({ fn, capture: !!(opts && (opts === true || opts.capture)) }); }
  removeEventListener(type, fn) { const l = this.__listeners[type]; if (l) this.__listeners[type] = l.filter(x => x.fn !== fn); }
  __fire(ev, phaseCapture) {
    const l = this.__listeners[ev.type] || [];
    for (const { fn, capture } of l.slice()) {
      if (!!capture !== !!phaseCapture) continue;
      ev.currentTarget = this;
      if (typeof fn === 'function') fn.call(this, ev); else if (fn && fn.handleEvent) fn.handleEvent(ev);
      if (ev.__stopImmediate) break;
    }
  }
  dispatchEvent(ev) {
    ev.target = ev.target || this;
    // path: target up to document, then window
    const path = [];
    let n = this; while (n) { path.push(n); n = n.parentNode || (n === document ? null : (n.__isDocument ? null : null)); }
    if (this !== window && path[path.length - 1] !== window) path.push(window);
    for (let i = path.length - 1; i >= 0 && !ev.__stop; i--) path[i].__fire(ev, true);
    for (let i = 0; i < path.length && !ev.__stop; i++) { path[i].__fire(ev, false); if (!ev.bubbles) break; }
    return !ev.defaultPrevented;
  }
}

class Event {
  constructor(type, init) { this.type = type; this.bubbles = !!(init && init.bubbles); this.cancelable = true; this.defaultPrevented = false; this.target = null; this.currentTarget = null; this.__stop = false; }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this.__stop = true; }
  stopImmediatePropagation() { this.__stop = true; this.__stopImmediate = true; }
}
class CustomEvent extends Event { constructor(t, i) { super(t, i); this.detail = i && i.detail; } }
class KeyboardEvent extends Event { constructor(t, i) { super(t, i); Object.assign(this, { key: '', ctrlKey: false, metaKey: false, shiftKey: false }, i || {}); } }
class MouseEvent extends Event { constructor(t, i) { super(t, i); Object.assign(this, { ctrlKey: false, metaKey: false, shiftKey: false, clientX: 0, clientY: 0 }, i || {}); } }

class Node extends EventTarget_ {
  constructor() { super(); this.parentNode = null; this.childNodes = []; }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  get isConnected() { let n = this; while (n) { if (n.__isDocument) return true; n = n.parentNode; } return false; }
}
class TextNode extends Node {
  constructor(t) { super(); this.nodeType = 3; this.nodeName = '#text'; this.data = String(t); }
  get textContent() { return this.data; } set textContent(v) { this.data = String(v); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
}

function cssEsc(s) { return s; }

class Element extends Node {
  constructor(tag) {
    super();
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.nodeName = this.tagName; this.localName = String(tag).toLowerCase();
    this.__attrs = {};
    this.style = new Proxy({ setProperty(k, v) { this[k] = v; }, getPropertyValue(k) { return this[k] || ''; }, removeProperty(k) { delete this[k]; } }, {});
    const el = this;
    this.classList = {
      add(...cs) { const s = el.__classSet(); cs.forEach(c => s.add(c)); el.__setClassSet(s); },
      remove(...cs) { const s = el.__classSet(); cs.forEach(c => s.delete(c)); el.__setClassSet(s); },
      toggle(c, force) { const s = el.__classSet(); const on = force === undefined ? !s.has(c) : !!force; if (on) s.add(c); else s.delete(c); el.__setClassSet(s); return on; },
      contains(c) { return el.__classSet().has(c); },
      get length() { return el.__classSet().size; },
      [Symbol.iterator]() { return el.__classSet()[Symbol.iterator](); },
      toString() { return el.getAttribute('class') || ''; },
    };
    this.dataset = new Proxy({}, {
      get(_, k) { if (typeof k !== 'string') return undefined; const a = 'data-' + k.replace(/[A-Z]/g, m => '-' + m.toLowerCase()); return el.hasAttribute(a) ? el.getAttribute(a) : undefined; },
      set(_, k, v) { el.setAttribute('data-' + k.replace(/[A-Z]/g, m => '-' + m.toLowerCase()), String(v)); return true; },
      has(_, k) { return el.hasAttribute('data-' + k.replace(/[A-Z]/g, m => '-' + m.toLowerCase())); },
      deleteProperty(_, k) { el.removeAttribute('data-' + k.replace(/[A-Z]/g, m => '-' + m.toLowerCase())); return true; },
      ownKeys() { return Object.keys(el.__attrs).filter(a => a.startsWith('data-')).map(a => a.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())); },
      getOwnPropertyDescriptor(_, k) { return { enumerable: true, configurable: true, value: el.dataset[k] }; },
    });
    this.__value = undefined; this.__checked = false; this.__selectedIndex = undefined;
  }
  __classSet() { return new Set((this.getAttribute('class') || '').split(/\s+/).filter(Boolean)); }
  __setClassSet(s) { this.setAttribute('class', [...s].join(' ')); }
  get className() { return this.getAttribute('class') || ''; } set className(v) { this.setAttribute('class', String(v)); }
  get id() { return this.getAttribute('id') || ''; } set id(v) { this.setAttribute('id', String(v)); }
  get title() { return this.getAttribute('title') || ''; } set title(v) { this.setAttribute('title', String(v)); }
  get type() { return this.getAttribute('type') || (this.localName === 'button' ? 'submit' : this.localName === 'input' ? 'text' : ''); } set type(v) { this.setAttribute('type', String(v)); }
  get hidden() { return this.hasAttribute('hidden'); } set hidden(v) { if (v) this.setAttribute('hidden', ''); else this.removeAttribute('hidden'); }
  get open() { return this.hasAttribute('open'); } set open(v) { if (v) this.setAttribute('open', ''); else this.removeAttribute('open'); }
  get disabled() { return this.hasAttribute('disabled'); } set disabled(v) { if (v) this.setAttribute('disabled', ''); else this.removeAttribute('disabled'); }
  get tabIndex() { return this.hasAttribute('tabindex') ? parseInt(this.getAttribute('tabindex'), 10) : -1; } set tabIndex(v) { this.setAttribute('tabindex', String(v)); }
  get checked() { return this.__checkedSet ? this.__checked : this.hasAttribute('checked'); } set checked(v) { this.__checked = !!v; this.__checkedSet = true; }
  get label() { return this.getAttribute('label') || ''; } set label(v) { this.setAttribute('label', String(v)); }
  get htmlFor() { return this.getAttribute('for') || ''; }
  get options() { return this.localName === 'select' ? this.querySelectorAll('option') : undefined; }
  get selectedIndex() { const o = this.options || []; const v = this.value; return o.findIndex(x => x.value === v); }
  get value() {
    if (this.localName === 'select') { const o = this.options; if (this.__value !== undefined && o.some(x => x.value === this.__value)) return this.__value; const sel = o.find(x => x.hasAttribute('selected')) || o[0]; return sel ? sel.value : ''; }
    if (this.localName === 'option') return this.hasAttribute('value') ? this.getAttribute('value') : this.textContent;
    return this.__value !== undefined ? this.__value : (this.getAttribute('value') || '');
  }
  set value(v) {
    v = String(v);
    if (this.localName === 'select') { const o = this.options; this.__value = o.some(x => x.value === v) ? v : ''; return; }
    this.__value = v;
  }
  getAttribute(k) { k = String(k).toLowerCase(); return Object.prototype.hasOwnProperty.call(this.__attrs, k) ? this.__attrs[k] : null; }
  setAttribute(k, v) { this.__attrs[String(k).toLowerCase()] = String(v); }
  removeAttribute(k) { delete this.__attrs[String(k).toLowerCase()]; }
  hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.__attrs, String(k).toLowerCase()); }
  toggleAttribute(k, force) { const on = force === undefined ? !this.hasAttribute(k) : !!force; if (on) this.setAttribute(k, ''); else this.removeAttribute(k); return on; }
  get attributes() { return Object.entries(this.__attrs).map(([name, value]) => ({ name, value })); }
  get children() { return this.childNodes.filter(n => n.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get firstElementChild() { return this.children[0] || null; }
  get lastElementChild() { const c = this.children; return c[c.length - 1] || null; }
  get nextElementSibling() { if (!this.parentNode) return null; const c = this.parentNode.children; return c[c.indexOf(this) + 1] || null; }
  get previousElementSibling() { if (!this.parentNode) return null; const c = this.parentNode.children; return c[c.indexOf(this) - 1] || null; }
  get nextSibling() { if (!this.parentNode) return null; const c = this.parentNode.childNodes; return c[c.indexOf(this) + 1] || null; }
  get tBodies() { return this.children.filter(c => c.localName === 'tbody'); }
  get tHead() { return this.children.find(c => c.localName === 'thead') || null; }
  get rows() { if (this.localName === 'table') return this.querySelectorAll(':scope > thead > tr, :scope > tbody > tr, :scope > tfoot > tr, :scope > tr'); return this.children.filter(c => c.localName === 'tr'); }
  get cells() { return this.children.filter(c => c.localName === 'td' || c.localName === 'th'); }
  get cellIndex() { return this.parentNode ? this.parentNode.cells.indexOf(this) : -1; }
  get offsetHeight() { return 0; } get offsetWidth() { return 0; } get clientWidth() { return 0; } get clientHeight() { return 0; } get scrollWidth() { return 0; } get scrollHeight() { return 0; }
  get scrollTop() { return 0; } set scrollTop(v) { } get scrollLeft() { return 0; } set scrollLeft(v) { }
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 }; }
  scrollIntoView() { } focus() { document.activeElement = this; } blur() { if (document.activeElement === this) document.activeElement = document.body; }
  click() { this.dispatchEvent(new MouseEvent('click', { bubbles: true })); }
  // tree ops
  appendChild(n) { if (n.parentNode) n.parentNode.removeChild(n); n.parentNode = this; this.childNodes.push(n); return n; }
  insertBefore(n, ref) { if (n.parentNode) n.parentNode.removeChild(n); const i = ref ? this.childNodes.indexOf(ref) : -1; n.parentNode = this; if (i < 0) this.childNodes.push(n); else this.childNodes.splice(i, 0, n); return n; }
  removeChild(n) { const i = this.childNodes.indexOf(n); if (i >= 0) { this.childNodes.splice(i, 1); n.parentNode = null; } return n; }
  replaceChild(n, old) { this.insertBefore(n, old); this.removeChild(old); return old; }
  append(...ns) { ns.forEach(n => this.appendChild(typeof n === 'string' ? new TextNode(n) : n)); }
  prepend(...ns) { ns.reverse().forEach(n => this.insertBefore(typeof n === 'string' ? new TextNode(n) : n, this.firstChild)); }
  after(...ns) { if (!this.parentNode) return; const ref = this.nextSibling; ns.forEach(n => this.parentNode.insertBefore(typeof n === 'string' ? new TextNode(n) : n, ref)); }
  before(...ns) { if (!this.parentNode) return; ns.forEach(n => this.parentNode.insertBefore(typeof n === 'string' ? new TextNode(n) : n, this)); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  replaceChildren(...ns) { this.childNodes.slice().forEach(c => this.removeChild(c)); this.append(...ns); }
  cloneNode(deep) { const e = createEl(this.localName); Object.assign(e.__attrs, this.__attrs); if (deep) this.childNodes.forEach(c => e.appendChild(c.nodeType === 3 ? new TextNode(c.data) : c.cloneNode(true))); return e; }
  contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
  insertAdjacentHTML(pos, html) { const frag = parseHTML(html); const kids = frag.childNodes.slice();
    if (pos === 'beforeend') kids.forEach(k => this.appendChild(k)); else if (pos === 'afterbegin') this.prepend(...kids); else if (pos === 'beforebegin') this.before(...kids); else this.after(...kids); }
  get textContent() { return this.childNodes.map(c => c.textContent).join(''); }
  set textContent(v) { this.childNodes.slice().forEach(c => this.removeChild(c)); if (v !== '' && v != null) this.appendChild(new TextNode(v)); }
  get innerText() { return this.textContent; } set innerText(v) { this.textContent = v; }
  get innerHTML() { return this.childNodes.map(serialize).join(''); }
  set innerHTML(v) { this.childNodes.slice().forEach(c => this.removeChild(c)); const frag = parseHTML(String(v)); frag.childNodes.slice().forEach(k => this.appendChild(k)); }
  get outerHTML() { return serialize(this); }
  // selectors
  matches(sel) { return splitList(sel).some(s => matchComplex(this, s, this)); }
  closest(sel) { let n = this; while (n && n.nodeType === 1) { if (n.matches(sel)) return n; n = n.parentNode; } return null; }
  querySelectorAll(sel) { const out = []; const scope = this; const all = descendants(this); splitList(sel).forEach(s => all.forEach(e => { if (matchComplex(e, s, scope) && !out.includes(e)) out.push(e); })); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getElementsByTagName(t) { t = t.toLowerCase(); return descendants(this).filter(e => t === '*' || e.localName === t); }
  getElementsByClassName(c) { return descendants(this).filter(e => e.classList.contains(c)); }
  getElementById(id) { return descendants(this).find(e => e.getAttribute('id') === id) || null; }
}
class HTMLElement extends Element { }
class HTMLDetailsElement extends HTMLElement { }
class HTMLTableElement extends HTMLElement { }
class SVGElement extends Element { }
function createEl(tag) { const t = String(tag).toLowerCase(); if (t === 'details') return new HTMLDetailsElement(t); if (t === 'table') return new HTMLTableElement(t); return new HTMLElement(t); }

function descendants(root) { const out = []; (function walk(n) { n.childNodes.forEach(c => { if (c.nodeType === 1) { out.push(c); walk(c); } }); })(root); return out; }
function serialize(n) { if (n.nodeType === 3) return n.data.replace(/&/g, '&amp;').replace(/</g, '&lt;'); const a = Object.entries(n.__attrs).map(([k, v]) => ` ${k}='${v.replace(/'/g, '&#39;')}'`).join(''); return VOID.has(n.localName) ? `<${n.localName}${a}>` : `<${n.localName}${a}>${n.innerHTML}</${n.localName}>`; }

// ---- selectors: comma lists; combinators ' ' and '>'; compounds of tag #id .class [attr] [attr=v] :scope :not(simple) ----
function splitList(sel) { const out = []; let depth = 0, cur = ''; for (const ch of String(sel)) { if (ch === '[' || ch === '(') depth++; else if (ch === ']' || ch === ')') depth--; if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; } else cur += ch; } if (cur.trim()) out.push(cur.trim()); return out; }
function tokenizeComplex(sel) {
  // -> [{compound, comb}] where comb is the combinator BEFORE this compound (' ' or '>'), null for the first
  const parts = []; let depth = 0, cur = '', comb = null, pendingComb = null;
  const flush = () => { if (cur.trim()) { parts.push({ compound: cur.trim(), comb }); cur = ''; comb = pendingComb; pendingComb = null; } };
  for (let i = 0; i < sel.length; i++) {
    const ch = sel[i];
    if (ch === '[' || ch === '(') depth++; else if (ch === ']' || ch === ')') depth--;
    if (depth === 0 && (ch === ' ' || ch === '>')) {
      if (cur.trim()) { parts.push({ compound: cur.trim(), comb }); cur = ''; comb = ' '; }
      if (ch === '>') comb = '>';
      continue;
    }
    cur += ch;
  }
  if (cur.trim()) parts.push({ compound: cur.trim(), comb });
  return parts;
}
function matchCompound(el, comp, scope) {
  if (!el || el.nodeType !== 1) return false;
  const re = /(\*|[a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:([~|^$*]?=)(?:'([^']*)'|"([^"]*)"|([^\]]+)))?\]|:([\w-]+)(?:\(([^)]*)\))?/g;
  let m, any = false;
  while ((m = re.exec(comp))) {
    any = true;
    if (m[1] !== undefined) { if (m[1] !== '*' && el.localName !== m[1].toLowerCase()) return false; }
    else if (m[2] !== undefined) { if (el.getAttribute('id') !== m[2]) return false; }
    else if (m[3] !== undefined) { if (!el.classList.contains(m[3])) return false; }
    else if (m[4] !== undefined) {
      const name = m[4], op = m[5], val = m[6] !== undefined ? m[6] : m[7] !== undefined ? m[7] : m[8];
      if (!el.hasAttribute(name)) return false;
      if (op) { const a = el.getAttribute(name); if (op === '=' && a !== val) return false; if (op === '^=' && !a.startsWith(val)) return false; if (op === '$=' && !a.endsWith(val)) return false; if (op === '*=' && !a.includes(val)) return false; if (op === '~=' && !a.split(/\s+/).includes(val)) return false; }
    } else if (m[9] !== undefined) {
      const ps = m[9];
      if (ps === 'scope') { if (el !== scope) return false; }
      else if (ps === 'not') { if (splitList(m[10]).some(s => matchCompound(el, s, scope))) return false; }
      else if (ps === 'first-child') { if (el.parentNode.children[0] !== el) return false; }
      else if (ps === 'last-child') { const c = el.parentNode.children; if (c[c.length - 1] !== el) return false; }
      else if (ps === 'checked') { if (!el.checked) return false; }
      else if (ps === 'empty') { if (el.childNodes.length) return false; }
      else return false;   // unsupported pseudo: no match
    }
  }
  return any;
}
function matchComplex(el, sel, scope) {
  const parts = tokenizeComplex(sel);
  if (!parts.length) return false;
  // right-to-left
  let i = parts.length - 1;
  if (!matchCompound(el, parts[i].compound, scope)) return false;
  let node = el;
  while (i > 0) {
    const comb = parts[i].comb; i--;
    if (comb === '>') { node = node.parentNode; if (!node || !matchCompound(node, parts[i].compound, scope)) return false; }
    else { node = node.parentNode; while (node && !matchCompound(node, parts[i].compound, scope)) node = node.parentNode; if (!node) return false; }
  }
  return true;
}

// ---- HTML parser (tolerant tokenizer) ----
function decodeEntities(s) { return s.replace(/&(amp|lt|gt|quot|#39|apos|nbsp|middot|rarr|larr|ndash|mdash|#(\d+)|#x([0-9a-fA-F]+));/g, (m, n, d, h) => { if (d) return String.fromCodePoint(+d); if (h) return String.fromCodePoint(parseInt(h, 16)); return { amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'", apos: "'", nbsp: ' ', middot: '·', rarr: '→', larr: '←', ndash: '–', mdash: '—' }[n] || m; }); }
function parseHTML(html) {
  const root = new HTMLElement('#fragment'); root.nodeType = 11;
  const stack = [root]; let i = 0; const n = html.length;
  const top = () => stack[stack.length - 1];
  while (i < n) {
    const lt = html.indexOf('<', i);
    if (lt < 0) { top().appendChild(new TextNode(decodeEntities(html.slice(i)))); break; }
    if (lt > i) top().appendChild(new TextNode(decodeEntities(html.slice(i, lt))));
    if (html.startsWith('<!--', lt)) { const e = html.indexOf('-->', lt); i = e < 0 ? n : e + 3; continue; }
    if (html[lt + 1] === '!' || html[lt + 1] === '?') { const e = html.indexOf('>', lt); i = e < 0 ? n : e + 1; continue; }
    if (html[lt + 1] === '/') {
      const e = html.indexOf('>', lt); const name = html.slice(lt + 2, e).trim().toLowerCase(); i = e + 1;
      for (let k = stack.length - 1; k > 0; k--) { if (stack[k].localName === name) { stack.length = k; break; } }
      continue;
    }
    // start tag
    let j = lt + 1; while (j < n && /[\w-]/.test(html[j])) j++;
    const name = html.slice(lt + 1, j).toLowerCase();
    if (!name) { top().appendChild(new TextNode('<')); i = lt + 1; continue; }
    const el = createEl(name);
    // attributes
    let selfClose = false;
    while (j < n) {
      while (j < n && /\s/.test(html[j])) j++;
      if (html[j] === '>') { j++; break; }
      if (html[j] === '/' ) { selfClose = true; j++; continue; }
      let k = j; while (k < n && !/[\s=>\/]/.test(html[k])) k++;
      const an = html.slice(j, k).toLowerCase(); j = k;
      while (j < n && /\s/.test(html[j])) j++;
      let av = '';
      if (html[j] === '=') { j++; while (j < n && /\s/.test(html[j])) j++;
        const q = html[j];
        if (q === '"' || q === "'") { const e = html.indexOf(q, j + 1); av = html.slice(j + 1, e < 0 ? n : e); j = e < 0 ? n : e + 1; }
        else { k = j; while (k < n && !/[\s>]/.test(html[k])) k++; av = html.slice(j, k); j = k; }
      }
      if (an) el.setAttribute(an, decodeEntities(av));
    }
    i = j;
    // implied end tags (very small subset): <p> closes an open <p>; <li>/<tr>/<td>/<th>/<option> close same-level siblings
    const implied = { p: ['p'], li: ['li'], tr: ['tr', 'td', 'th'], td: ['td', 'th'], th: ['td', 'th'], option: ['option'], dt: ['dt', 'dd'], dd: ['dt', 'dd'] }[name];
    if (implied) { const t = top(); if (implied.includes(t.localName)) stack.pop(); }
    top().appendChild(el);
    if (RAW.has(name)) { const close = '</' + name; const e = html.toLowerCase().indexOf(close, i); const raw = html.slice(i, e < 0 ? n : e); if (raw) el.appendChild(new TextNode(raw)); const gt = html.indexOf('>', e < 0 ? n : e); i = gt < 0 ? n : gt + 1; continue; }
    if (!selfClose && !VOID.has(name)) stack.push(el);
  }
  return root;
}

// ---- document ----
class Document extends Node {
  constructor() { super(); this.nodeType = 9; this.nodeName = '#document'; this.__isDocument = true; this.activeElement = null; }
  getElementById(id) { return descendants(this).find(e => e.getAttribute('id') === String(id)) || null; }
  querySelectorAll(sel) { return Element.prototype.querySelectorAll.call(this, sel); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getElementsByTagName(t) { return Element.prototype.getElementsByTagName.call(this, t); }
  createElement(t) { return createEl(t); }
  createElementNS(ns, t) { return new SVGElement(t); }
  createTextNode(t) { return new TextNode(t); }
  createDocumentFragment() { const f = new HTMLElement('#fragment'); f.nodeType = 11; return f; }
  createRange() { return { selectNodeContents() { }, selectNode() { } }; }
  get children() { return this.childNodes.filter(n => n.nodeType === 1); }
  get documentElement() { return this.children.find(c => c.localName === 'html') || this.children[0]; }
  get body() { return this.documentElement && this.documentElement.children.find(c => c.localName === 'body') || this.querySelector('body'); }
  get head() { return this.documentElement && this.documentElement.children.find(c => c.localName === 'head') || this.querySelector('head'); }
  appendChild(n) { n.parentNode = this; this.childNodes.push(n); return n; }
  get textContent() { return null; }
}
var document = new Document();
function __buildDocument() {
  const frag = parseHTML(__HTML);
  frag.childNodes.slice().forEach(k => { frag.removeChild(k); document.appendChild(k); });
  document.activeElement = document.body;
}

// ---- window-ish globals ----
var __timers = [];
var __timerSeq = 0;
function setTimeout(fn, ms, ...args) { const id = ++__timerSeq; __timers.push({ id, fn, args, ms: ms || 0 }); return id; }
function clearTimeout(id) { __timers = __timers.filter(t => t.id !== id); }
function setInterval(fn, ms) { return setTimeout(fn, ms); }
function clearInterval(id) { clearTimeout(id); }
function requestAnimationFrame(fn) { return setTimeout(() => fn(0), 0); }
function cancelAnimationFrame(id) { clearTimeout(id); }
function __drainTimers(max) { let k = 0; while (__timers.length && k++ < (max || 1000)) { const t = __timers.shift(); t.fn(...t.args); } return k; }
function matchMedia(q) { return { matches: false, media: q, addEventListener() { }, removeEventListener() { }, addListener() { }, removeListener() { } }; }
function getComputedStyle(el) { return { getPropertyValue: n => n.startsWith('--') ? '#123456' : '' }; }
function getSelection() { return { removeAllRanges() { }, addRange() { }, toString() { return ''; } }; }
function scrollTo() { }
var innerWidth = 1280, innerHeight = 800, devicePixelRatio = 1, scrollY = 0, scrollX = 0;
var __store = {};
var localStorage = { getItem: k => Object.prototype.hasOwnProperty.call(__store, k) ? __store[k] : null, setItem: (k, v) => { __store[k] = String(v); }, removeItem: k => { delete __store[k]; }, clear: () => { __store = {}; }, key: i => Object.keys(__store)[i] || null, get length() { return Object.keys(__store).length; } };
var sessionStorage = localStorage;
var location = { protocol: 'file:', host: '', hostname: '', port: '', pathname: '/dash/dashboard.html', search: '', hash: '', origin: 'null',
  get href() { return 'file:///dash/dashboard.html' + this.search + this.hash; }, reload() { }, assign() { }, replace() { }, toString() { return this.href; } };
var __history = [];
var history = { state: null, replaceState(st, title, url) { __history.push(['replace', url]); if (url != null) __applyUrl(String(url)); }, pushState(st, title, url) { __history.push(['push', url]); if (url != null) __applyUrl(String(url)); }, back() { }, length: 1 };
function __applyUrl(u) { if (u.startsWith('#')) { location.hash = u === '#' ? '' : u; return; } const h = u.indexOf('#'); location.hash = h >= 0 ? u.slice(h) : ''; }
var navigator = { userAgent: 'quickjs-stub', language: 'en', clipboard: undefined, platform: 'linux' };
var __windowListeners = new EventTarget_();
function addEventListener(t, f, o) { __windowListeners.addEventListener(t, f, o); }
function removeEventListener(t, f) { __windowListeners.removeEventListener(t, f); }
function dispatchEvent(ev) { ev.target = ev.target || window; __windowListeners.__fire(ev, true); __windowListeners.__fire(ev, false); return true; }
// EventTarget path code refers to window's __fire
window.__fire = (ev, cap) => __windowListeners.__fire(ev, cap);
window.__listeners = __windowListeners.__listeners;
var Element_ = Element;
var __dashErrors = [];
