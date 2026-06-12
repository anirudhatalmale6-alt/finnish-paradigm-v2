/* FCEI Toolkit Marketplace — frontend integration */
const TK_API = '/api/toolkit-store';
const tkToken = () => localStorage.getItem('fp_token');
const tkAuth = () => tkToken() ? { 'Authorization': 'Bearer ' + tkToken() } : {};
async function tkFetch(url, opts = {}) {
  const r = await fetch(url, { ...opts, headers: { ...(opts.headers || {}), ...tkAuth() } });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function tkMoney(cents, currency) { return (currency || 'GBP') + ' ' + ((cents || 0) / 100).toFixed(2); }

/* ─── Learner: Toolkit Buy Options (injected into module page) ─── */
async function renderToolkitBuyOptions(courseId, moduleId) {
  const container = document.getElementById('toolkitBuyOptions');
  if (!container) return;
  try {
    const url = tkToken()
      ? TK_API + '/learner/options?course_code=' + encodeURIComponent(courseId)
      : TK_API + '/public/options?course_code=' + encodeURIComponent(courseId);
    const data = await tkFetch(url);
    if (!data.products || !data.products.length) { container.innerHTML = ''; return; }
    container.innerHTML = '<div class="module-section"><h2>Toolkit / Downloadable Resources</h2>' +
      '<p>Choose a single module toolkit, course bundle, full library access, or institutional licence.</p>' +
      '<div class="toolkit-grid">' + data.products.map(p => {
        const owned = p.has_access;
        const price = p.effective_price_cents || p.price_cents;
        return '<div class="toolkit-card' + (owned ? ' owned' : '') + '" data-id="' + p.id + '">' +
          '<div class="tk-type">' + (p.product_type || '').replace(/_/g, ' ') + '</div>' +
          '<h3>' + p.title + '</h3>' +
          (p.description ? '<p>' + p.description + '</p>' : '') +
          '<div class="tk-price">' + (owned ? 'Owned' : tkMoney(price, p.currency)) + '</div>' +
          (owned
            ? '<button class="btn primary" onclick="viewToolkitAssets(' + p.id + ')">Open Toolkit</button>'
            : '<button class="btn outline" onclick="buyToolkit(' + p.id + ')">Add to Cart</button>') +
          '</div>';
      }).join('') + '</div></div>';
  } catch (e) { container.innerHTML = ''; }
}

async function buyToolkit(productId) {
  if (!tkToken()) { location.href = '/login.html'; return; }
  try {
    const data = await tkFetch(TK_API + '/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_ids: [productId] })
    });
    const orderId = data.order.id;
    if (confirm('Order created: ' + data.order.order_number + ' (' + tkMoney(data.order.total_cents, 'GBP') + '). Demo mode: complete payment now?')) {
      await tkFetch(TK_API + '/checkout/' + orderId + '/demo-complete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      alert('Payment complete! Toolkit access granted.');
      location.reload();
    }
  } catch (e) { alert('Checkout error: ' + e.message); }
}

async function viewToolkitAssets(productId) {
  try {
    const data = await tkFetch(TK_API + '/learner/products/' + productId + '/assets');
    if (!data.assets || !data.assets.length) { alert('No assets available for this toolkit yet.'); return; }
    const asset = data.assets[0];
    if (asset.public_url) { window.open(asset.public_url, '_blank'); }
    else { window.open('/api/toolkit-store/learner/products/' + productId + '/assets/' + asset.id + '/download', '_blank'); }
  } catch (e) { alert('Could not load assets: ' + e.message); }
}

/* ─── Learner: My Toolkits (injected into dashboard) ─── */
async function renderMyToolkits() {
  const container = document.getElementById('myToolkits');
  if (!container || !tkToken()) return;
  try {
    const data = await tkFetch(TK_API + '/learner/library');
    if (!data.entitlements || !data.entitlements.length) {
      container.innerHTML = '<p>No toolkit purchases yet. <a href="/courses.html">Browse courses</a> to find available toolkits.</p>';
      return;
    }
    container.innerHTML = '<div class="toolkit-grid">' + data.entitlements.map(e =>
      '<div class="toolkit-card owned">' +
      '<div class="tk-type">' + (e.product_type || '').replace(/_/g, ' ') + '</div>' +
      '<h3>' + e.title + '</h3>' +
      '<div class="tk-price">Owned' + (e.asset_count ? ' (' + e.asset_count + ' files)' : '') + '</div>' +
      '<button class="btn primary" onclick="viewToolkitAssets(' + e.product_id + ')">Open Toolkit</button>' +
      '</div>'
    ).join('') + '</div>';
  } catch (e) { container.innerHTML = '<p>Could not load toolkits.</p>'; }
}

/* ─── Admin: Toolkit Store ─── */
async function renderAdminToolkitStore() {
  const container = document.getElementById('adminToolkitStore');
  if (!container || !tkToken()) return;
  try {
    const [prodData, orderData] = await Promise.all([
      tkFetch(TK_API + '/admin/products'),
      tkFetch(TK_API + '/admin/orders')
    ]);
    const products = prodData.products || [];
    const orders = orderData.orders || [];
    container.innerHTML =
      '<h3>Create Toolkit Product</h3>' +
      '<form id="tkCreateForm" onsubmit="createToolkitProduct(event)" class="form-grid">' +
      '<input name="product_code" placeholder="Product code (e.g. TK-C01-M01)" required>' +
      '<input name="title" placeholder="Product title" required>' +
      '<select name="product_type"><option value="single_module_toolkit">Single Module Toolkit</option><option value="course_toolkit_bundle">Course Bundle</option><option value="full_toolkit_library">Full Library</option><option value="institutional_licence">Institutional Licence</option></select>' +
      '<input name="price_cents" type="number" placeholder="Price in pence (e.g. 1900 = GBP 19)" value="1900">' +
      '<input name="course_id" placeholder="Course ID (e.g. C01)">' +
      '<input name="module_id" placeholder="Module ID (e.g. C01-M01)">' +
      '<select name="access_scope"><option value="module">Module</option><option value="course">Course</option><option value="library">Library</option><option value="institution">Institution</option></select>' +
      '<select name="status"><option value="published">Published</option><option value="draft">Draft</option></select>' +
      '<textarea name="description" placeholder="Description" rows="2"></textarea>' +
      '<button class="btn primary" type="submit">Create Product</button>' +
      '</form>' +
      '<p id="tkCreateMsg"></p>' +
      '<h3>Toolkit Products (' + products.length + ')</h3>' +
      '<div class="scroll-x"><table class="dataTable"><thead><tr><th>Code</th><th>Title</th><th>Type</th><th>Price</th><th>Status</th><th>Assets</th><th>Actions</th></tr></thead><tbody>' +
      products.map(p =>
        '<tr><td>' + p.product_code + '</td><td>' + p.title + '</td><td>' + (p.product_type || '').replace(/_/g, ' ') + '</td>' +
        '<td>' + p.display_price + '</td><td>' + p.status + '</td><td>' + (p.asset_count || 0) + '</td>' +
        '<td><button class="btn light" onclick="toggleToolkitStatus(' + p.id + ',\'' + (p.status === 'published' ? 'draft' : 'published') + '\')">' + (p.status === 'published' ? 'Unpublish' : 'Publish') + '</button></td></tr>'
      ).join('') + '</tbody></table></div>' +
      '<h3>Upload Asset to Product</h3>' +
      '<form id="tkAssetForm" onsubmit="uploadToolkitAsset(event)" enctype="multipart/form-data" class="form-grid">' +
      '<select name="product_id">' + products.map(p => '<option value="' + p.id + '">' + p.product_code + ' — ' + p.title + '</option>').join('') + '</select>' +
      '<input name="asset" type="file" required>' +
      '<input name="title" placeholder="Asset title">' +
      '<select name="asset_type"><option value="pdf">PDF</option><option value="docx">DOCX</option><option value="pptx">PPTX</option><option value="xlsx">XLSX</option><option value="zip">ZIP</option><option value="link">Link</option></select>' +
      '<button class="btn primary" type="submit">Upload Asset</button>' +
      '</form>' +
      '<p id="tkAssetMsg"></p>' +
      '<h3>Recent Orders (' + orders.length + ')</h3>' +
      (orders.length ? '<div class="scroll-x"><table class="dataTable"><thead><tr><th>Order</th><th>User</th><th>Items</th><th>Total</th><th>Status</th><th>Date</th></tr></thead><tbody>' +
      orders.slice(0, 50).map(o =>
        '<tr><td>' + o.order_number + '</td><td>' + (o.user_name || o.user_email) + '</td><td>' + o.item_count + '</td>' +
        '<td>' + tkMoney(o.total_cents, o.currency) + '</td><td>' + o.status + '</td><td>' + (o.created_at || '').substring(0, 16) + '</td></tr>'
      ).join('') + '</tbody></table></div>' : '<p>No orders yet.</p>') +
      '<h3>Grant Entitlement</h3>' +
      '<form id="tkGrantForm" onsubmit="grantToolkitEntitlement(event)" class="form-grid">' +
      '<input name="user_id" type="number" placeholder="User ID" required>' +
      '<select name="product_id">' + products.map(p => '<option value="' + p.id + '">' + p.product_code + '</option>').join('') + '</select>' +
      '<button class="btn primary" type="submit">Grant Access</button>' +
      '</form>' +
      '<p id="tkGrantMsg"></p>';
  } catch (e) { container.innerHTML = '<p>Could not load toolkit store: ' + e.message + '</p>'; }
}

async function createToolkitProduct(e) {
  e.preventDefault();
  const f = e.target;
  const data = Object.fromEntries(new FormData(f).entries());
  data.price_cents = parseInt(data.price_cents) || 0;
  try {
    await tkFetch(TK_API + '/admin/products', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    document.getElementById('tkCreateMsg').textContent = 'Product created!';
    f.reset();
    renderAdminToolkitStore();
  } catch (e) { document.getElementById('tkCreateMsg').textContent = 'Error: ' + e.message; }
}

async function toggleToolkitStatus(productId, newStatus) {
  try {
    await tkFetch(TK_API + '/admin/products/' + productId, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus })
    });
    renderAdminToolkitStore();
  } catch (e) { alert('Error: ' + e.message); }
}

async function uploadToolkitAsset(e) {
  e.preventDefault();
  const f = e.target;
  const fd = new FormData(f);
  const productId = fd.get('product_id');
  fd.delete('product_id');
  try {
    const r = await fetch(TK_API + '/admin/products/' + productId + '/assets', {
      method: 'POST', headers: tkAuth(), body: fd
    });
    if (!r.ok) throw new Error(await r.text());
    document.getElementById('tkAssetMsg').textContent = 'Asset uploaded!';
    f.reset();
    renderAdminToolkitStore();
  } catch (e) { document.getElementById('tkAssetMsg').textContent = 'Error: ' + e.message; }
}

async function grantToolkitEntitlement(e) {
  e.preventDefault();
  const f = e.target;
  const data = Object.fromEntries(new FormData(f).entries());
  data.user_id = parseInt(data.user_id);
  data.product_id = parseInt(data.product_id);
  try {
    await tkFetch(TK_API + '/admin/entitlements/grant', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    document.getElementById('tkGrantMsg').textContent = 'Entitlement granted!';
    f.reset();
  } catch (e) { document.getElementById('tkGrantMsg').textContent = 'Error: ' + e.message; }
}

/* ─── Auto-init based on page ─── */
document.addEventListener('DOMContentLoaded', () => {
  const p = location.pathname;
  if (p.endsWith('/module.html')) {
    const params = new URLSearchParams(location.search);
    const moduleId = params.get('id');
    if (moduleId) {
      const courseCode = moduleId.split('-')[0];
      setTimeout(() => renderToolkitBuyOptions(courseCode, moduleId), 500);
    }
  }
  if (p.endsWith('/dashboard.html')) {
    setTimeout(() => renderMyToolkits(), 800);
  }
  if (p.endsWith('/admin.html')) {
    setTimeout(() => renderAdminToolkitStore(), 800);
  }
});
