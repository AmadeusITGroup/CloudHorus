/*
 * Stub-DOM harness for webui/app.js.
 *
 * The WebUI front end is plain browser JavaScript loaded by pywebview: there is no
 * bundler, no package.json and no JS test runner in this repository. Rather than
 * introducing a whole Node toolchain for a handful of DOM assertions, this harness
 * runs the real `webui/app.js` inside a Node `vm` context on top of a minimal DOM
 * stub whose element ids and initial classes are seeded from the real
 * `webui/index.html`. Tests drive it from pytest (tests/test_plan_diff_webui.py).
 *
 * Tradeoff: the stub implements only the DOM surface app.js actually touches
 * (classList, innerHTML as a plain string, value/checked, appendChild), so
 * assertions on generated markup inspect `innerHTML` text instead of a parsed
 * element tree. That is enough for the change-filter behaviour under test and
 * keeps the harness small.
 *
 * Inspector additions (interactive-resource-inspector 12.1), in the same spirit
 * as the existing showImage / initPanZoom stubs:
 *
 *   1. An `pywebview.api` stub for the three Inspector_Bridge reads. A snippet
 *      calls one of
 *          __installInspectorBridge({ layer, index, records })   // resolves now
 *          __installDeferredInspectorBridge({ ... })             // resolves on demand
 *          __installNullInspectorBridge()                        // every read -> null
 *      and every bridge call lands in `__calls` as
 *      { fn: 'get_interaction_layer' | 'read_inspector_index' | 'read_inspector_record' }.
 *      The deferred variant is flushed with `__resolveInspectorBridge()`, which
 *      is what lets a test observe the loading indicator before the record lands.
 *      `records` is a plain key -> record map; a key with no entry yields null,
 *      which is the unknown-key path.
 *
 *   2. `DOMParser`, real `querySelectorAll` / `querySelector` / `closest` and
 *      `matches` on the stub. The parser is a small XML-ish tokenizer producing
 *      `StubElement` trees carrying `tagName`, `id`, `attributes`, `children`
 *      and `textContent`; a malformed document yields a `<parsererror>` root, as
 *      the browser does. Selector support is deliberately narrow: comma-joined
 *      compound simple selectors (`g.node, g.cluster`, `#id`, `[data-x="y"]`,
 *      `*`). A selector with a combinator (a space, `>`) matches nothing, which
 *      is the pre-existing behaviour for the two descendant selectors app.js
 *      uses. `querySelector` falls back to the stable placeholder element when
 *      nothing in the real tree matches, so setStatus()-style writes still work.
 *
 *   3. `getBBox()` returning fixed geometry (`__STUB_BBOX`), so hit-rect
 *      insertion is asserted structurally — one rect per `g.node`, positioned
 *      from the reported box — rather than visually.
 *
 *   4. A listener registry on both `StubElement` and `document`:
 *      `addEventListener` stores the handler (it used to be a no-op) and
 *      `dispatchEvent({ type, ... })` invokes the handlers registered for that
 *      type, defaulting `target` to the element and supplying a
 *      `preventDefault` / `stopPropagation` pair. That is what lets a test
 *      exercise the delegated stage listeners and the document-level Escape
 *      handler through the paths app.js actually registers, rather than by
 *      calling its handlers directly (Requirements 8.1, 8.2, 8.4).
 *
 * Usage:  node tests/webui_dom_harness.js  < snippet.js
 * The snippet body runs inside the app.js script scope (so `state`, the chip
 * functions and `CHANGE_CATEGORIES` are all in scope) and its return value is
 * printed as JSON, together with everything recorded in `__calls`.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const APP_JS = path.join(ROOT, 'webui', 'app.js');
const INDEX_HTML = path.join(ROOT, 'webui', 'index.html');

// ─── HTML seeds: id -> { tag, className, value, checked } ──────────────────
function seedsFromHtml(html) {
  const seeds = {};
  const tagRe = /<([a-zA-Z][\w-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g;
  let m;
  while ((m = tagRe.exec(html)) !== null) {
    const attrs = m[2] || '';
    const idMatch = /\bid="([^"]+)"/.exec(attrs);
    if (!idMatch) continue;
    const classMatch = /\bclass="([^"]*)"/.exec(attrs);
    const valueMatch = /\bvalue="([^"]*)"/.exec(attrs);
    seeds[idMatch[1]] = {
      tag: m[1],
      className: classMatch ? classMatch[1] : '',
      value: valueMatch ? valueMatch[1] : '',
      checked: /\bchecked\b/.test(attrs),
    };
  }
  // <select> value comes from its selected (or first) <option>
  const selectRe = /<select\b((?:"[^"]*"|'[^']*'|[^>"'])*)>([\s\S]*?)<\/select>/g;
  while ((m = selectRe.exec(html)) !== null) {
    const idMatch = /\bid="([^"]+)"/.exec(m[1] || '');
    if (!idMatch || !seeds[idMatch[1]]) continue;
    const options = [...m[2].matchAll(/<option\b([^>]*)>/g)].map(o => o[1]);
    const selected = options.find(o => /\bselected\b/.test(o)) || options[0] || '';
    const valueMatch = /\bvalue="([^"]*)"/.exec(selected);
    if (valueMatch) seeds[idMatch[1]].value = valueMatch[1];
  }
  return seeds;
}

const SEEDS = seedsFromHtml(fs.readFileSync(INDEX_HTML, 'utf8'));

// ─── Minimal DOM ──────────────────────────────────────────────────────────
function escapeText(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function makeStyle() {
  return {
    cssText: '',
    setProperty(name, value) {
      this[name] = value;
    },
    removeProperty(name) {
      delete this[name];
    },
  };
}

// Fixed geometry reported by StubElement.getBBox(); tests assert hit rects
// against these numbers, so they are exported into the sandbox as __STUB_BBOX.
const STUB_BBOX = { x: 12, y: 34, width: 120, height: 60 };

// ─── Narrow selector engine: comma-joined compound simple selectors ────────
function compileSelector(selector) {
  return String(selector)
    .split(',')
    .map(part => part.trim())
    .filter(Boolean)
    .map(part => {
      // A combinator is out of scope: report it as never-matching, which is the
      // behaviour app.js already sees for its two descendant selectors.
      if (/[\s>+~]/.test(part.replace(/\[[^\]]*\]/g, ''))) return null;
      const spec = { tag: null, id: null, classes: [], attrs: [] };
      let rest = part;
      const attrRe = /\[([\w:.-]+)(?:\s*=\s*["']?([^\]"']*)["']?)?\]/g;
      let m;
      while ((m = attrRe.exec(part)) !== null) spec.attrs.push({ name: m[1], value: m[2] });
      rest = rest.replace(attrRe, '');
      const tagMatch = /^(\*|[\w:-]+)/.exec(rest);
      if (tagMatch) {
        if (tagMatch[1] !== '*') spec.tag = tagMatch[1].toUpperCase();
        rest = rest.slice(tagMatch[1].length);
      }
      const tokenRe = /([#.])([\w:-]+)/g;
      while ((m = tokenRe.exec(rest)) !== null) {
        if (m[1] === '#') spec.id = m[2];
        else spec.classes.push(m[2]);
      }
      return spec;
    })
    .filter(Boolean);
}

function matchesSpec(el, spec) {
  if (!el || el.nodeType === 3) return false;
  if (spec.tag && el.tagName !== spec.tag) return false;
  if (spec.id && el.id !== spec.id) return false;
  for (const name of spec.classes) {
    if (!el.classList || !el.classList.contains(name)) return false;
  }
  for (const attr of spec.attrs) {
    if (!el.hasAttribute || !el.hasAttribute(attr.name)) return false;
    if (attr.value !== undefined && attr.value !== null && el.getAttribute(attr.name) !== attr.value) {
      return false;
    }
  }
  return true;
}

function matchesSelector(el, selector) {
  return compileSelector(selector).some(spec => matchesSpec(el, spec));
}

function collectMatches(root, specs, out) {
  for (const child of root.children || []) {
    if (specs.some(spec => matchesSpec(child, spec))) out.push(child);
    collectMatches(child, specs, out);
  }
  return out;
}

class ClassList {
  constructor(el) {
    this.el = el;
  }
  _read() {
    return (this.el.className || '').split(/\s+/).filter(Boolean);
  }
  _write(names) {
    this.el.className = names.join(' ');
  }
  add(...names) {
    const current = this._read();
    for (const name of names) if (!current.includes(name)) current.push(name);
    this._write(current);
  }
  remove(...names) {
    this._write(this._read().filter(n => !names.includes(n)));
  }
  contains(name) {
    return this._read().includes(name);
  }
  toggle(name, force) {
    const has = this.contains(name);
    const want = force === undefined ? !has : !!force;
    if (want) this.add(name);
    else this.remove(name);
    return want;
  }
  get value() {
    return this.el.className;
  }
}

// ─── Event listeners: a registry plus a synchronous dispatch ──────────────
// Enough of the event model for a test to drive the delegated stage listeners
// and the document-level Escape handler through the registration paths app.js
// uses. No bubbling: a delegated listener is registered on the element the test
// dispatches to, which is exactly how app.js binds the stage.
function addListener(registry, type, handler) {
  if (typeof handler !== 'function') return;
  const key = String(type);
  if (!registry[key]) registry[key] = [];
  registry[key].push(handler);
}

function removeListener(registry, type, handler) {
  const key = String(type);
  if (registry[key]) registry[key] = registry[key].filter(fn => fn !== handler);
}

function fireListeners(registry, host, event) {
  const source = event || {};
  const payload = Object.assign(
    { type: source.type, target: host, preventDefault() {}, stopPropagation() {} },
    source
  );
  if (!payload.target) payload.target = host;
  for (const handler of (registry[String(payload.type)] || []).slice()) handler(payload);
  return true;
}

class StubElement {
  constructor(tag = 'div', id = '') {
    this.tagName = String(tag).toUpperCase();
    this.id = id;
    this.className = '';
    this.innerHTML = '';
    this.textContent = '';
    this.value = '';
    this.checked = false;
    this.children = [];
    this.attributes = {};
    this.style = makeStyle();
    this.classList = new ClassList(this);
    this.parentElement = null;
    this._selectorCache = new Map();
    this._listeners = {};
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') this.className = String(value);
    if (name === 'src') this.src = String(value);
  }
  getAttribute(name) {
    if (name === 'src' && this.src !== undefined) return this.src;
    return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
  }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === 'src') delete this.src;
    if (name === 'class') this.className = '';
  }
  hasAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name) || (name === 'src' && this.src !== undefined);
  }
  appendChild(child) {
    if (child && child.nodeType === 3) {
      // Text node: this is what escapeHtml() relies on
      this.innerHTML += escapeText(child.textContent);
      this.textContent += String(child.textContent);
      return child;
    }
    this.children.push(child);
    if (child) child.parentElement = this;
    return child;
  }
  setAttributeNS(_ns, name, value) {
    this.setAttribute(name, value);
  }
  removeChild(child) {
    this.children = this.children.filter(c => c !== child);
    if (child) child.parentElement = null;
    return child;
  }
  insertBefore(child, reference) {
    const index = reference ? this.children.indexOf(reference) : -1;
    if (index < 0) return this.appendChild(child);
    this.children.splice(index, 0, child);
    if (child) child.parentElement = this;
    return child;
  }
  prepend(...nodes) {
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      this.children.unshift(nodes[i]);
      if (nodes[i]) nodes[i].parentElement = this;
    }
  }
  append(...nodes) {
    for (const node of nodes) this.appendChild(node);
  }
  remove() {
    if (this.parentElement) this.parentElement.removeChild(this);
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parentElement = null;
    this.children = [];
    this.innerHTML = '';
    this.textContent = '';
    for (const node of nodes) this.appendChild(node);
  }
  cloneNode(deep) {
    const copy = new StubElement(this.tagName, this.id);
    copy.className = this.className;
    copy.textContent = this.textContent;
    copy.innerHTML = this.innerHTML;
    copy.value = this.value;
    copy.checked = this.checked;
    copy.attributes = Object.assign({}, this.attributes);
    if (this.src !== undefined) copy.src = this.src;
    if (deep) for (const child of this.children) copy.appendChild(child.cloneNode(true));
    return copy;
  }
  matches(selector) {
    return matchesSelector(this, selector);
  }
  // closest() walks parentElement, starting at this element (Requirements 9.2-9.4, 9.8).
  closest(selector) {
    let node = this;
    while (node) {
      if (matchesSelector(node, selector)) return node;
      node = node.parentElement;
    }
    return null;
  }
  // A real descendant lookup when the element has a parsed/appended tree;
  // otherwise a stable placeholder element so code like setStatus()
  // (chip.querySelector('.status-dot')) can still write to it.
  querySelector(selector) {
    const found = collectMatches(this, compileSelector(selector), []);
    if (found.length) return found[0];
    if (!this._selectorCache.has(selector)) {
      this._selectorCache.set(selector, new StubElement('span'));
    }
    return this._selectorCache.get(selector);
  }
  querySelectorAll(selector) {
    return collectMatches(this, compileSelector(selector), []);
  }
  getElementsByTagName(tag) {
    return this.querySelectorAll(String(tag));
  }
  // Fixed geometry: hit-rect insertion is asserted structurally, not visually.
  getBBox() {
    return Object.assign({}, STUB_BBOX);
  }
  addEventListener(type, handler) {
    addListener(this._listeners, type, handler);
  }
  removeEventListener(type, handler) {
    removeListener(this._listeners, type, handler);
  }
  dispatchEvent(event) {
    return fireListeners(this._listeners, this, event);
  }
  scrollIntoView() {}
  focus() {}
  blur() {}
  click() {}
  insertAdjacentHTML(_position, html) {
    this.innerHTML += html;
  }
  getBoundingClientRect() {
    return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
  }
  get childNodes() {
    return this.children;
  }
  get firstChild() {
    return this.children[0] || null;
  }
  get firstElementChild() {
    return this.children[0] || null;
  }
  get lastElementChild() {
    return this.children[this.children.length - 1] || null;
  }
  get nextElementSibling() {
    if (!this.parentElement) return null;
    const siblings = this.parentElement.children;
    return siblings[siblings.indexOf(this) + 1] || null;
  }
  get offsetWidth() {
    return 0;
  }
  get offsetHeight() {
    return 0;
  }
}

// ─── XML-ish parser: markup text -> StubElement tree ──────────────────────
// HTML voids only: SVG elements such as <use> and <path> are written either
// self-closed or with an explicit end tag, so they must not be forced void.
const VOID_TAGS = new Set(['img', 'br', 'hr', 'input', 'meta', 'link', 'source']);

function decodeEntities(text) {
  return String(text)
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&');
}

function parseAttributes(source) {
  const attrs = {};
  const re = /([\w:.-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  let m;
  while ((m = re.exec(source || '')) !== null) {
    const value = m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3] : m[4] !== undefined ? m[4] : '';
    attrs[m[1]] = decodeEntities(value);
  }
  return attrs;
}

function parseMarkup(text) {
  const cleaned = String(text)
    .replace(/<\?[\s\S]*?\?>/g, '')
    .replace(/<!DOCTYPE[^>]*>/gi, '')
    .replace(/<!--[\s\S]*?-->/g, '');

  const roots = [];
  const stack = [];
  const tagRe = /<(\/)?([A-Za-z_][\w:.-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/)?>/g;
  let cursor = 0;
  let m;

  const addText = raw => {
    if (!raw) return;
    const value = decodeEntities(raw);
    if (!stack.length) return;
    if (!value.trim() && !stack[stack.length - 1]._ownText) return;
    stack[stack.length - 1]._ownText += value;
  };

  while ((m = tagRe.exec(cleaned)) !== null) {
    addText(cleaned.slice(cursor, m.index));
    cursor = m.index + m[0].length;

    const closing = !!m[1];
    const tag = m[2];
    const selfClosing = !!m[4] || VOID_TAGS.has(tag.toLowerCase());

    if (closing) {
      if (!stack.length || stack[stack.length - 1].tagName !== tag.toUpperCase()) {
        return { error: `unexpected closing tag </${tag}>` };
      }
      stack.pop();
      continue;
    }

    const el = new StubElement(tag);
    el._ownText = '';
    const attrs = parseAttributes(m[3]);
    for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, value);
    if (attrs.id !== undefined) el.id = attrs.id;

    if (stack.length) stack[stack.length - 1].appendChild(el);
    else roots.push(el);
    if (!selfClosing) stack.push(el);
  }
  addText(cleaned.slice(cursor));

  if (stack.length) return { error: `unclosed tag <${stack[stack.length - 1].tagName.toLowerCase()}>` };
  if (!roots.length) return { error: 'no root element' };

  // textContent, post-order: own text plus every descendant's text.
  const fillText = el => {
    let text = el._ownText || '';
    for (const child of el.children) text += fillText(child);
    el.textContent = text;
    delete el._ownText;
    return text;
  };
  roots.forEach(fillText);
  return { roots };
}

class StubDocument {
  constructor(roots) {
    this.nodeType = 9;
    this._root = new StubElement('#document');
    for (const root of roots) this._root.appendChild(root);
  }
  get documentElement() {
    return this._root.firstElementChild;
  }
  get children() {
    return this._root.children;
  }
  querySelector(selector) {
    return collectMatches(this._root, compileSelector(selector), [])[0] || null;
  }
  querySelectorAll(selector) {
    return collectMatches(this._root, compileSelector(selector), []);
  }
  getElementsByTagName(tag) {
    return this.querySelectorAll(String(tag));
  }
  getElementById(id) {
    return this.querySelector('#' + id);
  }
}

class DOMParserStub {
  parseFromString(text, _mimeType) {
    const parsed = parseMarkup(text);
    if (parsed.error) {
      const err = new StubElement('parsererror');
      err.textContent = parsed.error;
      return new StubDocument([err]);
    }
    return new StubDocument(parsed.roots);
  }
}

function createSeeded(id) {
  const seed = SEEDS[id];
  const el = new StubElement(seed ? seed.tag : 'div', id);
  if (seed) {
    el.className = seed.className;
    el.value = seed.value;
    el.checked = seed.checked;
    el.__inHtml = true;
  }
  return el;
}

const elements = new Map();

const documentStub = {
  elements,
  body: new StubElement('body'),
  documentElement: new StubElement('html'),
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, createSeeded(id));
    return elements.get(id);
  },
  createElement(tag) {
    return new StubElement(tag);
  },
  createElementNS(_ns, tag) {
    return new StubElement(tag);
  },
  createTextNode(text) {
    return { nodeType: 3, textContent: String(text) };
  },
  // Deep-copies a node parsed in a detached document, which is the route
  // showInteractionLayer() takes instead of innerHTML.
  importNode(node, deep) {
    return node && node.cloneNode ? node.cloneNode(deep !== false) : node;
  },
  // Searches the elements created through getElementById plus the body tree.
  // Nothing matches a selector carrying a combinator, which is what app.js
  // already sees for its two descendant selectors.
  querySelectorAll(selector) {
    const specs = compileSelector(selector);
    if (!specs.length) return [];
    const found = [];
    for (const el of elements.values()) {
      if (specs.some(spec => matchesSpec(el, spec))) found.push(el);
      collectMatches(el, specs, found);
    }
    collectMatches(this.body, specs, found);
    return found;
  },
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  },
  getElementsByTagName(tag) {
    return this.querySelectorAll(String(tag));
  },
  getElementsByClassName(name) {
    return this.querySelectorAll('.' + String(name));
  },
  _listeners: {},
  addEventListener(type, handler) {
    addListener(this._listeners, type, handler);
  },
  removeEventListener(type, handler) {
    removeListener(this._listeners, type, handler);
  },
  dispatchEvent(event) {
    return fireListeners(this._listeners, this, event);
  },
  execCommand() {
    return true;
  },
};

const localStorageStub = {
  _data: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._data, k) ? this._data[k] : null;
  },
  setItem(k, v) {
    this._data[k] = String(v);
  },
  removeItem(k) {
    delete this._data[k];
  },
};

const sandbox = {
  console,
  document: documentStub,
  DOMParser: DOMParserStub,
  __STUB_BBOX: Object.assign({}, STUB_BBOX),
  localStorage: localStorageStub,
  navigator: { clipboard: null, userAgent: 'node' },
  location: { href: 'file:///index.html' },
  setTimeout,
  clearTimeout,
  setInterval: () => 0,
  clearInterval: () => {},
  requestAnimationFrame: () => 0,
  cancelAnimationFrame: () => {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  fetch: () => Promise.reject(new Error('no network in harness')),
  URL,
  Date,
  Math,
  JSON,
  Promise,
  Set,
  Map,
  Object,
  Array,
  String,
  Number,
  Boolean,
  RegExp,
  Error,
};

const context = vm.createContext(sandbox);
vm.runInContext(
  'var window = globalThis; window.self = window; window.pywebview = { api: {} };' +
    'var addEventListener = function(){}; var removeEventListener = function(){};',
  context,
  { filename: 'harness-bootstrap.js' }
);

// ─── Load app.js + instrumentation + the test snippet in one script ───────
const snippet = fs.readFileSync(0, 'utf8');

const PREAMBLE = `
;var __calls = [];
function __record(name, payload) { __calls.push(Object.assign({ fn: name }, payload || {})); }
// showImage() reaches for the pywebview image bridge and the pan/zoom plumbing,
// neither of which is under test here.
showImage = async function (filePath) { __record('showImage', { file: filePath }); };
initPanZoom = function () {};
startOutputPolling = function () {};
startAuthPolling = function () {};
stopAuthPolling = function () {};
launchEagleFlight = function () {};
startEagleSoar = function () {};
stopEagleSoar = function () {};
var __origShowToast = showToast;
showToast = function (message, type) { __record('showToast', { message: message, type: type }); };
var __origAppendConsole = appendConsole;
appendConsole = function (text, tag) { __record('appendConsole', { text: text, tag: tag }); };
// ─── Inspector_Bridge stubs (get_interaction_layer / read_inspector_index /
//     read_inspector_record) fed from fixture data in the snippet's scope. ──
var __bridgePending = [];
function __makeInspectorBridge(fixture, deferred) {
  var data = fixture || {};
  function answer(name, payload, value) {
    __record(name, payload);
    if (!deferred) return Promise.resolve(value);
    return new Promise(function (resolve) {
      __bridgePending.push(function () { resolve(value); });
    });
  }
  return {
    get_interaction_layer: function (pngPath) {
      var layer = data.layer === undefined ? null : data.layer;
      return answer('get_interaction_layer', { file: pngPath }, layer);
    },
    read_inspector_index: function (pngPath) {
      var index = data.index === undefined ? null : data.index;
      return answer('read_inspector_index', { file: pngPath }, index);
    },
    read_inspector_record: function (pngPath, inspectorKey) {
      var records = data.records || {};
      var record = Object.prototype.hasOwnProperty.call(records, inspectorKey) ? records[inspectorKey] : null;
      return answer('read_inspector_record', { file: pngPath, key: inspectorKey }, record);
    },
  };
}
// Immediate variant: every read resolves with the fixture on the next microtask.
function __installInspectorBridge(fixture) {
  window.pywebview.api = Object.assign({}, window.pywebview.api, __makeInspectorBridge(fixture, false));
  return window.pywebview.api;
}
// Deferred variant: reads stay pending until __resolveInspectorBridge(), which
// is what lets a test observe the loading indicator (Requirement 8.10).
function __installDeferredInspectorBridge(fixture) {
  window.pywebview.api = Object.assign({}, window.pywebview.api, __makeInspectorBridge(fixture, true));
  return window.pywebview.api;
}
function __resolveInspectorBridge() {
  var pending = __bridgePending;
  __bridgePending = [];
  pending.forEach(function (resolve) { resolve(); });
  return pending.length;
}
// Null variant: the missing-payload, missing-layer and unknown-key paths.
function __installNullInspectorBridge() {
  return __installInspectorBridge({ layer: null, index: null, records: {} });
}
function __domSnapshot() {
  var panel = document.getElementById('change-filter-panel');
  var chips = document.getElementById('change-filter-chips');
  var badge = document.getElementById('change-undisplayed-badge');
  var progress = document.getElementById('progress-container');
  var img = document.getElementById('viewer-img');
  return {
    panelHidden: panel.classList.contains('hidden'),
    panelClass: panel.className,
    chipsHtml: chips.innerHTML,
    badgeText: badge.textContent,
    badgeHidden: badge.classList.contains('hidden'),
    progressHidden: progress.classList.contains('hidden'),
    imgSrc: img.src || null,
    running: state.running,
    changeTypes: state.changeTypes.slice(),
    commandPreview: document.getElementById('command-preview').innerHTML,
  };
}
`;

const source = fs.readFileSync(APP_JS, 'utf8') + PREAMBLE + '\n__run = (async () => {\n' + snippet + '\n})();\n';

// Exit only once stdout has actually drained. A payload larger than the pipe
// buffer (a record carrying long values, say) is written in several chunks, and
// `process.exit()` right after `write()` would cut it mid-character, which the
// pytest side then sees as truncated JSON rather than as a test result.
function emit(payload) {
  process.stdout.write(JSON.stringify(payload), () => process.exit(0));
}

try {
  new vm.Script(source, { filename: 'app.js' }).runInContext(context);
  const run = vm.runInContext('__run', context);
  Promise.resolve(run).then(
    value => {
      emit({ ok: true, value: value === undefined ? null : value, calls: vm.runInContext('__calls', context) });
    },
    err => {
      emit({ ok: false, error: String((err && err.stack) || err), calls: vm.runInContext('__calls', context) });
    }
  );
} catch (err) {
  emit({ ok: false, error: String((err && err.stack) || err) });
}
