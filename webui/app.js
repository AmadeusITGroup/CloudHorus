/* ─── CloudHorus Modern UI — Application Logic ─── */

// ─── Clipboard Helper (works in non-HTTPS / pywebview contexts) ───
async function copyToClipboard(text) {
  // Try modern API first
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try { await navigator.clipboard.writeText(text); return; } catch (_) { /* fall through */ }
  }
  // Fallback: hidden textarea + execCommand
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
}

// ─── State ───
const state = {
  mode: 'live',
  authMethod: 'device-code',
  envTab: 'linux',
  bicepFiles: [],
  paramFiles: [],
  terraformMainFiles: [],
  terraformVarFiles: [],
  bicepSubscriptions: [],  // parsed from _cloudHorus metadata
  templateSubMap: [],       // maps each template index -> unique subscription index
  running: false,
  lastGeneratedFile: null,
  theme: 'light',
  styleMode: 'egyptian',
  viewerZoom: 1,
};

// ─── pywebview Bridge ───
// pywebview exposes the Python API class as `window.pywebview.api`
function api() {
  return window.pywebview ? window.pywebview.api : null;
}

// ─── Initialization ───
document.addEventListener('DOMContentLoaded', () => {
  // Wait for pywebview API to be ready
  if (window.pywebview) {
    init();
  } else {
    window.addEventListener('pywebviewready', init);
  }
});

function init() {
  refreshPreview();
  startOutputPolling();
  initParticles();
  initSplitter();
  initHSplitter();
  initInfoIcons();
  initTicker();
  loadVersion();
  // Restore theme (default: light)
  const saved = localStorage.getItem('cloudhorus-theme');
  applyTheme(saved || 'light');
  // Restore style mode
  const savedStyle = localStorage.getItem('cloudhorus-style');
  if (savedStyle) applyStyle(savedStyle);
  // Restore panel width
  const savedWidth = localStorage.getItem('cloudhorus-panel-width');
  if (savedWidth) {
    document.getElementById('config-panel').style.width = savedWidth + 'px';
  }
  // Restore panel collapsed state
  if (localStorage.getItem('cloudhorus-panel-collapsed') === '1') {
    toggleConfigPanel();
  }
  // Auto-show tour guide on first visit
  maybeShowTour();

  // Refresh env var helper when SP fields change
  ['input-sp-client-id', 'input-sp-tenant-id'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', refreshEnvVarHelper);
  });
  // Initialize env var helper with default content
  refreshEnvVarHelper();
}

// ─── Version Display ───
async function loadVersion() {
  const a = api();
  if (!a) return;
  try {
    const ver = await a.get_version();
    const badge = document.getElementById('version-badge');
    if (badge && ver) badge.textContent = 'v' + ver;
  } catch (_) { /* version display is non-critical */ }
}

// ─── Panel Splitter (VS Code-style resize) ───
function initSplitter() {
  const splitter = document.getElementById('panel-splitter');
  const panel = document.getElementById('config-panel');
  if (!splitter || !panel) return;

  let dragging = false;
  let startX = 0;
  let startWidth = 0;

  splitter.addEventListener('mousedown', (e) => {
    e.preventDefault();
    dragging = true;
    startX = e.clientX;
    startWidth = panel.offsetWidth;
    splitter.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    const newWidth = Math.max(280, Math.min(window.innerWidth * 0.7, startWidth + dx));
    panel.style.width = newWidth + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    splitter.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    // Persist width
    localStorage.setItem('cloudhorus-panel-width', panel.offsetWidth);
  });

  // Double-click to reset to default
  splitter.addEventListener('dblclick', () => {
    panel.style.width = '420px';
    localStorage.removeItem('cloudhorus-panel-width');
  });
}

// ─── Horizontal Splitter (Console / Viewer resizer) ───
function initHSplitter() {
  const splitter = document.getElementById('h-splitter');
  const consoleSection = document.getElementById('console-section');
  const viewerSection = document.getElementById('viewer-section');
  if (!splitter || !consoleSection) return;

  let dragging = false;
  let startY = 0;
  let startConsoleH = 0;
  let startViewerH = 0;

  splitter.addEventListener('mousedown', (e) => {
    // Only drag if viewer is visible
    if (!viewerSection || viewerSection.classList.contains('hidden')) return;
    e.preventDefault();
    dragging = true;
    startY = e.clientY;
    startConsoleH = consoleSection.offsetHeight;
    startViewerH = viewerSection.offsetHeight;
    splitter.classList.add('dragging');
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dy = e.clientY - startY;
    const minH = 48;
    const newConsoleH = Math.max(minH, startConsoleH + dy);
    const newViewerH = Math.max(minH, startViewerH - dy);
    consoleSection.style.flex = '0 0 ' + newConsoleH + 'px';
    viewerSection.style.flex = '0 0 ' + newViewerH + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    splitter.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });

  // Double-click to reset to equal split
  splitter.addEventListener('dblclick', () => {
    consoleSection.style.flex = '';
    viewerSection.style.flex = '';
    // Clear maximize/minimize states
    consoleSection.classList.remove('minimized', 'maximized');
    viewerSection.classList.remove('minimized', 'maximized');
    updateToggleIcons();
  });
}

// ─── Toggle Output Sections (Console / Viewer maximize/minimize) ───
function toggleOutputSection(which) {
  const consoleSection = document.getElementById('console-section');
  const viewerSection = document.getElementById('viewer-section');
  if (!consoleSection || !viewerSection || viewerSection.classList.contains('hidden')) return;

  // Clear any manual flex from h-splitter drag
  consoleSection.style.flex = '';
  viewerSection.style.flex = '';

  if (which === 'console') {
    if (consoleSection.classList.contains('minimized')) {
      // Restore both to normal
      consoleSection.classList.remove('minimized');
      viewerSection.classList.remove('maximized');
    } else {
      // Minimize console, maximize viewer
      consoleSection.classList.add('minimized');
      consoleSection.classList.remove('maximized');
      viewerSection.classList.add('maximized');
      viewerSection.classList.remove('minimized');
    }
  } else if (which === 'viewer') {
    if (viewerSection.classList.contains('maximized')) {
      // Restore both to normal
      viewerSection.classList.remove('maximized');
      consoleSection.classList.remove('minimized');
    } else {
      // Maximize viewer, minimize console
      viewerSection.classList.add('maximized');
      viewerSection.classList.remove('minimized');
      consoleSection.classList.add('minimized');
      consoleSection.classList.remove('maximized');
    }
  }
  updateToggleIcons();
}

function updateToggleIcons() {
  const consoleSection = document.getElementById('console-section');
  const viewerSection = document.getElementById('viewer-section');
  const consoleBtn = document.getElementById('btn-toggle-console');
  const viewerBtn = document.getElementById('btn-toggle-viewer');

  if (consoleBtn) {
    const icon = consoleBtn.querySelector('i');
    if (consoleSection.classList.contains('minimized')) {
      icon.className = 'fas fa-chevron-down';
      consoleBtn.title = 'Expand console';
    } else {
      icon.className = 'fas fa-chevron-up';
      consoleBtn.title = 'Minimize console';
    }
  }
  if (viewerBtn) {
    const icon = viewerBtn.querySelector('i');
    if (viewerSection.classList.contains('maximized')) {
      icon.className = 'fas fa-compress-alt';
      viewerBtn.title = 'Restore viewer';
    } else {
      icon.className = 'fas fa-expand-alt';
      viewerBtn.title = 'Maximize viewer';
    }
  }
}

// ─── Info Icons ───
// Floating tooltip appended to <body> so it's never clipped by overflow:hidden.
// Event delegation handles both static and dynamically-created info icons.
function initInfoIcons() {
  // Create the floating tooltip element once
  const tip = document.createElement('div');
  tip.className = 'info-tooltip-popup';
  document.body.appendChild(tip);
  let hideTimer = null;

  document.addEventListener('mouseenter', (e) => {
    if (!e.target || !e.target.closest) return;
    const icon = e.target.closest('.info-icon');
    if (!icon) return;
    const text = icon.getAttribute('data-tooltip');
    if (!text) return;
    clearTimeout(hideTimer);
    tip.textContent = text;
    tip.classList.add('visible');

    // Position above the icon
    const rect = icon.getBoundingClientRect();
    const tipW = tip.offsetWidth;
    const tipH = tip.offsetHeight;
    let left = rect.left + rect.width / 2 - tipW / 2;
    let top = rect.top - tipH - 10;
    // Keep within viewport
    if (left < 8) left = 8;
    if (left + tipW > window.innerWidth - 8) left = window.innerWidth - tipW - 8;
    if (top < 8) { top = rect.bottom + 10; } // flip below if no room above
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }, true);

  document.addEventListener('mouseleave', (e) => {
    if (!e.target || !e.target.closest) return;
    const icon = e.target.closest('.info-icon');
    if (!icon) return;
    hideTimer = setTimeout(() => {
      tip.classList.remove('visible');
    }, 80);
  }, true);

  // Prevent info-icon clicks from toggling parent <label> checkboxes
  document.addEventListener('click', (e) => {
    if (!e.target || !e.target.closest) return;
    const icon = e.target.closest('.info-icon');
    if (icon) {
      e.preventDefault();
      e.stopPropagation();
    }
  });
}

// ─── Theme ───
function toggleTheme() {
  const next = state.theme === 'dark' ? 'light' : 'dark';
  applyTheme(next);
}
function applyTheme(t) {
  state.theme = t;
  document.documentElement.setAttribute('data-theme', t);
  const icon = document.querySelector('#theme-toggle i');
  icon.className = t === 'dark' ? 'fas fa-moon' : 'fas fa-sun';
  localStorage.setItem('cloudhorus-theme', t);
}

// ─── Style Mode (Egyptian ↔ Modern) ───
function toggleStyle() {
  const next = state.styleMode === 'egyptian' ? 'modern' : 'egyptian';
  applyStyle(next);
}
function applyStyle(s) {
  state.styleMode = s;
  if (s === 'modern') {
    document.documentElement.setAttribute('data-style', 'modern');
  } else {
    document.documentElement.removeAttribute('data-style');
  }
  // Update toggle icon
  const icon = document.querySelector('#style-toggle i');
  if (icon) {
    icon.className = s === 'egyptian' ? 'fas fa-ankh' : 'fas fa-laptop-code';
  }
  // Update toggle tooltip
  const btn = document.getElementById('style-toggle');
  if (btn) {
    btn.title = s === 'egyptian'
      ? 'Switch to Modern style'
      : 'Switch to Egyptian style';
  }
  // Update particle colors
  updateParticleColors(s);
  localStorage.setItem('cloudhorus-style', s);
}

// ─── Header Ticker (Scrolling Tips) ───
const TICKER_TIPS = [
  { icon: 'fa-feather-alt', text: 'CloudHorus — Visualize your entire Azure architecture in one diagram' },
  { icon: 'fa-lightbulb', text: 'Tip: Use LR edge direction when you have many peer resources per tier' },
  { icon: 'fa-layer-group', text: 'Tip: Enable Subnet Optimization to hide unused subnets in large VNets' },
  { icon: 'fa-network-wired', text: 'Tip: PE Optimization groups Private Endpoints by subnet context' },
  { icon: 'fa-file-code', text: 'Bicep Mode: Analyze Bicep templates without an Azure subscription' },
  { icon: 'fa-code-branch', text: 'Terraform Mode: Analyze main.tf plus tfvars offline' },
  { icon: 'fa-cloud', text: 'Live Mode: Scan real tenants, subscriptions & resource groups' },
  { icon: 'fa-arrows-alt-h', text: 'Tip: Increase edge length (2-3) if edges overlap around hubs' },
  { icon: 'fa-shield-alt', text: 'Tip: Cross-PE Optimization hides PEs without cross-tenant dependencies' },
  { icon: 'fa-sitemap', text: 'Tip: Use TB direction for vertical layering, LR for horizontal spread' },
  { icon: 'fa-th', text: 'Tip: Lower maxSubnetPerLine to reduce horizontal scroll on wide diagrams' },
  { icon: 'fa-dns', text: 'Tip: DNS Zone Optimization aggregates Private DNS zones per VNet' },
  { icon: 'fa-eye', text: 'Tip: Hover over any parameter label (ⓘ) for a detailed description' },
  { icon: 'fa-compress-arrows-alt', text: 'Tip: Drag the splitter between panels to resize the layout' },
  { icon: 'fa-image', text: 'Tip: Use the zoom controls to inspect generated diagrams in detail' },
  { icon: 'fa-terminal', text: 'Tip: Check the console output for detailed generation logs' },
  { icon: 'fa-bolt', text: 'Tip: Per-subscription settings let you fine-tune each subscription independently' },
];

function initTicker() {
  const track = document.getElementById('ticker-track');
  if (!track) return;
  // Build two copies of all tips for seamless infinite scroll
  let html = '';
  for (let copy = 0; copy < 2; copy++) {
    TICKER_TIPS.forEach((tip, i) => {
      html += `<span class="ticker-item"><i class="fas ${tip.icon}"></i>${tip.text}</span>`;
      html += `<span class="ticker-sep">◆</span>`;
    });
  }
  track.innerHTML = html;
  // Set animation duration based on tip count (approx 8s per tip)
  const dur = TICKER_TIPS.length * 8;
  track.parentElement.style.setProperty('--ticker-duration', dur + 's');
}

// ─── Mode Selection ───
function selectMode(mode) {
  state.mode = mode;
  document.getElementById('mode-live').classList.toggle('active', mode === 'live');
  document.getElementById('mode-bicep').classList.toggle('active', mode === 'bicep');
  document.getElementById('mode-terraform').classList.toggle('active', mode === 'terraform');

  const azureSection = document.getElementById('section-azure-scope');
  const bicepSection = document.getElementById('section-bicep-files');
  const terraformSection = document.getElementById('section-terraform-files');
  const authSection = document.getElementById('section-auth');

  if (mode === 'live') {
    azureSection.classList.remove('hidden');
    bicepSection.classList.add('hidden');
    terraformSection.classList.add('hidden');
    if (authSection) authSection.classList.remove('hidden');
  } else if (mode === 'bicep') {
    azureSection.classList.add('hidden');
    bicepSection.classList.remove('hidden');
    terraformSection.classList.add('hidden');
    // Offline modes hide auth and force device-code (no SP needed)
    if (authSection) authSection.classList.add('hidden');
    state.authMethod = 'device-code';
  } else {
    azureSection.classList.add('hidden');
    bicepSection.classList.add('hidden');
    terraformSection.classList.remove('hidden');
    if (authSection) authSection.classList.add('hidden');
    state.authMethod = 'device-code';
  }
  refreshPreview();
}

// ─── Authentication Method ───
function selectAuthMethod(method) {
  state.authMethod = method;
  document.getElementById('auth-device-code').classList.toggle('active', method === 'device-code');
  document.getElementById('auth-service-principal').classList.toggle('active', method === 'service-principal');

  const spSection = document.getElementById('sp-credentials');
  if (method === 'service-principal') {
    spSection.classList.remove('hidden');
    // Auto-fill SP Tenant ID from the first tenant tag if available
    const tenantInput = document.getElementById('input-tenants');
    const spTenantInput = document.getElementById('input-sp-tenant-id');
    if (tenantInput && spTenantInput && !spTenantInput.value && tenantInput.value) {
      spTenantInput.value = tenantInput.value.split(/\s+/)[0];
    }
  } else {
    spSection.classList.add('hidden');
  }
  refreshEnvVarHelper();
  refreshPreview();
}

function toggleSecretVisibility() {
  const input = document.getElementById('input-sp-secret');
  const icon = document.getElementById('icon-secret-toggle');
  if (input.type === 'password') {
    input.type = 'text';
    icon.classList.replace('fa-eye', 'fa-eye-slash');
  } else {
    input.type = 'password';
    icon.classList.replace('fa-eye-slash', 'fa-eye');
  }
}

async function validateSP() {
  const a = api();
  const resultEl = document.getElementById('sp-validation-result');
  resultEl.classList.remove('hidden', 'success', 'error');

  const clientId = document.getElementById('input-sp-client-id').value.trim();
  const tenantId = document.getElementById('input-sp-tenant-id').value.trim();
  const secret = document.getElementById('input-sp-secret').value;

  if (!clientId || !tenantId) {
    resultEl.classList.add('error');
    resultEl.innerHTML = '<i class="fas fa-times-circle"></i> Client ID and Tenant ID are required.';
    resultEl.classList.remove('hidden');
    return;
  }
  if (!secret) {
    resultEl.classList.add('error');
    resultEl.innerHTML = '<i class="fas fa-times-circle"></i> Client secret is required.';
    resultEl.classList.remove('hidden');
    return;
  }

  resultEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Validating...';
  resultEl.classList.remove('hidden');

  if (a && a.validate_service_principal) {
    try {
      const res = await a.validate_service_principal(clientId, tenantId, secret);
      if (res && res.valid) {
        resultEl.classList.add('success');
        resultEl.innerHTML = '<i class="fas fa-check-circle"></i> Service Principal credentials are valid.';
      } else {
        resultEl.classList.add('error');
        resultEl.innerHTML = '<i class="fas fa-times-circle"></i> ' + escapeHtml(res.error || 'Validation failed.');
      }
    } catch (e) {
      resultEl.classList.add('error');
      resultEl.innerHTML = '<i class="fas fa-times-circle"></i> ' + escapeHtml(e.message || 'Validation error.');
    }
  } else {
    // No backend — show info that validation requires the backend
    resultEl.classList.add('error');
    resultEl.innerHTML = '<i class="fas fa-info-circle"></i> Backend not available for live validation.';
  }
}

// ─── OS-Aware Env Var Helper ───
function selectEnvTab(tab) {
  state.envTab = tab;
  document.getElementById('env-tab-linux').classList.toggle('active', tab === 'linux');
  document.getElementById('env-tab-windows').classList.toggle('active', tab === 'windows');
  document.getElementById('env-tab-powershell').classList.toggle('active', tab === 'powershell');
  refreshEnvVarHelper();
}

function refreshEnvVarHelper() {
  const pre = document.getElementById('env-var-pre');
  if (!pre) return;

  const clientId = document.getElementById('input-sp-client-id').value.trim() || '<YOUR_CLIENT_ID>';
  const tenantId = document.getElementById('input-sp-tenant-id').value.trim() || '<YOUR_TENANT_ID>';

  const tab = state.envTab;
  let lines = [];

  if (tab === 'linux') {
    lines.push('# Set these in your shell before running CloudHorus');
    lines.push('export AZURE_CLIENT_ID="' + clientId + '"');
    lines.push('export AZURE_TENANT_ID="' + tenantId + '"');
    lines.push('export AZURE_CLIENT_SECRET="<YOUR_SECRET>"');
    lines.push('');
    lines.push('python3 src/main.py --authMethod service-principal \\');
    lines.push('  --tenants ' + tenantId + ' \\');
    lines.push('  --subscriptions <SUB_ID> \\');
    lines.push('  --resourcegroups <RG_NAME>');
  } else if (tab === 'windows') {
    lines.push('REM Set these in Command Prompt before running CloudHorus');
    lines.push('set AZURE_CLIENT_ID=' + clientId);
    lines.push('set AZURE_TENANT_ID=' + tenantId);
    lines.push('set AZURE_CLIENT_SECRET=<YOUR_SECRET>');
    lines.push('');
    lines.push('python src\\main.py --authMethod service-principal ^');
    lines.push('  --tenants ' + tenantId + ' ^');
    lines.push('  --subscriptions <SUB_ID> ^');
    lines.push('  --resourcegroups <RG_NAME>');
  } else {
    lines.push('# Set these in PowerShell before running CloudHorus');
    lines.push('$env:AZURE_CLIENT_ID = "' + clientId + '"');
    lines.push('$env:AZURE_TENANT_ID = "' + tenantId + '"');
    lines.push('$env:AZURE_CLIENT_SECRET = "<YOUR_SECRET>"');
    lines.push('');
    lines.push('python src/main.py --authMethod service-principal `');
    lines.push('  --tenants ' + tenantId + ' `');
    lines.push('  --subscriptions <SUB_ID> `');
    lines.push('  --resourcegroups <RG_NAME>');
  }

  pre.textContent = lines.join('\n');
}

async function copyEnvVars() {
  const pre = document.getElementById('env-var-pre');
  if (pre) {
    await copyToClipboard(pre.textContent);
    showToast('Environment variables copied to clipboard', 'success');
  }
}

// ─── Collapsible Sections ───
function toggleSection(header) {
  header.classList.toggle('collapsed');
  const body = header.nextElementSibling;
  if (body) body.classList.toggle('collapsed');
}

// ─── Config Panel Collapse/Expand ───
function toggleConfigPanel() {
  const panel = document.getElementById('config-panel');
  const expandBtn = document.getElementById('btn-expand-panel');
  const splitter = document.getElementById('panel-splitter');
  const isCollapsed = panel.classList.toggle('collapsed');

  if (isCollapsed) {
    expandBtn.classList.remove('hidden');
    splitter.classList.add('hidden');
  } else {
    expandBtn.classList.add('hidden');
    splitter.classList.remove('hidden');
    // Restore saved width or default
    const savedWidth = localStorage.getItem('cloudhorus-panel-width');
    if (savedWidth) {
      panel.style.width = savedWidth + 'px';
    }
  }
  localStorage.setItem('cloudhorus-panel-collapsed', isCollapsed ? '1' : '0');
}

// ─── Stepper Input ───
function stepValue(id, delta) {
  const input = document.getElementById(id);
  let val = parseInt(input.value) || 0;
  const min = parseInt(input.min) || 0;
  const max = parseInt(input.max) || 999;
  val = Math.max(min, Math.min(max, val + delta));
  input.value = val;
  // Animate
  input.style.transform = 'scale(1.15)';
  setTimeout(() => input.style.transform = 'scale(1)', 150);
  refreshPreview();
}

// ─── Tag/Chip Input System ───
// Stores tags per field: { tenants: [...], subscriptions: [...], resourcegroups: [...] }
const tagStore = { tenants: [], subscriptions: [], resourcegroups: [] };
// Tracks which RGs have discovery enabled (per-RG toggle)
const discoveryStore = new Set();

function focusTagInput(wrapper) {
  const entry = wrapper.querySelector('.tag-text-input');
  if (entry) entry.focus();
}

function handleTagKey(e, field) {
  if (e.key === 'Enter' || e.key === 'Tab' || e.key === ',') {
    e.preventDefault();
    const entry = e.target;
    const raw = entry.value.trim();
    if (raw) {
      addTags(field, raw.split(/[\s,;]+/).filter(Boolean));
      entry.value = '';
    }
  } else if (e.key === 'Backspace' && !e.target.value && tagStore[field].length > 0) {
    // Remove last tag on Backspace in empty input
    removeTag(field, tagStore[field].length - 1);
  }
}

function handleTagPaste(e, field) {
  e.preventDefault();
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!text) return;
  // Split pasted text by whitespace, commas, semicolons, newlines
  const items = text.split(/[\s,;\n\r]+/).map(s => s.trim()).filter(Boolean);
  if (items.length > 0) {
    addTags(field, items);
    e.target.value = '';
  }
}

function addTags(field, values) {
  let added = 0;
  for (const v of values) {
    // Avoid duplicates
    if (!tagStore[field].includes(v)) {
      tagStore[field].push(v);
      added++;
    }
  }
  if (added > 0) {
    syncTagsToHidden(field);
    renderTags(field);
    if (field === 'subscriptions') onSubscriptionsChange();
    refreshPreview();
  }
}

function removeTag(field, index) {
  const removed = tagStore[field][index];
  tagStore[field].splice(index, 1);
  if (field === 'resourcegroups') discoveryStore.delete(removed);
  syncTagsToHidden(field);
  renderTags(field);
  if (field === 'subscriptions') onSubscriptionsChange();
  refreshPreview();
}

function syncTagsToHidden(field) {
  // Write space-separated values into the hidden input so all existing
  // code that reads .value continues to work without changes
  const hidden = document.getElementById('input-' + field);
  hidden.value = tagStore[field].join(' ');
}

function renderTags(field) {
  const container = document.getElementById('tags-' + field);
  container.innerHTML = tagStore[field].map((tag, i) => {
    const discoverToggle = field === 'resourcegroups'
      ? `<span class="chip-discover ${discoveryStore.has(tag) ? 'active' : ''}" onclick="event.stopPropagation(); toggleRgDiscovery('${escapeHtml(tag)}')" title="Toggle discovery for this RG"><i class="fas fa-search-plus"></i></span>`
      : '';
    return `<span class="tag-chip${field === 'resourcegroups' && discoveryStore.has(tag) ? ' discovery-on' : ''}" title="${escapeHtml(tag)}">
      ${discoverToggle}
      <span class="chip-label">${escapeHtml(tag)}</span>
      <span class="chip-remove" onclick="event.stopPropagation(); removeTag('${field}', ${i})">&times;</span>
    </span>`;
  }).join('');

  // Update count badge
  let badge = container.parentElement.querySelector('.tag-count');
  if (tagStore[field].length > 0) {
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'tag-count';
      container.parentElement.appendChild(badge);
    }
    badge.textContent = tagStore[field].length + ' item' + (tagStore[field].length > 1 ? 's' : '');
  } else if (badge) {
    badge.remove();
  }
}

function toggleRgDiscovery(rgName) {
  if (discoveryStore.has(rgName)) {
    discoveryStore.delete(rgName);
  } else {
    discoveryStore.add(rgName);
  }
  // Sync the global checkbox
  const chk = document.getElementById('chk-discover-rgs');
  if (chk) {
    chk.checked = tagStore.resourcegroups.length > 0 &&
      tagStore.resourcegroups.every(rg => discoveryStore.has(rg));
  }
  renderTags('resourcegroups');
  refreshPreview();
}

function toggleAllRgDiscovery() {
  const chk = document.getElementById('chk-discover-rgs');
  if (chk && chk.checked) {
    tagStore.resourcegroups.forEach(rg => discoveryStore.add(rg));
  } else {
    discoveryStore.clear();
  }
  renderTags('resourcegroups');
  refreshPreview();
}

function isGuid(s) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);
}

// ─── Per-Subscription Dynamic Controls ───
function onSubscriptionsChange() {
  const val = document.getElementById('input-subscriptions').value.trim();
  const subs = val ? val.split(/\s+/) : [];
  const container = document.getElementById('per-sub-options');
  const grid = document.getElementById('per-sub-grid');

  if (subs.length === 0) {
    container.classList.add('hidden');
    return;
  }

  container.classList.remove('hidden');
  grid.innerHTML = '';

  subs.forEach((sub, i) => {
    const shortId = sub.length > 12 ? sub.substring(0, 8) + '...' : sub;
    const row = document.createElement('div');
    row.className = 'per-sub-row';
    row.innerHTML = `
      <div class="per-sub-row-header">
        <i class="fas fa-layer-group"></i> Subscription ${i + 1}: ${shortId}
      </div>
      <div class="per-sub-toggles">
        <label class="per-sub-toggle">
          <span>Subnet Opt<span class="info-icon" data-tooltip="Hides subnets that don't have VNet integration. Useful to avoid plotting all subnets in a Landing Zone VNet and keep only those linked to Private Endpoints."><i class="fas fa-info-circle"></i></span></span>
          <input type="checkbox" id="sub-subnet-${i}" onchange="refreshPreview()">
          <span class="mini-toggle" onclick="toggleMini(this, event)"></span>
        </label>
        <label class="per-sub-toggle">
          <span>PE Opt<span class="info-icon" data-tooltip="Groups and moves Private Endpoints by their subnet context for a cleaner layout. Enabled by default."><i class="fas fa-info-circle"></i></span></span>
          <input type="checkbox" id="sub-pe-${i}" checked onchange="refreshPreview()">
          <span class="mini-toggle" onclick="toggleMini(this, event)"></span>
        </label>
        <label class="per-sub-toggle">
          <span>Cross-PE Opt<span class="info-icon" data-tooltip="Hides Private Endpoints that have no cross-tenant dependencies with resources (not VNet integration). Enable for performance and clarity in multi-tenant architectures."><i class="fas fa-info-circle"></i></span></span>
          <input type="checkbox" id="sub-crosspe-${i}" onchange="refreshPreview()">
          <span class="mini-toggle" onclick="toggleMini(this, event)"></span>
        </label>
        <label class="per-sub-toggle">
          <span>RG Edge Len<span class="info-icon" data-tooltip="Controls spacing between resource groups within this subscription. Increase (5-8) if groups overlap. Auto-recommendation: 4 base, +1 if >8 RGs, +2 if >15 RGs."><i class="fas fa-info-circle"></i></span></span>
          <input type="number" class="per-sub-edge-input" id="sub-rgedge-${i}" value="4" min="1" max="10" onchange="refreshPreview()">
        </label>
      </div>
    `;
    grid.appendChild(row);
  });

  refreshPreview();
}

function toggleMini(el, event) {
  // Stop propagation so the parent <label> doesn't double-toggle the checkbox
  if (event) { event.stopPropagation(); event.preventDefault(); }
  const cb = el.previousElementSibling;
  if (cb && cb.type === 'checkbox') {
    cb.checked = !cb.checked;
    refreshPreview();
  }
}

// ─── File Handling (Bicep Mode) ───
async function pickBicepFiles() {
  const a = api();
  if (!a) return;
  try {
    const files = await a.pick_files('bicep');
    if (files && files.length > 0) {
      state.bicepFiles = files;
      renderFileChips('bicep');
      refreshPreview();
    }
  } catch (e) {
    showToast('Bicep file picker failed', 'error');
  }
}

async function pickTerraformMainFiles() {
  const a = api();
  if (!a) return;
  try {
    const files = await a.pick_files('terraform-main');
    if (files && files.length > 0) {
      const accepted = files.filter(file => file.replace(/\\/g, '/').endsWith('/main.tf') || file === 'main.tf');
      const rejected = files.length - accepted.length;
      state.terraformMainFiles = mergeUniqueFiles(state.terraformMainFiles, accepted);
      renderFileChips('terraform-main');
      refreshPreview();
      if (rejected > 0) {
        showToast('Terraform mode only accepts files named main.tf', 'warning');
      }
    }
  } catch (e) {
    showToast('Terraform main.tf picker failed', 'error');
  }
}

async function pickTerraformVarFiles() {
  const a = api();
  if (!a) return;
  try {
    const files = await a.pick_files('terraform-vars');
    if (files && files.length > 0) {
      const accepted = files.filter(file => file.toLowerCase().endsWith('.tfvars'));
      const rejected = files.length - accepted.length;
      state.terraformVarFiles = mergeUniqueFiles(state.terraformVarFiles, accepted);
      renderFileChips('terraform-vars');
      refreshPreview();
      if (rejected > 0) {
        showToast('Terraform mode only accepts files ending in .tfvars', 'warning');
      }
    }
  } catch (e) {
    showToast('Terraform tfvars picker failed', 'error');
  }
}

async function pickParamFiles() {
  const a = api();
  if (!a) return;
  try {
    const files = await a.pick_files('params');
    if (files && files.length > 0) {
      state.paramFiles = files;
      renderFileChips('params');
      await parseBicepParamsMetadata();
      refreshPreview();
    }
  } catch (e) {
    showToast('Parameter file picker failed', 'error');
  }
}

async function parseBicepParamsMetadata() {
  const a = api();
  if (!a || state.paramFiles.length === 0) {
    state.bicepSubscriptions = [];
    state.templateSubMap = [];
    renderBicepPerSubControls();
    return;
  }
  try {
    const result = await a.parse_params_metadata(state.paramFiles);
    if (result.errors && result.errors.length > 0) {
      result.errors.forEach(err => showToast(err, 'warning'));
    }
    state.bicepSubscriptions = result.subscriptions || [];
    state.templateSubMap = result.templateSubMap || [];
  } catch (e) {
    state.bicepSubscriptions = [];
    state.templateSubMap = [];
    showToast('Failed to parse parameter metadata', 'error');
  }
  renderBicepPerSubControls();
}

function renderBicepPerSubControls() {
  renderOfflinePerSubControls({
    containerId: 'bicep-per-sub-options',
    gridId: 'bicep-per-sub-grid',
    subscriptions: state.bicepSubscriptions,
    prefix: 'bicep'
  });
}

function renderOfflinePerSubControls({ containerId, gridId, subscriptions, prefix }) {
  const container = document.getElementById(containerId);
  const grid = document.getElementById(gridId);
  if (!container || !grid) return;

  if (!subscriptions || subscriptions.length === 0) {
    container.classList.add('hidden');
    grid.innerHTML = '';
    return;
  }

  container.classList.remove('hidden');
  grid.innerHTML = '';

  subscriptions.forEach((sub, i) => {
    const shortId = sub.id.length > 16 ? sub.id.substring(0, 12) + '...' : sub.id;
    const rgList = (sub.resourceGroups || []).join(', ');
    const rgCount = (sub.resourceGroups || []).length;
    const recommendSubnetOpt = rgCount > 6;
    const baseEdge = Math.min(4 + (rgCount > 8 ? 1 : 0) + (rgCount > 15 ? 2 : 0), 8);

    const row = document.createElement('div');
    row.className = 'per-sub-row';
    row.innerHTML = `
      <div class="per-sub-row-header">
        <i class="fas fa-layer-group"></i> Subscription ${i + 1}: ${shortId}
        <span class="per-sub-rg-hint">(${rgCount} RG${rgCount !== 1 ? 's' : ''}${rgList ? ': ' + rgList : ''})</span>
      </div>
      <div class="per-sub-toggles">
        <label class="per-sub-toggle">
          <span>Subnet Opt<span class="info-icon" data-tooltip="Hides subnets that don't have VNet integration. Useful to avoid plotting all subnets in a Landing Zone VNet and keep only those linked to Private Endpoints."><i class="fas fa-info-circle"></i></span></span>
          <input type="checkbox" id="${prefix}-sub-subnet-${i}" ${recommendSubnetOpt ? 'checked' : ''} onchange="refreshPreview()">
          <span class="mini-toggle" onclick="toggleMini(this, event)"></span>
        </label>
        <label class="per-sub-toggle">
          <span>PE Opt<span class="info-icon" data-tooltip="Groups and moves Private Endpoints by their subnet context for a cleaner layout. Enabled by default."><i class="fas fa-info-circle"></i></span></span>
          <input type="checkbox" id="${prefix}-sub-pe-${i}" checked onchange="refreshPreview()">
          <span class="mini-toggle" onclick="toggleMini(this, event)"></span>
        </label>
        <label class="per-sub-toggle">
          <span>Cross-PE Opt<span class="info-icon" data-tooltip="Hides Private Endpoints that have no cross-tenant dependencies with resources (not VNet integration). Enable for performance and clarity in multi-tenant architectures."><i class="fas fa-info-circle"></i></span></span>
          <input type="checkbox" id="${prefix}-sub-crosspe-${i}" onchange="refreshPreview()">
          <span class="mini-toggle" onclick="toggleMini(this, event)"></span>
        </label>
        <label class="per-sub-toggle">
          <span>RG Edge Len<span class="info-icon" data-tooltip="Controls spacing between resource groups within this subscription. Increase (5-8) if groups overlap. Auto-recommendation: 4 base, +1 if >8 RGs, +2 if >15 RGs."><i class="fas fa-info-circle"></i></span></span>
          <input type="number" class="per-sub-edge-input" id="${prefix}-sub-rgedge-${i}" value="${baseEdge}" min="1" max="10" onchange="refreshPreview()">
        </label>
      </div>
    `;
    grid.appendChild(row);
  });

  refreshPreview();
}

function handleDragOver(e) {
  e.preventDefault();
  e.currentTarget.classList.add('drag-over');
}
function handleDragLeave(e) {
  e.currentTarget.classList.remove('drag-over');
}
function handleDrop(e, type) {
  e.preventDefault();
  e.currentTarget.classList.remove('drag-over');
  // Note: pywebview may not support drag-and-drop file paths directly
  // Users should use the browse button
  showToast('Use the browse button to select files', 'info');
}

function renderFileChips(type) {
  const list = getFileList(type);
  const container = document.getElementById(`file-list-${type}`);
  container.innerHTML = list.map((f, i) => {
    const name = f.split(/[/\\]/).pop();
    return `<span class="file-chip">
      <i class="fas fa-file-code"></i>
      ${name}
      <span class="remove-file" onclick="removeFile('${type}', ${i})">&times;</span>
    </span>`;
  }).join('');
}

function removeFile(type, index) {
  if (type === 'bicep') {
    state.bicepFiles.splice(index, 1);
  } else if (type === 'params') {
    state.paramFiles.splice(index, 1);
    // Re-parse metadata after removing a param file
    parseBicepParamsMetadata();
  } else if (type === 'terraform-main') {
    state.terraformMainFiles.splice(index, 1);
  } else {
    state.terraformVarFiles.splice(index, 1);
  }
  renderFileChips(type);
  refreshPreview();
}

function getFileList(type) {
  if (type === 'bicep') return state.bicepFiles;
  if (type === 'params') return state.paramFiles;
  if (type === 'terraform-main') return state.terraformMainFiles;
  if (type === 'terraform-vars') return state.terraformVarFiles;
  return [];
}

function mergeUniqueFiles(existingFiles, newFiles) {
  const merged = [...(existingFiles || [])];
  for (const file of newFiles || []) {
    if (!merged.includes(file)) {
      merged.push(file);
    }
  }
  return merged;
}

function terraformRootDirsFromMainFiles(mainFiles) {
  return (mainFiles || []).map(path => {
    const normalized = path.replace(/\\/g, '/');
    const parts = normalized.split('/');
    parts.pop();
    return parts.join('/') || '.';
  });
}

// ─── Build Command ───
function buildCommandArgs() {
  const args = {};
  args.mode = state.mode;
  args.authMethod = state.authMethod;

  // Service Principal credentials (only when SP auth selected in live mode)
  if (state.mode === 'live' && state.authMethod === 'service-principal') {
    args.servicePrincipal = {
      clientId: document.getElementById('input-sp-client-id').value.trim(),
      tenantId: document.getElementById('input-sp-tenant-id').value.trim(),
      secret: document.getElementById('input-sp-secret').value
    };
  }

  if (state.mode === 'live') {
    args.tenants = document.getElementById('input-tenants').value.trim();
    args.subscriptions = document.getElementById('input-subscriptions').value.trim();
    args.resourcegroups = document.getElementById('input-resourcegroups').value.trim();
    args.discoverResourceGroups = Array.from(discoveryStore);
  } else if (state.mode === 'terraform') {
    args.terraformRootDirs = terraformRootDirsFromMainFiles(state.terraformMainFiles);
    args.terraformVarFiles = state.terraformVarFiles;
  } else {
    args.bicepFiles = state.bicepFiles;
    args.parametersFiles = state.paramFiles;
  }

  args.edgeDirection = document.getElementById('sel-edge-direction').value;
  args.tenantDirection = document.getElementById('sel-tenant-direction').value;
  args.maxSubnetPerline = document.getElementById('input-max-subnet').value;
  args.resourcesEdgeLength = document.getElementById('input-res-edge-len').value;
  args.privateDnsZonesOptimization = document.getElementById('chk-dns-opt').checked;
  args.rankDebug = document.getElementById('chk-rank-debug').checked;
  args.exportDrawio = document.getElementById('chk-export-drawio').checked;

  // Per-subscription arrays
  if (state.mode === 'live') {
    const subs = args.subscriptions ? args.subscriptions.split(/\s+/) : [];
    args.subnetOptimization = [];
    args.peOptimization = [];
    args.crossPeOptimization = [];
    args.resourceGroupsEdgeLengthListBySubscription = [];

    for (let i = 0; i < subs.length; i++) {
      const subEl = document.getElementById(`sub-subnet-${i}`);
      const peEl = document.getElementById(`sub-pe-${i}`);
      const crossEl = document.getElementById(`sub-crosspe-${i}`);
      const edgeEl = document.getElementById(`sub-rgedge-${i}`);
      args.subnetOptimization.push(subEl ? subEl.checked : false);
      args.peOptimization.push(peEl ? peEl.checked : true);
      args.crossPeOptimization.push(crossEl ? crossEl.checked : false);
      args.resourceGroupsEdgeLengthListBySubscription.push(edgeEl ? parseInt(edgeEl.value) || 4 : 4);
    }
  } else if (state.mode === 'bicep') {
    applyOfflinePerSubscriptionArgs(args, state.bicepSubscriptions, state.templateSubMap, 'bicep');
  }

  return args;
}

function applyOfflinePerSubscriptionArgs(args, subscriptions, templateSubMap, prefix) {
  if (!subscriptions || subscriptions.length === 0 || !templateSubMap || templateSubMap.length === 0) return;

  const uniqueSubnet = [];
  const uniquePe = [];
  const uniqueCross = [];
  const uniqueEdge = [];
  for (let i = 0; i < subscriptions.length; i++) {
    const subEl = document.getElementById(`${prefix}-sub-subnet-${i}`);
    const peEl = document.getElementById(`${prefix}-sub-pe-${i}`);
    const crossEl = document.getElementById(`${prefix}-sub-crosspe-${i}`);
    const edgeEl = document.getElementById(`${prefix}-sub-rgedge-${i}`);
    uniqueSubnet.push(subEl ? subEl.checked : false);
    uniquePe.push(peEl ? peEl.checked : true);
    uniqueCross.push(crossEl ? crossEl.checked : false);
    uniqueEdge.push(edgeEl ? parseInt(edgeEl.value) || 4 : 4);
  }

  args.subnetOptimization = [];
  args.peOptimization = [];
  args.crossPeOptimization = [];
  args.resourceGroupsEdgeLengthListBySubscription = [];
  for (const idx of templateSubMap) {
    const si = idx >= 0 ? idx : 0;
    args.subnetOptimization.push(uniqueSubnet[si] ?? false);
    args.peOptimization.push(uniquePe[si] ?? true);
    args.crossPeOptimization.push(uniqueCross[si] ?? false);
    args.resourceGroupsEdgeLengthListBySubscription.push(uniqueEdge[si] ?? 4);
  }
}

function buildCommandString() {
  const args = buildCommandArgs();
  let parts = ['python3', 'src/main.py'];

  if (args.authMethod === 'service-principal') {
    parts.push('--authMethod', 'service-principal');
  }

  if (state.mode === 'live') {
    if (args.tenants) parts.push('--tenants', ...args.tenants.split(/\s+/));
    if (args.subscriptions) parts.push('--subscriptions', ...args.subscriptions.split(/\s+/));
    if (args.resourcegroups) parts.push('--resourcegroups', ...args.resourcegroups.split(/\s+/));
    if (args.discoverResourceGroups && args.discoverResourceGroups.length > 0) parts.push('--discoverResourceGroups', ...args.discoverResourceGroups);
  } else if (state.mode === 'terraform') {
    if (args.terraformRootDirs.length) parts.push('--terraformRootDirs', ...args.terraformRootDirs);
    if (args.terraformVarFiles.length) parts.push('--terraformVarFiles', ...args.terraformVarFiles);
  } else {
    if (args.bicepFiles.length) parts.push('--bicepFiles', ...args.bicepFiles);
    if (args.parametersFiles.length) parts.push('--parametersFiles', ...args.parametersFiles);
  }

  parts.push('--edgeDirection', args.edgeDirection);
  parts.push('--tenantDirection', args.tenantDirection);
  parts.push('--maxSubnetPerline', args.maxSubnetPerline);
  parts.push('--resourcesEdgeLength', args.resourcesEdgeLength);
  parts.push('--rankDebug', args.rankDebug ? 'true' : 'false');
  parts.push('--privateDnsZonesOptimization', args.privateDnsZonesOptimization ? 'true' : 'false');
  if (args.exportDrawio) parts.push('--exportDrawio', 'true');

  if (args.subnetOptimization && args.subnetOptimization.length > 0) {
    parts.push('--subnetOptimization', ...args.subnetOptimization.map(v => v ? 'true' : 'false'));
    parts.push('--peOptimization', ...args.peOptimization.map(v => v ? 'true' : 'false'));
    parts.push('--crossPeOptimization', ...args.crossPeOptimization.map(v => v ? 'true' : 'false'));
    parts.push('--resourceGroupsEdgeLengthListBySubscription',
      ...args.resourceGroupsEdgeLengthListBySubscription.map(String));
  }

  return parts.join(' ');
}

function refreshPreview() {
  const preview = document.getElementById('command-preview');
  const cmd = buildCommandString();
  // Mask subscription/tenant IDs for display
  const masked = cmd.replace(
    /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/gi,
    (m) => m.substring(0, 8) + '...'
  );
  preview.innerHTML = `<code>${escapeHtml(masked)}</code>`;
}

async function copyCommand() {
  const cmd = buildCommandString();
  try {
    await copyToClipboard(cmd);
    showToast('Command copied to clipboard', 'success');
  } catch {
    showToast('Failed to copy', 'error');
  }
}

// ─── Validation ───
function validate() {
  if (state.mode === 'live') {
    const tenants = document.getElementById('input-tenants').value.trim();
    const subs = document.getElementById('input-subscriptions').value.trim();
    const rgs = document.getElementById('input-resourcegroups').value.trim();

    if (!tenants) { showToast('Tenant IDs required', 'error'); return false; }
    if (!subs) { showToast('Subscription IDs required', 'error'); return false; }
    if (!rgs) { showToast('Resource Groups required', 'error'); return false; }

    // Service Principal field validation
    if (state.authMethod === 'service-principal') {
      const spCid = document.getElementById('input-sp-client-id').value.trim();
      const spTid = document.getElementById('input-sp-tenant-id').value.trim();
      if (!spCid) { showToast('Service Principal Client ID required', 'error'); return false; }
      if (!spTid) { showToast('Service Principal Tenant ID required', 'error'); return false; }
      if (!document.getElementById('input-sp-secret').value) {
        showToast('Client secret required', 'error'); return false;
      }
    }
  } else {
    if (state.mode === 'bicep' && state.bicepFiles.length === 0) {
      showToast('Select Bicep template files', 'error');
      return false;
    }
    if (state.mode === 'bicep' && state.paramFiles.length === 0) {
      showToast('Select parameter files', 'error');
      return false;
    }
    if (state.mode === 'bicep' && state.bicepFiles.length !== state.paramFiles.length) {
      showToast('Bicep & parameter file counts must match', 'error');
      return false;
    }
    if (state.mode === 'terraform' && state.terraformMainFiles.length === 0) {
      showToast('Select Terraform main.tf files', 'error');
      return false;
    }
    if (
      state.mode === 'terraform' &&
      state.terraformVarFiles.length === 0
    ) {
      showToast('Select Terraform tfvars files', 'error');
      return false;
    }
    if (
      state.mode === 'terraform' &&
      state.terraformMainFiles.length !== state.terraformVarFiles.length
    ) {
      showToast('Terraform main.tf and tfvars file counts must match', 'error');
      return false;
    }
  }
  return true;
}

// ─── Generate ───
async function generate() {
  if (!validate()) return;
  if (state.running) return;

  const a = api();
  if (!a) {
    showToast('Backend not connected', 'error');
    return;
  }

  state.running = true;
  setStatus('running', 'Generating...');
  showProgress(true);
  clearConsole();
  appendConsole('[CloudHorus] 🦅 The Guardian takes flight...', 'info');
  startAuthPolling();

  // Launch eagle flight animation & start soaring
  launchEagleFlight();
  startEagleSoar();

  // Clear previous diagram to avoid showing stale/outdated image
  const prevViewer = document.getElementById('viewer-section');
  const prevImg = document.getElementById('viewer-img');
  prevViewer.classList.add('hidden');
  prevImg.removeAttribute('src');
  state.lastGeneratedFile = null;

  // Hide horizontal splitter and restore console to normal
  const hSplitter = document.getElementById('h-splitter');
  if (hSplitter) hSplitter.classList.add('hidden');
  const consoleSection = document.getElementById('console-section');
  if (consoleSection) {
    consoleSection.classList.remove('minimized', 'maximized');
    consoleSection.style.flex = '';
  }
  prevViewer.classList.remove('minimized', 'maximized');
  prevViewer.style.flex = '';

  document.getElementById('btn-generate').classList.add('hidden');
  document.getElementById('btn-stop').classList.remove('hidden');
  document.getElementById('btn-view').disabled = true;

  try {
    const args = buildCommandArgs();
    const result = await a.start_generation(JSON.stringify(args));

    if (result && result.success) {
      state.lastGeneratedFile = result.file;
      setStatus('ready', 'Complete');
      showToast('🦅 Divine insight delivered!', 'success');
      appendConsole('[CloudHorus] 🦅 Generation complete: ' + (result.file || ''), 'success');
      document.getElementById('btn-view').disabled = false;
      // Check for DrawIO file (only if export was enabled)
      if (document.getElementById('chk-export-drawio').checked) {
        checkDrawIOAvailable(result.file);
      }
      // Victory eagle flight
      launchEagleFlight();

      // Auto-show the image
      if (result.file) {
        showImage(result.file);
      }
    } else {
      setStatus('error', 'Failed');
      showToast('Generation failed', 'error');
    }
  } catch (err) {
    setStatus('error', 'Error');
    appendConsole('[Error] ' + err.message, 'error');
    showToast('Generation error: ' + err.message, 'error');
  } finally {
    state.running = false;
    showProgress(false);
    stopAuthPolling();
    stopEagleSoar();
    document.getElementById('btn-generate').classList.remove('hidden');
    document.getElementById('btn-stop').classList.add('hidden');
  }
}

async function stopGeneration() {
  const a = api();
  if (a) {
    await a.stop_generation();
    setStatus('ready', 'Stopped');
    showToast('Guardian recalled', 'warning');
  }
  state.running = false;
  showProgress(false);
  stopAuthPolling();
  stopEagleSoar();
  document.getElementById('btn-generate').classList.remove('hidden');
  document.getElementById('btn-stop').classList.add('hidden');
}

// ─── View Result ───
async function viewResult() {
  const a = api();
  if (a && state.lastGeneratedFile) {
    await a.open_file(state.lastGeneratedFile);
  }
}

// ─── DrawIO Support ───
function checkDrawIOAvailable(pngPath) {
  const btn = document.getElementById('btn-drawio');
  if (!btn || !pngPath) return;

  // Derive .drawio path directly from the PNG path (no Python round-trip needed)
  const drawioPath = pngPath.replace(/\.png$/i, '.drawio');
  state.drawioFile = drawioPath;
  btn.style.display = '';
  btn.disabled = false;
  appendConsole('[CloudHorus] 📐 DrawIO file expected at: ' + drawioPath, 'success');
}

async function openDrawIO() {
  const a = api();
  if (!a) {
    showToast('API not available', 'warning');
    return;
  }

  // If we have a known drawio path, open its folder
  if (state.drawioFile) {
    try {
      const ok = await a.open_file_location(state.drawioFile);
      if (ok) {
        showToast('📐 Opened folder with DrawIO file', 'success');
      } else {
        showToast('Could not open folder', 'warning');
      }
    } catch (e) {
      showToast('Error opening folder: ' + e.message, 'warning');
    }
  } else if (state.lastGeneratedFile) {
    // Fallback: open the folder of the last generated file
    try {
      await a.open_file_location(state.lastGeneratedFile);
      showToast('📐 Opened output folder', 'info');
    } catch (e) {
      showToast('Error opening folder: ' + e.message, 'warning');
    }
  } else {
    showToast('No generated file to locate', 'warning');
  }
}

async function showImage(filePath) {
  const viewer = document.getElementById('viewer-section');
  const img = document.getElementById('viewer-img');

  // Force clear previous image before loading new one
  img.removeAttribute('src');
  viewer.classList.remove('hidden');

  // Show the horizontal splitter now that both sections are visible
  const hSplitter = document.getElementById('h-splitter');
  if (hSplitter) hSplitter.classList.remove('hidden');

  // Auto-maximize viewer for best diagram viewing
  const consoleSection = document.getElementById('console-section');
  if (consoleSection && viewer) {
    consoleSection.style.flex = '';
    viewer.style.flex = '';
    consoleSection.classList.add('minimized');
    consoleSection.classList.remove('maximized');
    viewer.classList.add('maximized');
    viewer.classList.remove('minimized');
    updateToggleIcons();
  }

  // Use base64 data URL via backend (avoids file:// CORS issues in HTTP mode)
  const a = api();
  if (a) {
    const dataUrl = await a.get_image_base64(filePath);
    if (dataUrl) {
      img.src = dataUrl;
    } else {
      img.src = 'file://' + filePath + '?t=' + Date.now();
    }
  }

  state.viewerZoom = 1;
  img.style.transform = 'scale(1)';
  initPanZoom();

  // Scroll to viewer with slight delay to ensure image is rendered
  requestAnimationFrame(() => {
    viewer.scrollIntoView({ behavior: 'smooth' });
  });
}

// ─── Pan & Zoom for Viewer ───
function initPanZoom() {
  const canvas = document.getElementById('viewer-canvas');
  const img = document.getElementById('viewer-img');
  let isPanning = false;
  let startX, startY, scrollLeft, scrollTop;

  // Remove old listeners to avoid duplicates
  canvas.onmousedown = (e) => {
    isPanning = true;
    canvas.style.cursor = 'grabbing';
    startX = e.pageX - canvas.offsetLeft;
    startY = e.pageY - canvas.offsetTop;
    scrollLeft = canvas.scrollLeft;
    scrollTop = canvas.scrollTop;
  };
  canvas.onmouseup = () => { isPanning = false; canvas.style.cursor = 'grab'; };
  canvas.onmouseleave = () => { isPanning = false; canvas.style.cursor = 'grab'; };
  canvas.onmousemove = (e) => {
    if (!isPanning) return;
    e.preventDefault();
    const x = e.pageX - canvas.offsetLeft;
    const y = e.pageY - canvas.offsetTop;
    canvas.scrollLeft = scrollLeft - (x - startX);
    canvas.scrollTop = scrollTop - (y - startY);
  };

  // Mouse wheel zoom
  canvas.onwheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    state.viewerZoom = Math.max(0.1, Math.min(5, state.viewerZoom * delta));
    img.style.transform = `scale(${state.viewerZoom})`;
  };
}

function openExternal() {
  const a = api();
  if (a && state.lastGeneratedFile) {
    a.open_file(state.lastGeneratedFile);
  }
}

// ─── Viewer Zoom ───
function zoomIn() {
  state.viewerZoom = Math.min(state.viewerZoom * 1.25, 5);
  document.getElementById('viewer-img').style.transform = `scale(${state.viewerZoom})`;
}
function zoomOut() {
  state.viewerZoom = Math.max(state.viewerZoom * 0.8, 0.1);
  document.getElementById('viewer-img').style.transform = `scale(${state.viewerZoom})`;
}
function zoomReset() {
  state.viewerZoom = 1;
  document.getElementById('viewer-img').style.transform = 'scale(1)';
}

// ─── Fullscreen Viewer ───
function toggleFullscreen() {
  const viewer = document.getElementById('viewer-section');
  const btn = document.getElementById('btn-fullscreen');
  if (!viewer) return;

  const app = document.getElementById('app');
  const isFullscreen = app.classList.contains('viewer-fullscreen');

  if (isFullscreen) {
    // Exit in-app fullscreen
    app.classList.remove('viewer-fullscreen');
    const icon = btn.querySelector('i');
    icon.className = 'fas fa-expand-arrows-alt';
    btn.title = 'Fullscreen';
  } else {
    // Enter in-app fullscreen — viewer takes the whole window
    app.classList.add('viewer-fullscreen');
    const icon = btn.querySelector('i');
    icon.className = 'fas fa-compress-arrows-alt';
    btn.title = 'Exit fullscreen';
  }
}

// Also support Escape key to exit in-app fullscreen
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const app = document.getElementById('app');
    if (app && app.classList.contains('viewer-fullscreen')) {
      toggleFullscreen();
    }
  }
});

// ─── Console ───
// Strip ANSI escape codes from text
function stripAnsi(str) {
  return str.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '').replace(/\r/g, '');
}

// Detect tqdm / progress-bar lines (e.g. "Processing: 50%|████")
function isProgressLine(text) {
  return /\d+%\|/.test(text) || /\|[█▓▒░ ]*\|/.test(text);
}

// Extract progress label prefix for matching (e.g. "Processing Resources")
function progressKey(text) {
  const m = text.match(/^(.*?)\s*:?\s*\d+%/);
  return m ? m[1].trim() : '__progress__';
}

function appendConsole(text, tag) {
  const container = document.getElementById('console-output');
  const clean = stripAnsi(text);
  if (!clean.trim()) return; // skip empty lines

  // Handle tqdm progress bars: update in-place instead of appending
  if (isProgressLine(clean)) {
    const key = progressKey(clean);
    // Look for an existing progress line with same key
    let existing = container.querySelector(`.console-line[data-progress-key="${CSS.escape(key)}"]`);
    if (existing) {
      existing.textContent = clean;
      existing.className = 'console-line progress-update ' + (tag || '');
      container.scrollTop = container.scrollHeight;
      return;
    }
    // First occurrence: create with data attribute
    const line = document.createElement('div');
    line.className = 'console-line progress-update ' + (tag || '');
    line.setAttribute('data-progress-key', key);
    line.textContent = clean;
    container.appendChild(line);
    container.scrollTop = container.scrollHeight;
    return;
  }

  const line = document.createElement('div');
  line.className = 'console-line ' + (tag || '');

  // Parse prefix
  const prefixMatch = clean.match(/^\[([^\]]+)\]/);
  if (prefixMatch) {
    const prefix = prefixMatch[0];
    const rest = clean.substring(prefix.length);
    line.innerHTML = `<span class="console-prefix">${escapeHtml(prefix)}</span>${escapeHtml(rest)}`;
  } else {
    line.textContent = clean;
  }

  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
}

function clearConsole() {
  document.getElementById('console-output').innerHTML = '';
}

function scrollConsoleBottom() {
  const c = document.getElementById('console-output');
  c.scrollTop = c.scrollHeight;
}

// ─── Output Polling ───
let outputPollTimer = null;
let _lastOutputTime = 0;          // epoch-ms of last received output
const _SILENCE_THRESHOLD = 5000;  // ms before showing "still working"

function startOutputPolling() {
  _lastOutputTime = Date.now();
  _authzErrorShown = false;  // reset so a new run can re-trigger the modal
  outputPollTimer = setInterval(async () => {
    const a = api();
    if (!a) return;
    try {
      const lines = await a.get_output_lines();
      if (lines && lines.length > 0) {
        _lastOutputTime = Date.now();
        lines.forEach(line => {
          let tag = '';
          const lower = line.toLowerCase();
          if (lower.includes('error') || lower.includes('traceback') || lower.includes('exception')) tag = 'error';
          else if (lower.includes('warning') || lower.includes('warn')) tag = 'warning';
          else if (lower.includes('success') || lower.includes('complete') || lower.includes('done')) tag = 'success';
          else tag = 'info';
          appendConsole(line, tag);
          // Detect Azure authorization / RBAC failures and surface a sticky red modal.
          // Cross-tenant noise is logged at DEBUG (not emitted to stdout) so anything
          // that reaches this point is a real access problem the user must see.
          maybeShowAuthzError(line);
        });
        // Update progress based on output
        updateProgressFromOutput(lines);
      } else {
        // Client-side silence detection: if no output for a while,
        // pulse the progress text so the UI never looks frozen.
        const silence = Date.now() - _lastOutputTime;
        if (silence >= _SILENCE_THRESHOLD) {
          const text = document.getElementById('progress-text');
          if (text && !text.textContent.includes('Complete')) {
            const secs = Math.round(silence / 1000);
            text.textContent = `Still working... (${secs}s)`;
          }
        }
      }
    } catch (e) { /* ignore polling errors */ }
  }, 300);
}

function updateProgressFromOutput(lines) {
  const fill = document.getElementById('progress-fill');
  const text = document.getElementById('progress-text');

  // Process ALL lines in the batch (not just the last one) so we never
  // miss a progress marker buried in a burst of output.
  for (const rawLine of lines) {
    // Strip the logger filename suffix  e.g. "(graph_generator.py:1210)"
    // to avoid false matches on words like "graph" in filenames.
    const line = rawLine.replace(/\s*\([^)]+\.py:\d+\)\s*$/, '');

    // ── 1. tqdm progress bars: "Processing Resources in RG: 42%|████  | 289/1091" ──
    const tqdmMatch = rawLine.match(/(\d+)%\|[^|]*\|\s*(\d+)\/(\d+)/);
    if (tqdmMatch) {
      const pct = parseInt(tqdmMatch[1], 10);
      const current = parseInt(tqdmMatch[2], 10);
      const total = parseInt(tqdmMatch[3], 10);
      // Map tqdm 0-100% to [30..60%] of overall bar
      const mapped = 30 + Math.round((pct / 100) * 30);
      fill.style.width = Math.min(mapped, 60) + '%';
      text.textContent = `Processing resources ${current}/${total} (${pct}%)...`;
      continue;
    }

    // ── 2. Fallback heuristic indicators (filename-safe) ──
    const indicators = [
      { match: /auth/i,                             pct: 10, label: 'Authenticating...' },
      { match: /export.*template|scan|discover/i,   pct: 20, label: 'Fetching resources...' },
      { match: /processing resources/i,             pct: 30, label: 'Processing...' },
      { match: /saving diagram|\.png/i,             pct: 75, label: 'Rendering PNG...' },
      { match: /draw\.io|drawio.*xml/i,             pct: 87, label: 'Exporting Draw.io...' },
      { match: /generation completed/i,             pct: 95, label: 'Finalizing...' },
      { match: /opened diagram|success/i,           pct: 100, label: 'Complete!' },
    ];

    for (const ind of indicators) {
      if (ind.match.test(line)) {
        fill.style.width = ind.pct + '%';
        text.textContent = ind.label;
        break;
      }
    }
  }
}

// ─── Auth Polling ───
let authPollTimer = null;
function startAuthPolling() {
  if (authPollTimer) return; // already running
  authPollTimer = setInterval(async () => {
    const a = api();
    if (!a) return;
    try {
      const auth = await a.check_auth_prompt();
      if (auth && auth.url) {
        showAuthModal(auth.url, auth.code, auth.expires_on);
      }
    } catch (e) { /* ignore */ }
  }, 2000);
}
function stopAuthPolling() {
  if (authPollTimer) {
    clearInterval(authPollTimer);
    authPollTimer = null;
  }
  closeAuthModal();
}

let _authCountdownTimer = null;

function showAuthModal(url, code, expiresOn) {
  document.getElementById('auth-url').textContent = url;
  document.getElementById('auth-code').textContent = code;
  document.getElementById('auth-modal').classList.remove('hidden');

  // Start live countdown if we have an ISO timestamp
  _startAuthCountdown(expiresOn);
}

function _startAuthCountdown(expiresOnIso) {
  // Clear any previous countdown
  if (_authCountdownTimer) {
    clearInterval(_authCountdownTimer);
    _authCountdownTimer = null;
  }

  const expiryEl = document.getElementById('auth-expiry');
  const spanEl = document.getElementById('auth-expires');

  if (!expiresOnIso) {
    spanEl.textContent = '15 minutes';
    expiryEl.classList.remove('auth-expiry--warn', 'auth-expiry--critical');
    return;
  }

  const deadline = new Date(expiresOnIso).getTime();
  if (isNaN(deadline)) {
    spanEl.textContent = '15 minutes';
    return;
  }

  function tick() {
    const now = Date.now();
    const left = Math.max(0, Math.floor((deadline - now) / 1000));
    const m = Math.floor(left / 60);
    const s = left % 60;
    const pad = (n) => String(n).padStart(2, '0');
    spanEl.textContent = `${pad(m)}:${pad(s)}`;

    // Visual urgency classes
    expiryEl.classList.toggle('auth-expiry--warn', left <= 120 && left > 30);
    expiryEl.classList.toggle('auth-expiry--critical', left <= 30);

    if (left <= 0) {
      clearInterval(_authCountdownTimer);
      _authCountdownTimer = null;
      spanEl.textContent = 'EXPIRED';
      expiryEl.classList.add('auth-expiry--critical');
    }
  }

  tick(); // immediate first render
  _authCountdownTimer = setInterval(tick, 1000);
}

function closeAuthModal() {
  document.getElementById('auth-modal').classList.add('hidden');
  if (_authCountdownTimer) {
    clearInterval(_authCountdownTimer);
    _authCountdownTimer = null;
  }
  const expiryEl = document.getElementById('auth-expiry');
  expiryEl.classList.remove('auth-expiry--warn', 'auth-expiry--critical');
}

async function copyAuthUrl() {
  const url = document.getElementById('auth-url').textContent;
  await copyToClipboard(url);
  showToast('URL copied', 'success');
}

async function copyAuthCode() {
  const code = document.getElementById('auth-code').textContent;
  await copyToClipboard(code);
  showToast('Code copied', 'success');
}

// ─── Status & Progress ───
function setStatus(type, text) {
  const chip = document.getElementById('status-chip');
  const dot = chip.querySelector('.status-dot');
  const label = chip.querySelector('.status-text');
  label.textContent = text;

  dot.style.background = {
    ready: 'var(--accent-green)',
    running: 'var(--accent-primary)',
    error: 'var(--accent-red)',
  }[type] || 'var(--accent-green)';

  if (type === 'running') {
    dot.style.animation = 'pulse-dot 0.8s infinite';
  } else {
    dot.style.animation = 'pulse-dot 2s infinite';
  }
}

function showProgress(show) {
  const container = document.getElementById('progress-container');
  const fill = document.getElementById('progress-fill');
  if (show) {
    container.classList.remove('hidden');
    fill.style.width = '5%';
  } else {
    fill.style.width = '100%';
    setTimeout(() => container.classList.add('hidden'), 600);
  }
}

// ─── Toast Notifications ───
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icons = { info: 'fa-info-circle', success: 'fa-check-circle', error: 'fa-exclamation-circle', warning: 'fa-exclamation-triangle' };
  toast.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ─── Authorization Error Detection (sticky red modal) ───
// Patterns matched against streamed log lines. Cross-tenant expected noise is
// already silenced at the backend (DEBUG level), so anything reaching the UI
// indicates a real RBAC / identity problem the user must address.
const AUTHZ_ERROR_PATTERNS = [
  /AuthorizationFailed/i,
  /does not have authorization to perform action/i,
  /AADSTS70011/i,             // invalid scope
  /AADSTS700016/i,            // app not found in tenant
  /AADSTS7000215/i,           // invalid client secret
  /AADSTS7000222/i,           // expired client secret
  /AADSTS900023/i,            // invalid tenant identifier
  /InvalidAuthenticationToken(?!Tenant)/i, // exclude cross-tenant variant
  /ClientAuthenticationError/i,
];
let _authzErrorShown = false;

function maybeShowAuthzError(line) {
  if (_authzErrorShown) return;
  if (!AUTHZ_ERROR_PATTERNS.some(rx => rx.test(line))) return;
  _authzErrorShown = true;
  const modal = document.getElementById('authz-error-modal');
  const msgEl = document.getElementById('authz-error-message');
  if (msgEl) {
    // Show the relevant portion of the message (everything after the level marker).
    const m = line.match(/-\s*(?:WARNING|ERROR|CRITICAL)\s*-\s*(.*)$/i);
    msgEl.textContent = (m ? m[1] : line).trim();
  }
  if (modal) modal.classList.remove('hidden');
  // Also fire a toast so the user sees something even if the modal is dismissed quickly.
  showToast('Azure access denied — check identity & RBAC permissions', 'error');
}

function dismissAuthzError() {
  const modal = document.getElementById('authz-error-modal');
  if (modal) modal.classList.add('hidden');
  // Reset flag so a NEW run can re-trigger if errors recur.
  _authzErrorShown = false;
}

// ─── Particles Background ───
// Color palettes for style modes
const particlePalettes = {
  egyptian: [
    { r: 212, g: 160, b: 23 },   // Horus gold
    { r: 246, g: 211, b: 101 },   // Light gold
    { r: 196, g: 168, b: 108 },   // Sand
    { r: 0,   g: 212, b: 255 },   // Cyan (Eye of Horus)
    { r: 139, g: 105, b: 20 },    // Dark gold
  ],
  modern: [
    { r: 59,  g: 130, b: 246 },   // Blue
    { r: 96,  g: 165, b: 250 },   // Light blue
    { r: 139, g: 92,  b: 246 },   // Violet
    { r: 6,   g: 182, b: 212 },   // Cyan
    { r: 37,  g: 99,  b: 235 },   // Dark blue
  ],
};
const particleLine = {
  egyptian: { r: 212, g: 160, b: 23 },
  modern:   { r: 59,  g: 130, b: 246 },
};
let _particleInstances = [];

function updateParticleColors(styleMode) {
  const palette = particlePalettes[styleMode] || particlePalettes.egyptian;
  _particleInstances.forEach(p => {
    p.color = palette[Math.floor(Math.random() * palette.length)];
  });
}

function initParticles() {
  const canvas = document.getElementById('particles-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let w, h;
  _particleInstances = [];

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  function getColors() {
    return particlePalettes[state.styleMode] || particlePalettes.egyptian;
  }
  function getLineColor() {
    const c = particleLine[state.styleMode] || particleLine.egyptian;
    return c;
  }

  class Particle {
    constructor() { this.reset(); }
    reset() {
      this.x = Math.random() * w;
      this.y = Math.random() * h;
      this.vx = (Math.random() - 0.5) * 0.25;
      this.vy = (Math.random() - 0.5) * 0.25;
      this.r = Math.random() * 1.8 + 0.4;
      this.alpha = Math.random() * 0.4 + 0.1;
      const colors = getColors();
      this.color = colors[Math.floor(Math.random() * colors.length)];
    }
    update() {
      this.x += this.vx;
      this.y += this.vy;
      if (this.x < 0 || this.x > w) this.vx *= -1;
      if (this.y < 0 || this.y > h) this.vy *= -1;
    }
    draw() {
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${this.color.r}, ${this.color.g}, ${this.color.b}, ${this.alpha})`;
      ctx.fill();
    }
  }

  for (let i = 0; i < 50; i++) _particleInstances.push(new Particle());

  function drawLines() {
    const lc = getLineColor();
    for (let i = 0; i < _particleInstances.length; i++) {
      for (let j = i + 1; j < _particleInstances.length; j++) {
        const dx = _particleInstances[i].x - _particleInstances[j].x;
        const dy = _particleInstances[i].y - _particleInstances[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 110) {
          ctx.beginPath();
          ctx.moveTo(_particleInstances[i].x, _particleInstances[i].y);
          ctx.lineTo(_particleInstances[j].x, _particleInstances[j].y);
          ctx.strokeStyle = `rgba(${lc.r}, ${lc.g}, ${lc.b}, ${0.06 * (1 - dist / 110)})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
    }
  }

  function animate() {
    ctx.clearRect(0, 0, w, h);
    _particleInstances.forEach(p => { p.update(); p.draw(); });
    drawLines();
    requestAnimationFrame(animate);
  }
  animate();
}

// ─── Eagle Flight Animation ───
function launchEagleFlight() {
  if (state.styleMode === 'modern') return; // No eagle in modern mode
  const overlay = document.getElementById('eagle-flight-overlay');
  if (!overlay) return;
  overlay.classList.remove('hidden');
  overlay.innerHTML = '';

  // Create eagle SVG element
  const eagle = document.createElement('img');
  eagle.src = 'eagle.svg';
  eagle.className = 'eagle-svg';
  eagle.style.animationDuration = '2.5s';
  overlay.appendChild(eagle);

  // Create trailing particles
  const trailCount = 15;
  for (let i = 0; i < trailCount; i++) {
    setTimeout(() => {
      const trail = document.createElement('div');
      trail.className = 'eagle-trail';
      trail.style.left = (10 + Math.random() * 80) + '%';
      trail.style.top = (30 + Math.random() * 40) + '%';
      trail.style.width = (3 + Math.random() * 5) + 'px';
      trail.style.height = trail.style.width;
      trail.style.animationDelay = '0s';
      trail.style.background = Math.random() > 0.5
        ? 'var(--horus-gold)'
        : 'var(--horus-cyan)';
      overlay.appendChild(trail);
    }, i * 150);
  }

  // Hide after animation completes
  setTimeout(() => {
    overlay.classList.add('hidden');
    overlay.innerHTML = '';
  }, 3000);
}

function startEagleSoar() {
  if (state.styleMode === 'modern') return; // No eagle in modern mode
  const eagle = document.getElementById('eagle-soar');
  if (eagle) {
    eagle.classList.remove('hidden');
  }
  // Also add generating class to header
  const header = document.getElementById('app-header');
  if (header) header.classList.add('generating');
}

function stopEagleSoar() {
  const eagle = document.getElementById('eagle-soar');
  if (eagle) {
    eagle.classList.add('hidden');
  }
  const header = document.getElementById('app-header');
  if (header) header.classList.remove('generating');
}

// ─── Welcome Tour Guide ───
const TOUR_STEPS = [
  // ── Step 1: Welcome ──
  {
    target: '#app-header',
    title: '🦅 Welcome to CloudHorus',
    body: 'Azure Cloud Architecture Guardian — generate beautiful architecture diagrams of your Azure infrastructure.<br><br>' +
          '• The <strong>status chip</strong> (top-right) shows whether the tool is Ready, Running, or has an Error.<br>' +
          '• The <strong>ankh button</strong> <i class="fas fa-ankh"></i> switches between Egyptian and Modern UI styles.<br>' +
          '• The <strong>moon button</strong> <i class="fas fa-moon"></i> toggles Dark / Light theme.<br>' +
          '• The scrolling <strong>tips ticker</strong> shows helpful hints as you work.',
    position: 'bottom'
  },
  // ── Step 2: Mode ──
  {
    target: '.mode-section',
    title: '☁️ Choose Your Mode',
    body: '<strong>Live Azure</strong> — Connects to your real Azure subscriptions and scans actual deployed resources. ' +
          'Use this when you want to diagram what\'s currently running in Azure.<br>' +
          '<em>Example: You have a production environment with VNets, VMs, and storage — Live mode will query Azure and draw all of them.</em><br><br>' +
          '<strong>Bicep Templates</strong> — Analyzes local <code>.bicep</code> template files offline, without needing Azure access. ' +
          'Use this to visualize what your templates <em>will</em> deploy before actually deploying.<br>' +
          '<em>Example: You wrote a Bicep template that creates a VNet with subnets and a VM — Bicep mode will diagram those planned resources.</em><br><br>' +
          '<strong>Terraform</strong> — Analyzes local Terraform source offline using a <code>main.tf</code> file and a matching <code>.tfvars</code> file for each stack. ' +
          'Use this when you want CloudHorus to parse Terraform locally without requiring exported plan JSON or Azure login.<br>' +
          '<em>Example: You have a network stack and an app stack, each with a <code>main.tf</code> and <code>prod.tfvars</code> — Terraform mode will diagram those planned AzureRM resources.</em>',
    position: 'right'
  },
  // ── Step 3: Authentication ──
  {
    target: '#section-auth',
    title: '🔐 Authentication & Read-Only Security',
    body: '<strong>Live mode only.</strong> CloudHorus connects to Azure as a strictly <strong>read-only</strong> client — write calls are blocked at the SDK pipeline level (defense-in-depth on top of RBAC).<br><br>' +
          '🛡️ <strong>Recommended role:</strong> Grant the identity only the built-in <code>Reader</code> role at the smallest scope you need. No <code>Contributor</code> / <code>Owner</code>, no key-listing roles.<br><br>' +
          '<strong>Three authentication methods:</strong><br>' +
          '• <strong>Device Code</strong> <em>(default, here in the UI)</em> — Interactive browser login. Best for hands-on use on your workstation. A device code appears and you sign in via <code>microsoft.com/devicelogin</code>.<br>' +
          '• <strong>Service Principal</strong> <em>(here in the UI)</em> — Non-interactive. Provide <code>Client ID</code>, <code>Tenant ID</code>, and <code>Client Secret</code>. The secret is only kept in memory for the process — never written to disk. Use the <strong>Validate Credentials</strong> button to verify before running.<br>' +
          '• <strong>Environment</strong> <em>(CLI only — for CI/CD)</em> — Add <code>--authMethod environment</code> to the command preview when running on a pipeline that already authenticated (GitHub Actions <code>azure/login</code>, Azure DevOps service connection, or a managed identity). CloudHorus auto-detects the existing token; no credentials in the pipeline definition.<br><br>' +
          '⚡ <strong>Non-interactive mode</strong> auto-activates for both Service Principal and Environment — CloudHorus will fail-fast instead of hanging on a prompt, which is exactly what CI/CD pipelines need.<br><br>' +
          '💡 The <strong>OS-aware env-var helper</strong> (collapsible at the bottom of this section) generates the exact <code>export</code> / <code>set</code> / <code>$env:</code> commands for Linux, Windows CMD, or PowerShell — handy for one-off terminal runs.<br><br>' +
          '📖 Full details: <code>docs/SECURITY.md</code>.',
    position: 'right'
  },
  // ── Step 4: Tenant IDs ──
  {
    target: '#tags-tenants',
    title: '🏢 Tenant IDs',
    body: 'An Azure <strong>Tenant</strong> is your organization\'s Azure Active Directory instance. ' +
          'Each tenant has a unique GUID (format: <code>xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx</code>).<br><br>' +
          '<strong>How to find it:</strong> Run <code>az account show --query tenantId</code> in your terminal, or check the Azure Portal under Azure Active Directory → Overview.<br><br>' +
          'Type or paste the ID and press <strong>Enter</strong> to add it. You can add multiple tenants if your resources span different organizations.',
    position: 'right'
  },
  // ── Step 4: Subscription IDs ──
  {
    target: '#tags-subscriptions',
    title: '💳 Subscription IDs',
    body: 'A <strong>Subscription</strong> is a billing and access boundary inside a tenant. ' +
          'Each subscription contains resource groups and resources.<br><br>' +
          '<strong>How to find it:</strong> Run <code>az account list --query "[].{name:name, id:id}"</code> or check the Azure Portal → Subscriptions.<br><br>' +
          'The format is a GUID: <code>xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx</code><br><br>' +
          'Add one subscription per entry. The order matters — per-subscription optimization settings (like Subnet or PE optimization) will follow this same order.',
    position: 'right'
  },
  // ── Step 5: Resource Groups ──
  {
    target: '#tags-resourcegroups',
    title: '📦 Resource Groups',
    body: 'A <strong>Resource Group</strong> is a logical container that holds related Azure resources (VMs, VNets, databases, etc.).<br><br>' +
          '<strong>How to find them:</strong> Run <code>az group list --query "[].name"</code> or check Azure Portal → Resource Groups.<br><br>' +
          '<em>Example:</em> <code>rg-production-networking</code>, <code>rg-app-backend</code><br><br>' +
          'Add the resource groups you want to include in the diagram. Only resources inside these groups will be scanned and visualized.<br><br>' +
          '💡 <strong>Tip:</strong> Start with 2–3 groups that are closely related (e.g., one for networking + one for apps) to get a focused diagram.',
    position: 'right'
  },
  // ── Step 6: Discover Related RGs ──
  {
    target: '#chk-discover-rgs',
    title: '🔍 Discover Related Resource Groups',
    body: 'This is one of CloudHorus\'s most powerful features. When enabled, it <strong>automatically finds resource groups that are connected</strong> to the ones you listed — even if you didn\'t add them explicitly.<br><br>' +
          '<strong>How it works:</strong> CloudHorus inspects resources in your listed RGs and follows dependency links (like Private Endpoints connecting to resources in other RGs, or VNet peerings). Those "discovered" RGs appear as dashed boxes in the diagram.<br><br>' +
          '<em>Example:</em> You add <code>rg-app-backend</code> which has a Private Endpoint linked to a database in <code>rg-shared-databases</code>. Even though you didn\'t add <code>rg-shared-databases</code>, CloudHorus finds it and shows the connection.<br><br>' +
          '• <strong>Toggle ON here</strong> = enable discovery for ALL resource groups at once.<br>' +
          '• You can also click the <i class="fas fa-search-plus"></i> icon on each individual RG chip to enable/disable discovery per group.<br><br>' +
          '💡 <strong>When to disable:</strong> If you want a strictly scoped diagram showing only the RGs you listed, leave this off.',
    position: 'right'
  },
  // ── Step 7: Offline Files (shown when an offline mode is selected) ──
  {
    target: '#section-bicep-files',
    title: '📜 Offline Template Files',
    body: '<em>(Visible when Bicep or Terraform mode is selected)</em><br><br>' +
          '<strong>Bicep mode</strong> expects two aligned file lists:<br>' +
          '• <strong>Bicep files (.bicep)</strong> — the infrastructure templates<br>' +
          '• <strong>Parameter files (.json)</strong> — the values passed into those templates<br><br>' +
          '<strong>Terraform mode</strong> expects two aligned file lists:<br>' +
          '• <strong>main.tf files</strong> — one Terraform root entry file per stack<br>' +
          '• <strong>.tfvars files</strong> — one variable file per <code>main.tf</code>, in the same order<br><br>' +
          'Terraform mode is <strong>offline</strong>, so Azure login is not required for this flow.<br><br>' +
          '⚠️ <strong>Important:</strong> The number and order must match. File 1 uses tfvars 1, File 2 uses tfvars 2, and so on.<br><br>' +
          'Drag and drop files or click <strong>browse</strong> to select them.',
    position: 'right'
  },
  // ── Step 8: Edge Direction ──
  {
    target: '#sel-edge-direction',
    title: '↕️ Edge Direction',
    body: 'Controls the <strong>main flow direction</strong> of your architecture diagram — how resources are arranged relative to each other.<br><br>' +
          '• <strong>Top → Bottom (TB)</strong> — Default. Resources flow downward like an org chart. Best for hierarchical views (Tenant → Subscription → RG → Resources).<br>' +
          '• <strong>Left → Right (LR)</strong> — Resources flow horizontally. Better when you have many peer resources at the same level (e.g., 10+ subnets or services side by side).<br>' +
          '• <strong>Bottom → Top / Right → Left</strong> — Reverse orientations, rarely needed.<br><br>' +
          '<em>Example:</em> If your diagram has 3 tiers (VNet → Subnets → VMs) with few items per tier, use <strong>TB</strong>. If one tier has 15 items, try <strong>LR</strong> to avoid a super-wide diagram.',
    position: 'right'
  },
  // ── Step 9: Tenant Direction ──
  {
    target: '#sel-tenant-direction',
    title: '🏗️ Tenant Direction',
    body: 'When you have <strong>multiple tenants</strong>, this controls how they are placed relative to each other.<br><br>' +
          '• <strong>Left → Right (LR)</strong> — Default. Tenants appear side by side horizontally. Best when you have 2–3 tenants to compare.<br>' +
          '• <strong>Top → Bottom (TB)</strong> — Tenants stack vertically. Use this if each tenant is wide and you\'d rather scroll down than sideways.<br><br>' +
          '<em>Example:</em> Company "Contoso" has Tenant A (production) and Tenant B (development). With LR, you see them left-right. With TB, production is on top and dev below.',
    position: 'right'
  },
  // ── Step 10: Max Subnets Per Line ──
  {
    target: '#input-max-subnet',
    title: '🔢 Max Subnets Per Line',
    body: 'Inside each VNet box in the diagram, subnets are arranged in a grid. This setting controls <strong>how many subnets fit in one row</strong> before wrapping to the next line.<br><br>' +
          '• <strong>Default: 4</strong> — Good balance for most VNets with 4–12 subnets.<br>' +
          '• <strong>Lower (2–3)</strong> — Makes the VNet box taller but narrower. Use when subnets have long names or many connected resources.<br>' +
          '• <strong>Higher (5–8)</strong> — Makes the VNet box wider but shorter. Use for VNets with many subnets (e.g., hub VNet with 20+ subnets) to keep the diagram compact.<br><br>' +
          '<em>Example:</em> A VNet with 12 subnets at max=4 will show 3 rows of 4. At max=6, it shows 2 rows of 6 — wider but shorter.',
    position: 'right'
  },
  // ── Step 11: Resource Edge Length ──
  {
    target: '#input-res-edge-len',
    title: '📏 Resource Edge Length',
    body: 'Controls the <strong>spacing between connected resources</strong> in the diagram. This affects how far apart nodes are when they have dependency arrows between them.<br><br>' +
          '• <strong>Default: 1</strong> — Tight layout, keeps everything compact. Good for small-to-medium diagrams.<br>' +
          '• <strong>2–3</strong> — Adds more breathing room. Use when arrows overlap and become hard to read in dense areas (e.g., a hub VNet connected to many spokes).<br>' +
          '• <strong>4+</strong> — Very spread out. Rarely needed unless you have an extremely dense hub.<br><br>' +
          '<em>Example:</em> If your App Gateway connects to 8 different backends and all the arrows cross each other, increase this to 2 to untangle the lines.',
    position: 'right'
  },
  // ── Step 12: Private DNS Zones Optimization ──
  {
    target: '#chk-dns-opt',
    title: '🌐 Private DNS Zones Optimization',
    body: 'Azure Private DNS Zones can create a lot of visual clutter because each zone links to one or more VNets.<br><br>' +
          '• <strong>ON (default)</strong> — Aggregates all Private DNS Zones linked to a VNet into a single compact group, showing just the zone names as a list. Much cleaner.<br>' +
          '• <strong>OFF</strong> — Draws every DNS zone as a separate node with individual link arrows to each VNet. Use this only when troubleshooting specific DNS resolution issues.<br><br>' +
          '<em>Example:</em> If you have 15 Private DNS Zones (privatelink.blob.core.windows.net, privatelink.database.windows.net, etc.) all linked to the same VNet, ' +
          'ON shows them as one compact block, while OFF draws 15 separate nodes with 15 arrows.',
    position: 'right'
  },
  // ── Step 13: Rank Debug ──
  {
    target: '#chk-rank-debug',
    title: '🔧 Rank Debug',
    body: 'This is an <strong>advanced troubleshooting</strong> toggle for diagram layout issues.<br><br>' +
          '• <strong>OFF (default)</strong> — Normal behavior. Hidden layout helpers are invisible.<br>' +
          '• <strong>ON</strong> — Makes Graphviz\'s internal ranking nodes visible. These are invisible helper nodes that control where resources are positioned vertically/horizontally.<br><br>' +
          '<em>When to use:</em> Only enable this if resources are appearing in unexpected positions and you need to understand the layout engine\'s decisions. ' +
          'The diagram will look messy with debug info — it\'s not meant for final output.<br><br>' +
          '💡 Most users never need this. It\'s a developer/debugging tool.',
    position: 'right'
  },
  // ── Step 14: Export DrawIO ──
  {
    target: '#chk-export-drawio',
    title: '📐 Export DrawIO',
    body: 'Generates a <strong>.drawio file</strong> alongside the PNG diagram. DrawIO (also known as diagrams.net) is a free diagramming tool.<br><br>' +
          '• <strong>OFF (default)</strong> — Only generates the PNG image.<br>' +
          '• <strong>ON</strong> — Also creates a .drawio file that you can open in <a href="https://app.diagrams.net" style="color:var(--color-accent)">diagrams.net</a> or the DrawIO VS Code extension.<br><br>' +
          '<em>Why use it:</em> The PNG is a static image. The .drawio file lets you <strong>move, resize, recolor, and annotate</strong> resources after generation. ' +
          'Great for presentations, documentation, or adding notes to the diagram.<br><br>' +
          'After generation, the <strong>"Open DrawIO"</strong> button will appear — it opens the output folder so you can find and open the .drawio file.',
    position: 'right'
  },
  // ── Step 15: Per-Subscription Settings ──
  {
    target: '#per-sub-options',
    title: '⚡ Per-Subscription Settings',
    body: 'These settings are applied <strong>individually to each subscription</strong>. When you add subscriptions above, a row of toggles appears here for each one.<br><br>' +
          '<strong>Subnet Optimization</strong> — Hides subnets that have no VNet integration (no Private Endpoints or connected services). ' +
          'Useful when a landing zone VNet has 50+ subnets but only 5 are actually used.<br>' +
          '<em>Example:</em> Your hub VNet has subnets for every possible service, but only "snet-pe-storage" and "snet-app" have resources — enable this to hide the empty 48.</em><br><br>' +
          '<strong>PE Optimization</strong> — Groups and repositions Private Endpoints by their subnet context instead of scattering them across the diagram. ' +
          'Enabled by default because most Azure architectures use many PEs.<br><br>' +
          '<strong>Cross-PE Optimization</strong> — Hides Private Endpoints that only connect within the same VNet (no cross-tenant or cross-VNet dependencies). ' +
          'Use this for maximum clarity when you only care about cross-boundary connections.<br><br>' +
          '<strong>RG Edge Length</strong> — Like Resource Edge Length, but per subscription. Controls spacing between resource groups within each subscription box.',
    position: 'right'
  },
  // ── Step 16: Command Preview ──
  {
    target: '.preview-section',
    title: '💻 Command Preview',
    body: 'Shows the <strong>exact CLI command</strong> that CloudHorus will execute based on your configuration. It updates in real time as you change settings.<br><br>' +
          '• Click <i class="fas fa-copy"></i> to <strong>copy the command</strong> to your clipboard — useful for running manually in a terminal, sharing with teammates, or saving in CI/CD scripts.<br>' +
          '• Click <i class="fas fa-sync-alt"></i> to <strong>refresh</strong> the preview if it seems out of sync.<br><br>' +
          '<em>Example output:</em><br><code style="font-size:0.85em">python3 src/main.py --tenants &lt;tenantId&gt; --subscriptions &lt;subId&gt; --resourcegroups rg-net rg-app --edgeDirection TB</code>',
    position: 'left'
  },
  // ── Step 17: Action Buttons ──
  {
    target: '.action-bar',
    title: '🦅 Action Buttons',
    body: '<strong>Invoke the Guardian</strong> — Starts diagram generation. The eagle soars while CloudHorus scans your resources and builds the architecture diagram.<br><br>' +
          '<strong>Stop</strong> — Appears during generation. Cancels the process if it\'s taking too long or you need to change settings.<br><br>' +
          '<strong>View Result</strong> — Opens the generated PNG diagram in the built-in viewer (below). Enabled after a successful generation.<br><br>' +
          '<strong>Open DrawIO</strong> — Opens the folder containing the .drawio file (only visible when Export DrawIO is enabled). From there, open the file in diagrams.net or VS Code.',
    position: 'left'
  },
  // ── Step 18: Console ──
  {
    target: '#console-section',
    title: '📟 Console Output',
    body: 'The live output log showing exactly what CloudHorus is doing step by step.<br><br>' +
          '• <strong>Blue lines</strong> — Informational messages (scanning resources, building graph...).<br>' +
          '• <strong>Green lines</strong> — Success messages (generation complete, file saved).<br>' +
          '• <strong>Yellow/Red lines</strong> — Warnings or errors (missing permissions, auth required).<br>' +
          '• Progress bars show real-time scanning status per resource group.<br><br>' +
          'Controls: <i class="fas fa-trash-alt"></i> clears the console, <i class="fas fa-angle-double-down"></i> scrolls to the latest output, ' +
          'and <i class="fas fa-chevron-up"></i> minimizes the console panel.',
    position: 'left'
  },
  // ── Step 19: Viewer ──
  {
    target: '#viewer-section',
    title: '👁️ Architecture Diagram Viewer',
    body: 'After generation, your architecture diagram appears here with full pan & zoom controls.<br><br>' +
          '• <i class="fas fa-search-plus"></i> / <i class="fas fa-search-minus"></i> — <strong>Zoom in/out</strong> to inspect details or see the big picture.<br>' +
          '• <i class="fas fa-expand"></i> — <strong>Fit to screen</strong> resets zoom to show the entire diagram.<br>' +
          '• <i class="fas fa-expand-arrows-alt"></i> — <strong>Fullscreen mode</strong> for a distraction-free view.<br>' +
          '• <i class="fas fa-external-link-alt"></i> — <strong>Open externally</strong> in your system\'s default image viewer.<br>' +
          '• <strong>Click and drag</strong> the image to pan around large diagrams.<br>' +
          '• <strong>Mouse wheel</strong> to zoom.<br><br>' +
          '💡 Use the horizontal splitter bar between the Console and Viewer to resize the areas.',
    position: 'left'
  },
  // ── Step 20: You're Ready! ──
  {
    target: '#app-header',
    title: '🦅 You\'re Ready!',
    body: 'That\'s everything! Here\'s a quick checklist to get started:<br><br>' +
          '1️⃣ Choose <strong>Live Azure</strong>, <strong>Bicep</strong>, or <strong>Terraform</strong> mode.<br>' +
          '2️⃣ Enter your Azure scope or select the offline files for Bicep/Terraform.<br>' +
          '3️⃣ Optionally enable <strong>Discover Related RGs</strong> to automatically find connected resources.<br>' +
          '4️⃣ Adjust Layout & Optimizations if the default diagram is too dense or sparse.<br>' +
          '5️⃣ Click <strong>Invoke the Guardian</strong> and watch the magic happen!<br><br>' +
          'You can retake this tour anytime by clicking the <i class="fas fa-route"></i> button in the Configuration panel header.',
    position: 'bottom'
  }
];

let tourState = { active: false, step: 0, highlight: null, tempShown: [] };

function startTour() {
  tourState.active = true;
  tourState.step = 0;
  tourState.tempShown = [];
  document.getElementById('tour-overlay').classList.remove('hidden');
  renderTourStep();
  localStorage.setItem('cloudhorus-tour-done', '1');
}

function endTour() {
  tourState.active = false;
  const overlay = document.getElementById('tour-overlay');
  overlay.classList.add('hidden');
  // Remove highlight
  if (tourState.highlight) {
    tourState.highlight.classList.remove('tour-highlight');
    tourState.highlight = null;
  }
  // Restore any temporarily shown elements
  _tourRestoreTempShown();
}

/** Hide elements that were temporarily revealed for the previous step */
function _tourRestoreTempShown() {
  for (const entry of tourState.tempShown) {
    if (entry.wasHidden) entry.el.classList.add('hidden');
    if (entry.wasDisplayNone) entry.el.style.display = entry.prevDisplay;
  }
  tourState.tempShown = [];
}

/** Temporarily reveal a hidden element so the tour can highlight it */
function _tourTempShow(el) {
  if (!el) return;
  const entry = { el, wasHidden: false, wasDisplayNone: false, prevDisplay: '' };
  if (el.classList.contains('hidden')) {
    entry.wasHidden = true;
    el.classList.remove('hidden');
  }
  const cs = window.getComputedStyle(el);
  if (cs.display === 'none') {
    entry.wasDisplayNone = true;
    entry.prevDisplay = el.style.display;
    el.style.display = '';  // let CSS class take over
    // if still none after removing inline style, force block
    if (window.getComputedStyle(el).display === 'none') {
      el.style.display = 'block';
    }
  }
  tourState.tempShown.push(entry);
}

function tourNext() {
  if (tourState.step < TOUR_STEPS.length - 1) {
    tourState.step++;
    renderTourStep();
  } else {
    endTour();
    showToast('🦅 Tour complete! You\'re ready to invoke the Guardian.', 'success');
  }
}

function tourPrev() {
  if (tourState.step > 0) {
    tourState.step--;
    renderTourStep();
  }
}

function renderTourStep() {
  const step = TOUR_STEPS[tourState.step];
  const total = TOUR_STEPS.length;

  // Restore previously temp-shown elements before revealing new ones
  _tourRestoreTempShown();

  // Update text
  document.getElementById('tour-step-badge').textContent = `${tourState.step + 1}/${total}`;
  document.getElementById('tour-title').textContent = step.title;
  document.getElementById('tour-body').innerHTML = step.body;

  // Update dots
  const dotsContainer = document.getElementById('tour-dots');
  dotsContainer.innerHTML = '';
  for (let i = 0; i < total; i++) {
    const dot = document.createElement('span');
    dot.className = 'tour-dot' + (i === tourState.step ? ' active' : '');
    dot.onclick = () => { tourState.step = i; renderTourStep(); };
    dotsContainer.appendChild(dot);
  }

  // Button states
  document.getElementById('tour-prev').style.visibility = tourState.step > 0 ? 'visible' : 'hidden';
  const nextBtn = document.getElementById('tour-next');
  if (tourState.step === total - 1) {
    nextBtn.innerHTML = '<i class="fas fa-check"></i> Finish';
  } else {
    nextBtn.innerHTML = 'Next <i class="fas fa-arrow-right"></i>';
  }

  // Highlight target element
  if (tourState.highlight) {
    tourState.highlight.classList.remove('tour-highlight');
    tourState.highlight = null;
  }
  let targetEl = document.querySelector(step.target);

  // If target is hidden / display:none, temporarily reveal it and its
  // hidden ancestors so it can be highlighted in place (instead of
  // centering the tooltip on screen or falling back to a parent).
  if (targetEl) {
    // Walk up and reveal hidden ancestors first
    let ancestor = targetEl.parentElement;
    while (ancestor && ancestor !== document.body) {
      if (ancestor.classList.contains('hidden') || window.getComputedStyle(ancestor).display === 'none') {
        _tourTempShow(ancestor);
      }
      ancestor = ancestor.parentElement;
    }
    // Reveal the element itself (only if explicitly hidden, not merely empty)
    if (targetEl.classList.contains('hidden') || window.getComputedStyle(targetEl).display === 'none') {
      _tourTempShow(targetEl);
    }
  }

  // Determine if the target is truly visible. offsetParent is null for
  // zero-height empty containers (e.g. empty .tag-chips divs) even when
  // they and their parents ARE visible.  Use getBoundingClientRect as a
  // more reliable check: if top/left are both 0 AND width/height are 0
  // the element is likely not rendered; otherwise treat it as visible.
  // Also fall back to the nearest visible parent (.tag-input-wrapper or
  // .form-group) so the tooltip still anchors near the right spot.
  function _isTourVisible(el) {
    if (!el) return false;
    if (el.offsetParent !== null) return true;
    // offsetParent can be null for elements in a visible flex container
    // that have no own height — check bounding rect instead
    const r = el.getBoundingClientRect();
    return (r.top !== 0 || r.left !== 0);
  }

  if (targetEl && _isTourVisible(targetEl)) {
    targetEl.classList.add('tour-highlight');
    tourState.highlight = targetEl;
    targetEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } else if (targetEl) {
    // Element exists but has no measurable rect — highlight nearest
    // visible parent instead of centering on screen
    const fallback = targetEl.closest('.tag-input-wrapper')
                  || targetEl.closest('.form-group')
                  || targetEl.closest('.panel-section');
    if (fallback && _isTourVisible(fallback)) {
      fallback.classList.add('tour-highlight');
      tourState.highlight = fallback;
      fallback.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      targetEl = fallback;
    } else {
      targetEl = null; // truly invisible — center tooltip on screen
    }
  } else {
    targetEl = null; // element not found
  }

  // Position tooltip near target (with slight delay to let scroll settle)
  setTimeout(() => positionTooltip(targetEl, step.position), 80);
}

function positionTooltip(targetEl, position) {
  const tooltip = document.getElementById('tour-tooltip');
  if (!targetEl) {
    // Center on screen
    tooltip.style.top = '50%';
    tooltip.style.left = '50%';
    tooltip.style.transform = 'translate(-50%, -50%)';
    return;
  }

  const rect = targetEl.getBoundingClientRect();
  const ttW = 420;
  const ttH = tooltip.getBoundingClientRect().height || 300;
  const margin = 16;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  // Remove previous transform
  tooltip.style.transform = '';

  let top, left;

  switch (position) {
    case 'bottom':
      top = rect.bottom + margin;
      left = Math.max(margin, rect.left + rect.width / 2 - ttW / 2);
      break;
    case 'right':
      top = Math.max(margin, rect.top);
      left = Math.min(vw - ttW - margin, rect.right + margin);
      break;
    case 'left':
      top = Math.max(margin, rect.top);
      left = Math.max(margin, rect.left - ttW - margin);
      break;
    case 'top':
      top = Math.max(margin, rect.top - ttH - margin);
      left = Math.max(margin, rect.left + rect.width / 2 - ttW / 2);
      break;
    default:
      top = margin;
      left = margin;
  }

  // Clamp to viewport
  if (top + ttH > vh - margin) top = Math.max(margin, vh - ttH - margin);
  if (left + ttW > vw - margin) left = Math.max(margin, vw - ttW - margin);

  tooltip.style.top = top + 'px';
  tooltip.style.left = left + 'px';
}

// Auto-show tour on first visit
function maybeShowTour() {
  if (!localStorage.getItem('cloudhorus-tour-done')) {
    setTimeout(() => {
      // Don't show if auth modal is visible
      const authModal = document.getElementById('auth-modal');
      if (authModal && !authModal.classList.contains('hidden')) {
        // Defer until auth closes
        const observer = new MutationObserver(() => {
          if (authModal.classList.contains('hidden')) {
            observer.disconnect();
            startTour();
          }
        });
        observer.observe(authModal, { attributes: true, attributeFilter: ['class'] });
        return;
      }
      startTour();
    }, 1500);
  }
}

// ─── Utility ───
function escapeHtml(str) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}
