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
 * assertions inspect `innerHTML` text instead of a parsed element tree. That is
 * enough for the change-filter behaviour under test and keeps the harness small.
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
  removeChild(child) {
    this.children = this.children.filter(c => c !== child);
    if (child) child.parentElement = null;
    return child;
  }
  remove() {
    if (this.parentElement) this.parentElement.removeChild(this);
  }
  // Selector lookups return a stable placeholder element so code like
  // setStatus() (chip.querySelector('.status-dot')) can write to it.
  querySelector(selector) {
    if (!this._selectorCache.has(selector)) {
      this._selectorCache.set(selector, new StubElement('span'));
    }
    return this._selectorCache.get(selector);
  }
  querySelectorAll() {
    return [];
  }
  addEventListener() {}
  removeEventListener() {}
  dispatchEvent() {
    return true;
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
  get firstElementChild() {
    return this.children[0] || null;
  }
  get nextElementSibling() {
    return null;
  }
  get offsetWidth() {
    return 0;
  }
  get offsetHeight() {
    return 0;
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
  createTextNode(text) {
    return { nodeType: 3, textContent: String(text) };
  },
  querySelector() {
    return null;
  },
  querySelectorAll() {
    return [];
  },
  getElementsByClassName() {
    return [];
  },
  addEventListener() {},
  removeEventListener() {},
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

function emit(payload) {
  process.stdout.write(JSON.stringify(payload));
}

try {
  new vm.Script(source, { filename: 'app.js' }).runInContext(context);
  const run = vm.runInContext('__run', context);
  Promise.resolve(run).then(
    value => {
      emit({ ok: true, value: value === undefined ? null : value, calls: vm.runInContext('__calls', context) });
      process.exit(0);
    },
    err => {
      emit({ ok: false, error: String((err && err.stack) || err), calls: vm.runInContext('__calls', context) });
      process.exit(0);
    }
  );
} catch (err) {
  emit({ ok: false, error: String((err && err.stack) || err) });
  process.exit(0);
}
