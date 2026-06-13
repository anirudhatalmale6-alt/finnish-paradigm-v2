/* FCEI Cookie Consent — vanilla JS integration (no React) */
const CC_API = '/api/cookie-consent';
const CC_STORAGE_KEY = 'fcei_cookie_consent_v1';
const CC_CONSENT_ID_KEY = 'fcei_consent_id';

function ccToken() { return localStorage.getItem('fp_token'); }
function ccAuth() { return ccToken() ? { 'Authorization': 'Bearer ' + ccToken() } : {}; }

async function ccFetch(url, opts) {
  opts = opts || {};
  var r = await fetch(url, Object.assign({}, opts, {
    headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {}, ccAuth())
  }));
  var text = await r.text();
  var data = text ? JSON.parse(text) : {};
  if (!r.ok) throw new Error(data.detail || data.error || 'Request failed');
  return data;
}

function ccGetConsentId() {
  var id = localStorage.getItem(CC_CONSENT_ID_KEY);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(16).slice(2));
    localStorage.setItem(CC_CONSENT_ID_KEY, id);
  }
  return id;
}

function ccReadStored() {
  try {
    var raw = localStorage.getItem(CC_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
}

function ccWriteStored(consent) {
  localStorage.setItem(CC_STORAGE_KEY, JSON.stringify(consent));
  var secure = location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = 'fcei_cookie_consent=' + encodeURIComponent(JSON.stringify({
    consent_id: consent.consent_id,
    policy_version: consent.policy_version,
    choices: consent.choices,
    updated_at: consent.updated_at
  })) + '; Path=/; Max-Age=31536000; SameSite=Lax' + secure;
}

function ccClearOptionalCookies() {
  var names = ['_ga', '_gid', '_gat', '_gcl_au', '_fbp', '_fbc', 'hubspotutk'];
  for (var i = 0; i < names.length; i++) {
    document.cookie = names[i] + '=; Path=/; Max-Age=0; SameSite=Lax';
    document.cookie = names[i] + '=; Path=/; Domain=.' + location.hostname + '; Max-Age=0; SameSite=Lax';
  }
}

function ccSafeHref(url) {
  if (!url) return '';
  var v = String(url).trim();
  if (v.startsWith('/') || v.startsWith('#')) return v;
  var m = v.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):/);
  if (!m) return v;
  return ['http', 'https', 'mailto', 'tel'].indexOf(m[1].toLowerCase()) >= 0 ? v : '';
}

function ccApplyScripts(services, choices) {
  if (!services || !choices) return;
  for (var i = 0; i < services.length; i++) {
    var svc = services[i];
    if (!svc.script_url || !choices[svc.category_key]) continue;
    var id = 'fcei-cc-script-' + svc.service_key;
    if (document.getElementById(id)) continue;
    var parsed;
    try { parsed = new URL(svc.script_url, location.origin); } catch (e) { continue; }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') continue;
    var script = document.createElement('script');
    script.id = id;
    script.src = parsed.href;
    script.async = true;
    document.head.appendChild(script);
  }
}

function ccEsc(s) {
  var d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

/* ── Main cookie consent banner ── */
var _ccConfig = null;
var _ccChoices = {};
var _ccVisible = false;
var _ccManageOpen = false;

function ccInit() {
  ccFetch(CC_API + '/config').then(function(data) {
    _ccConfig = data;
    var stored = ccReadStored();
    var needsChoice = !stored || stored.policy_version !== data.policy_version;
    _ccChoices = stored && stored.choices ? Object.assign({}, stored.choices) : ccDefaultChoices(data.categories, 'reject_optional');
    if (stored && stored.choices) ccApplyScripts(data.services, stored.choices);
    if (needsChoice) ccShow(); else ccRenderFloatingButton();
  }).catch(function() {});
}

function ccDefaultChoices(categories, mode) {
  var choices = {};
  for (var i = 0; i < categories.length; i++) {
    var c = categories[i];
    if (c.is_essential) { choices[c.category_key] = true; continue; }
    if (mode === 'accept_all') { choices[c.category_key] = true; continue; }
    if (mode === 'reject_optional') { choices[c.category_key] = false; continue; }
    choices[c.category_key] = !!c.default_enabled;
  }
  return choices;
}

function ccShow() {
  _ccVisible = true;
  _ccManageOpen = false;
  ccRender();
}

function ccHide() {
  _ccVisible = false;
  _ccManageOpen = false;
  ccRender();
}

function ccRender() {
  var existing = document.getElementById('fcei-cookie-consent-root');
  if (existing) existing.remove();

  var root = document.createElement('div');
  root.id = 'fcei-cookie-consent-root';

  if (!_ccVisible) {
    root.innerHTML = '<button class="fcei-cc cookie-floating-button" type="button" onclick="ccShow()">Cookie settings</button>';
    document.body.appendChild(root);
    return;
  }

  var cfg = _ccConfig;
  if (!cfg) return;

  var logoHtml = '';
  var logoSrc = ccSafeHref(cfg.brand_logo_url);
  if (logoSrc) logoHtml = '<img src="' + ccEsc(logoSrc) + '" alt="">';

  var categoriesHtml = '';
  if (_ccManageOpen) {
    categoriesHtml = '<div class="cookie-categories">';
    for (var i = 0; i < cfg.categories.length; i++) {
      var cat = cfg.categories[i];
      var checked = !!_ccChoices[cat.category_key];
      var disabled = cat.is_essential;
      var switchLabel = disabled ? 'Always on' : (checked ? 'On' : 'Off');

      var servicesHtml = '';
      var catServices = (cfg.services || []).filter(function(s) { return s.category_key === cat.category_key; });
      if (catServices.length === 0) {
        servicesHtml = '<small>No optional service currently registered.</small>';
      } else {
        for (var j = 0; j < catServices.length; j++) {
          var svc = catServices[j];
          var cookieNames = '';
          if (Array.isArray(svc.cookies) && svc.cookies.length > 0) {
            cookieNames = '<code>' + svc.cookies.map(function(c) { return ccEsc(c.name || c); }).join(', ') + '</code>';
          }
          var privLink = '';
          var privHref = ccSafeHref(svc.privacy_url);
          if (privHref) {
            privLink = '<p><a class="cookie-service-link" href="' + ccEsc(privHref) + '" target="_blank" rel="noopener noreferrer">Privacy notice</a></p>';
          }
          servicesHtml += '<div class="cookie-service">' +
            '<small><strong>' + ccEsc(svc.name) + '</strong> &middot; ' + ccEsc(svc.provider || 'FCEI') + '</small>' +
            '<p>' + ccEsc(svc.purpose || '') + '</p>' +
            cookieNames + privLink + '</div>';
        }
      }

      categoriesHtml += '<div class="cookie-category">' +
        '<div><strong>' + ccEsc(cat.label) + '</strong>' +
        '<p>' + ccEsc(cat.description) + '</p>' +
        '<details><summary>Services in this category</summary>' + servicesHtml + '</details></div>' +
        '<label class="switch">' +
        '<input type="checkbox" data-cat="' + ccEsc(cat.category_key) + '"' +
        (checked ? ' checked' : '') + (disabled ? ' disabled' : '') +
        ' onchange="ccUpdateChoice(this.dataset.cat, this.checked)">' +
        '<span>' + switchLabel + '</span></label></div>';
    }
    categoriesHtml += '</div>';
  }

  var saveBtn = _ccManageOpen ? '<button type="button" onclick="ccSavePreferences()">Save choices</button>' : '';

  root.innerHTML = '<div class="fcei-cc cookie-consent-backdrop" role="dialog" aria-modal="true" aria-labelledby="cookie-title">' +
    '<section class="cookie-consent-panel">' +
    '<div class="cookie-consent-header">' +
    '<div class="cookie-brand">' + logoHtml +
    '<div><small>FCEI privacy controls</small>' +
    '<h2 id="cookie-title">' + ccEsc(cfg.banner_title) + '</h2></div></div>' +
    '<button class="link-button" type="button" onclick="ccToggleManage()">' +
    (_ccManageOpen ? 'Hide preferences' : 'Manage preferences') + '</button></div>' +
    '<p>' + ccEsc(cfg.banner_text) + '</p>' +
    '<p class="muted">You can accept, reject non-essential cookies, or choose categories. Necessary cookies stay on because the platform needs them for login, security, payments, SCORM progress and saved cookie choices.</p>' +
    categoriesHtml +
    '<div class="cookie-actions">' +
    '<button type="button" onclick="ccAcceptAll()">Accept all</button>' +
    '<button class="secondary" type="button" onclick="ccRejectOptional()">Reject non-essential</button>' +
    '<button class="secondary" type="button" onclick="ccToggleManage()">Manage cookies</button>' +
    saveBtn + '</div>' +
    '<p class="cookie-links"><a href="' + ccEsc(cfg.cookie_policy_url || '/cookie-policy') + '">Cookie Policy</a> &middot; ' +
    '<a href="' + ccEsc(cfg.privacy_policy_url || '/privacy-policy') + '">Privacy Policy</a></p>' +
    '</section></div>';

  document.body.appendChild(root);
}

function ccRenderFloatingButton() {
  var existing = document.getElementById('fcei-cookie-consent-root');
  if (existing) existing.remove();
  var root = document.createElement('div');
  root.id = 'fcei-cookie-consent-root';
  root.innerHTML = '<button class="fcei-cc cookie-floating-button" type="button" onclick="ccShow()">Cookie settings</button>';
  document.body.appendChild(root);
}

function ccToggleManage() {
  _ccManageOpen = !_ccManageOpen;
  ccRender();
}

function ccUpdateChoice(key, value) {
  _ccChoices[key] = value;
}

async function ccSave(action, choices) {
  if (!_ccConfig) return;
  var consent_id = ccGetConsentId();
  try {
    var data = await ccFetch(CC_API + '/record', {
      method: 'POST',
      body: JSON.stringify({ consent_id: consent_id, action: action, choices: choices })
    });
    var stored = {
      consent_id: consent_id,
      policy_version: data.consent.policy_version,
      action: action,
      choices: data.choices,
      updated_at: data.consent.created_at
    };
    ccWriteStored(stored);
    _ccChoices = data.choices;
    if (action === 'reject_optional' || Object.values(data.choices).some(function(v) { return v === false; })) {
      ccClearOptionalCookies();
    }
    ccApplyScripts(_ccConfig.services || [], data.choices);
    _ccVisible = false;
    _ccManageOpen = false;
    ccRenderFloatingButton();
  } catch (e) { console.error('Cookie consent save error:', e); }
}

function ccAcceptAll() {
  ccSave('accept_all', ccDefaultChoices(_ccConfig.categories, 'accept_all'));
}

function ccRejectOptional() {
  ccSave('reject_optional', ccDefaultChoices(_ccConfig.categories, 'reject_optional'));
}

function ccSavePreferences() {
  ccSave('save_preferences', _ccChoices);
}


/* ── Admin cookie consent panel ── */
async function renderAdminCookieConsent() {
  var container = document.getElementById('adminCookieConsent');
  if (!container || !ccToken()) return;
  try {
    var results = await Promise.all([
      ccFetch(CC_API + '/admin/records?limit=25'),
      ccFetch(CC_API + '/admin/categories'),
      ccFetch(CC_API + '/admin/services')
    ]);
    var records = results[0].records || [];
    var categories = results[1].categories || [];
    var services = results[2].services || [];

    var catOptions = categories.map(function(c) {
      return '<option value="' + ccEsc(c.category_key) + '">' + ccEsc(c.label) + '</option>';
    }).join('');

    container.innerHTML =
      '<h3>Cookie Consent Manager</h3>' +
      '<p>Register optional cookies, scripts and consent categories before enabling analytics, pixels, marketing tags or other storage/access technologies.</p>' +

      '<div class="cc-admin-grid">' +
      '<div class="card soft">' +
      '<h4>Registered Categories</h4>' +
      '<ul>' + categories.map(function(c) {
        return '<li><strong>' + ccEsc(c.label) + '</strong> &middot; ' +
          (c.is_essential ? 'always on' : 'optional') + '<br><small>' + ccEsc(c.description) + '</small></li>';
      }).join('') + '</ul></div>' +

      '<form id="ccServiceForm" onsubmit="ccSaveService(event)" class="card soft">' +
      '<h4>Add / Update Cookie Service</h4>' +
      '<label>Service key<input name="service_key" placeholder="google_analytics" required></label>' +
      '<label>Category<select name="category_key">' + catOptions + '</select></label>' +
      '<label>Name<input name="name" placeholder="Google Analytics 4" required></label>' +
      '<label>Provider<input name="provider" placeholder="Google"></label>' +
      '<label>Purpose<textarea name="purpose" placeholder="Analytics reporting, if enabled by user consent." rows="2"></textarea></label>' +
      '<label>Cookie names (comma-separated)<input name="cookies" placeholder="_ga, _gid"></label>' +
      '<label>Privacy URL<input name="privacy_url" placeholder="https://..."></label>' +
      '<label>Script URL<input name="script_url" placeholder="https://..."></label>' +
      '<label class="inline-check"><input type="checkbox" name="enabled" checked> Enabled</label>' +
      '<label class="inline-check"><input type="checkbox" name="requires_consent" checked> Requires consent</label>' +
      '<button class="btn primary" type="submit">Save Service</button>' +
      '<p id="ccServiceMsg"></p></form></div>' +

      '<div class="card soft">' +
      '<h4>Registered Services</h4>' +
      '<div class="scroll-x"><table class="dataTable"><thead><tr><th>Service</th><th>Category</th><th>Provider</th><th>Enabled</th></tr></thead><tbody>' +
      services.map(function(s) {
        return '<tr><td>' + ccEsc(s.name) + '<br><small>' + ccEsc(s.service_key) + '</small></td>' +
          '<td>' + ccEsc(s.category_key) + '</td><td>' + ccEsc(s.provider || '-') + '</td>' +
          '<td>' + (s.enabled ? 'Yes' : 'No') + '</td></tr>';
      }).join('') + '</tbody></table></div></div>' +

      '<div class="card soft">' +
      '<h4>Recent Consent Records</h4>' +
      (records.length ?
        '<div class="scroll-x"><table class="dataTable"><thead><tr><th>Date</th><th>Action</th><th>Choices</th><th>User</th></tr></thead><tbody>' +
        records.map(function(r) {
          var choicesStr = '';
          try { choicesStr = JSON.stringify(r.choices); } catch (e) { choicesStr = '{}'; }
          return '<tr><td>' + ccEsc((r.created_at || '').substring(0, 16)) + '</td>' +
            '<td>' + ccEsc(r.action) + '</td><td><code>' + ccEsc(choicesStr) + '</code></td>' +
            '<td>' + ccEsc(r.email || 'anonymous') + '</td></tr>';
        }).join('') + '</tbody></table></div>'
        : '<p>No consent records yet.</p>') + '</div>';

  } catch (e) {
    container.innerHTML = '<p>Could not load cookie consent manager: ' + ccEsc(e.message) + '</p>';
  }
}

async function ccSaveService(e) {
  e.preventDefault();
  var f = e.target;
  var payload = {
    service_key: f.service_key.value,
    category_key: f.category_key.value,
    name: f.name.value,
    provider: f.provider.value,
    purpose: f.purpose.value,
    privacy_url: f.privacy_url.value,
    script_url: f.script_url.value,
    enabled: f.enabled.checked,
    requires_consent: f.requires_consent.checked,
    cookies: f.cookies.value.split(',').map(function(x) { return x.trim(); }).filter(Boolean).map(function(n) { return { name: n }; })
  };
  try {
    await ccFetch(CC_API + '/admin/services', { method: 'POST', body: JSON.stringify(payload) });
    document.getElementById('ccServiceMsg').textContent = 'Cookie service saved!';
    f.reset();
    renderAdminCookieConsent();
  } catch (err) {
    document.getElementById('ccServiceMsg').textContent = 'Error: ' + err.message;
  }
}

/* ── Auto-init ── */
function ccBootstrap() {
  ccInit();
  if (location.pathname.endsWith('/admin.html')) {
    setTimeout(function() { renderAdminCookieConsent(); }, 800);
  }
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ccBootstrap);
} else {
  ccBootstrap();
}
