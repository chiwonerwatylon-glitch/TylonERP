/* Offline screens: sell, count stock, add clients and record payments with no connection.
   Everything is saved on the phone through window.TylonStore and uploaded by the app when it can.
   Text from the server (names) is always inserted with textContent, never as HTML. */
(function () {
  'use strict';
  var S = window.TylonStore;
  var $ = function (id) { return document.getElementById(id); };
  var products = [], clients = [], debts = [], state = {};
  var tab = 'sell', chosen = null, lastSale = null;

  // ------------------------------------------------------------------ helpers
  function parse(s, fallback) { try { return JSON.parse(s); } catch (e) { return fallback; } }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function cents(v) {
    var s = String(v == null ? '' : v).trim();
    if (!/^\d{1,10}(\.\d{0,2})?$|^\.\d{1,2}$/.test(s)) return null;
    return Math.round(parseFloat(s) * 100);
  }
  function money(c) {
    var neg = c < 0, v = Math.abs(c), whole = Math.floor(v / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return (neg ? '-' : '') + whole + '.' + ('0' + (v % 100)).slice(-2);
  }
  function whole(v, max) { var s = String(v == null ? '' : v).trim(); if (!/^\d+$/.test(s)) return null; var n = parseInt(s, 10); return n <= (max || 1000000) ? n : null; }
  function tidy(s) { return String(s || '').trim().replace(/\s+/g, ' '); }
  // Same matching rule as the server: numeric codes match however many leading zeros they were read with.
  function bkey(code) {
    if (!code) return null;
    var c = String(code).replace(/[\x00-\x1f\x7f\s]+/g, '').replace(/^\][A-Za-z][0-9A-Za-z]/, '');
    if (!c) return null;
    if (!/^\d+$/.test(c)) return c;
    var core = c.replace(/^0+/, '') || '0';
    while (core.length < 14) core = '0' + core;
    return core;
  }
  function cleanCode(code) {
    var c = String(code || '').replace(/[\x00-\x1f\x7f\s]+/g, '').replace(/^\][A-Za-z][0-9A-Za-z]/, '');
    return /^\d{12}$/.test(c) ? '0' + c : c;
  }
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function when(ms) {
    var d = new Date(ms); if (isNaN(d)) return '';
    return ('0' + d.getDate()).slice(-2) + ' ' + MONTHS[d.getMonth()] + ', ' + ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }
  function alertBox(node, text, kind) {
    clear(node);
    if (!text) return;
    var d = el('div', 'alert py-2 my-2 alert-' + (kind === 'ok' ? 'success' : kind === 'error' ? 'danger' : 'secondary'));
    d.appendChild(el('span', null, text));
    node.appendChild(d);
  }
  function queue(kind, data, summary) {
    var r = parse(S.queue(kind, JSON.stringify(data), summary), {ok: false, error: 'The phone could not save that.'});
    load();
    renderAll();
    return r;
  }
  function productById(id) { for (var i = 0; i < products.length; i++) if (products[i].id === id) return products[i]; return null; }
  function productByCode(code) {
    var k = bkey(code); if (!k) return null;
    for (var i = 0; i < products.length; i++) if (bkey(products[i].barcode) === k) return products[i];
    return null;
  }
  function productByName(name) {
    var n = tidy(name).toLowerCase();
    for (var i = 0; i < products.length; i++) if (tidy(products[i].name).toLowerCase() === n) return products[i];
    return null;
  }

  // ------------------------------------------------------------------ data and status
  function load() {
    products = parse(S.products(), []);
    clients = parse(S.clients(), []);
    debts = parse(S.debts(), []);
    state = parse(S.state(), {});
  }

  function renderStatus() {
    var t = state.tenant || {};
    $('tname').textContent = t.name || 'TylonERP';
    $('markletter').textContent = (t.name || 'T').charAt(0).toUpperCase();
    var st = $('status'), text, cls = '';
    if (state.needs_sign_in) { text = 'Sign in again to upload your work'; cls = 'is-error'; }
    else if (state.syncing) { text = 'Uploading…'; cls = 'is-online'; }
    else if (state.pending > 0) { text = state.pending + (state.pending === 1 ? ' change' : ' changes') + ' waiting to upload'; }
    else if (state.failed > 0) { text = state.failed + (state.failed === 1 ? ' change was' : ' changes were') + ' not accepted. See Changes'; cls = 'is-error'; }
    else if (state.last_sync) { text = 'All uploaded, ' + when(state.last_sync); cls = state.online ? 'is-online' : ''; }
    else { text = 'Not synced yet'; }
    if (!state.online && !state.needs_sign_in) text = 'Offline. ' + text;
    st.textContent = text;
    st.className = 'off-status ' + cls;
    $('syncbtn').disabled = !!state.syncing;
    var b = $('badge'), n = (state.pending || 0) + (state.failed || 0);
    b.textContent = n > 99 ? '99+' : String(n);
    b.classList.toggle('hidden', n === 0);
    renderBanner();
  }

  var reason = (location.hash || '').slice(1);
  function renderBanner() {
    var banner = $('banner'), text = '', cls = '', btn = '';
    if (state.needs_sign_in) { text = 'This phone was signed out by the server. Sign in again; nothing you saved is lost.'; cls = 'is-error'; btn = 'Sign in'; }
    else if (state.online && reason !== 'chosen') { text = 'Connection is back.'; btn = 'Open full app'; }
    else if (reason === 'server') { text = 'The server cannot be reached right now. Keep working; it all uploads later.'; cls = 'is-warn'; }
    else if (reason === 'no-network' || reason === 'connection' || !state.online) { text = 'No connection. Keep working; it all uploads later.'; cls = 'is-warn'; }
    banner.className = 'off-banner ' + cls + (text ? '' : ' hidden');
    $('bannertext').textContent = text;
    $('bannerbtn').textContent = btn;
    $('bannerbtn').classList.toggle('hidden', !btn);
  }
  $('bannerbtn').onclick = function () {
    if (state.needs_sign_in) location.href = 'setup.html';
    else S.openOnline();
  };
  $('syncbtn').onclick = function () { S.sync(); state.syncing = true; renderStatus(); };

  function renderAll() {
    renderStatus();
    renderSellList();
    renderProducts();
    renderClients();
    renderDebts();
    renderChanges();
  }

  // ------------------------------------------------------------------ tabs
  function show(name) {
    tab = name;
    ['sell', 'stock', 'clients', 'debts', 'changes'].forEach(function (n) { $('pg-' + n).classList.toggle('hidden', n !== name); });
    Array.prototype.forEach.call(document.querySelectorAll('.off-tabs button'), function (b) { b.classList.toggle('active', b.dataset.tab === name); });
    if (name !== 'sell') stopCam('s');
    if (name !== 'stock') stopCam('k');
    window.scrollTo(0, 0);
  }
  Array.prototype.forEach.call(document.querySelectorAll('.off-tabs button'), function (b) { b.onclick = function () { show(b.dataset.tab); }; });

  // ------------------------------------------------------------------ camera (shared scanner from the web app)
  var cams = {s: {stream: null, stop: null}, k: {stream: null, stop: null}};
  function startCam(which, onCode) {
    var c = cams[which], box = $(which + 'cam'), video = $(which + 'v'), hint = $(which + 'hint');
    if (c.stream) { stopCam(which); return; }
    box.classList.remove('hidden');
    hint.textContent = 'Starting camera…';
    TT.startCamera(video).then(function (stream) {
      c.stream = stream;
      return TT.scanBarcodes(video, onCode, function (t) { hint.textContent = t; });
    }).then(function (stop) {
      c.stop = stop;
      hint.textContent = 'Hold the barcode inside the box';
    }).catch(function (e) {
      hint.textContent = (e && e.message) || 'The camera could not start.';
      stopCam(which, true);
    });
  }
  function stopCam(which, keepBox) {
    var c = cams[which];
    if (c.stop) { c.stop(); c.stop = null; }
    if (c.stream) { TT.stopCamera(c.stream, $(which + 'v')); c.stream = null; }
    if (!keepBox) $(which + 'cam').classList.add('hidden');
  }
  window.addEventListener('pagehide', function () { stopCam('s'); stopCam('k'); });

  // ------------------------------------------------------------------ sell
  function renderSellList() {
    var list = $('slist'), q = tidy($('sq').value).toLowerCase(), k = bkey(q), shown = 0;
    clear(list);
    var matches = products.filter(function (p) {
      return !q || p.name.toLowerCase().indexOf(q) >= 0 || (k && bkey(p.barcode) === k) || (p.sku && p.sku.toLowerCase() === q);
    });
    matches.slice(0, 60).forEach(function (p) {
      var b = el('button', 'pick');
      b.type = 'button';
      var g = el('div', 'grow');
      g.appendChild(el('div', 't', p.name));
      g.appendChild(el('div', 's', p.stock > 0 ? p.stock + ' in stock' : 'Out of stock'));
      b.appendChild(g);
      b.appendChild(el('div', 'price', money(cents(p.price) || 0)));
      if (p.stock <= 0) b.disabled = true;
      b.onclick = function () { openSale(p); };
      list.appendChild(b);
      shown++;
    });
    if (!shown) list.appendChild(el('div', 'empty-note', products.length ? 'No product matches that.' : 'No products on this phone yet. Connect once so they can download, or add them under Stock.'));
  }
  $('sq').oninput = renderSellList;
  $('sscan').onclick = function () {
    startCam('s', function (code) {
      var p = productByCode(code);
      stopCam('s');
      if (p) openSale(p);
      else { $('sq').value = code; renderSellList(); }
    });
  };

  function openSale(p) {
    if (p.stock <= 0) return;
    chosen = p;
    $('salename').textContent = p.name;
    $('saleinfo').textContent = p.stock + ' in stock at ' + money(cents(p.price) || 0) + ' each';
    var sel = $('client'); clear(sel);
    var o = el('option', null, 'Walk-in'); o.value = ''; sel.appendChild(o);
    clients.forEach(function (c) { var x = el('option', null, c.name); x.value = c.id; sel.appendChild(x); });
    $('qty').value = '1'; $('paid').value = ''; $('method').value = 'cash'; $('ophone').value = ''; $('oref').value = '';
    $('omwrap').classList.add('hidden');
    alertBox($('salemsg'), '');
    updateTotal();
    sheet('sale', true);
  }
  function updateTotal() {
    var q = whole($('qty').value) || 0;
    $('total').textContent = chosen ? money(q * (cents(chosen.price) || 0)) : '0.00';
  }
  $('qty').oninput = updateTotal;
  $('method').onchange = function () { $('omwrap').classList.toggle('hidden', this.value !== 'onemoney'); };
  $('saleclose').onclick = function () { sheet('sale', false); };
  $('sheetback').onclick = function () { sheet('sale', false); sheet('done', false); };

  $('sellbtn').onclick = function () {
    if (!chosen) return;
    var btn = this, q = whole($('qty').value);
    if (!q) { alertBox($('salemsg'), 'Enter how many to sell.', 'error'); return; }
    var paidRaw = $('paid').value.trim();
    if (paidRaw && cents(paidRaw) === null) { alertBox($('salemsg'), 'The amount paid is not a valid amount.', 'error'); return; }
    var total = q * (cents(chosen.price) || 0);
    var data = {product: chosen.id, quantity: q, unit_price: chosen.price, paid: paidRaw, client: $('client').value,
      method: $('method').value, phone: $('ophone').value.trim(), payment_ref: $('oref').value.trim(), at: Date.now()};
    btn.disabled = true;
    var summary = 'Sold ' + q + ' × ' + chosen.name + ' for ' + money(total);
    var r = queue('sale.create', data, summary);
    btn.disabled = false;
    if (!r.ok) { alertBox($('salemsg'), r.error, 'error'); return; }
    var paid = paidRaw ? Math.min(cents(paidRaw), total) : total;
    var cl = null; clients.forEach(function (c) { if (c.id === data.client) cl = c; });
    lastSale = {name: chosen.name, qty: q, unit: cents(chosen.price) || 0, total: total, paid: paid, client: cl ? cl.name : 'Walk-in',
      method: data.method === 'onemoney' ? 'OneMoney' : 'Cash', ref: data.payment_ref, at: data.at, id: r.op_id};
    sheet('sale', false);
    showReceipt(lastSale);
  };

  function receiptLines(s) {
    var t = state.tenant || {}, u = state.user || {};
    var lines = [['c b', t.name || 'TylonERP'], ['hr'], ['r', 'Date', when(s.at)], ['r', 'Served by', u.name || ''], ['r', 'Customer', s.client],
      ['hr'], ['', s.name], ['r', s.qty + ' x ' + money(s.unit), money(s.total)], ['hr'], ['r b', 'TOTAL', money(s.total)], ['r', 'Paid', money(s.paid)],
      ['r', 'Method', s.method]];
    if (s.ref) lines.push(['r', 'Ref', s.ref]);
    if (s.total > s.paid) lines.push(['r b', 'BALANCE DUE', money(s.total - s.paid)]);
    lines.push(['hr'], ['c', 'Thank you for your business'], ['c', 'Saved offline, uploads later']);
    return lines;
  }
  function showReceipt(s) {
    var box = $('receipt'); clear(box);
    receiptLines(s).forEach(function (l) {
      if (l[0] === 'hr') { box.appendChild(el('hr')); return; }
      var d = el('div', l[0] || null);
      if (l.length === 3) { d.appendChild(el('span', null, l[1])); d.appendChild(el('span', null, l[2])); } else d.textContent = l[1];
      box.appendChild(d);
    });
    sheet('done', true);
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  $('printbtn').onclick = function () {
    if (!lastSale) return;
    var body = receiptLines(lastSale).map(function (l) {
      if (l[0] === 'hr') return '<hr>';
      var cls = l[0] ? ' class="' + l[0] + '"' : '';
      return l.length === 3 ? '<div' + cls + '><span>' + esc(l[1]) + '</span><span>' + esc(l[2]) + '</span></div>' : '<div' + cls + '>' + esc(l[1]) + '</div>';
    }).join('');
    var html = '<!doctype html><html><head><meta charset="utf-8"><style>@page{size:80mm auto;margin:0}body{margin:0;padding:4mm;width:72mm;' +
      'font:12px/1.5 monospace;color:#111}.r{display:flex;justify-content:space-between;gap:8px}.c{text-align:center}.b{font-weight:700}' +
      'hr{border:0;border-top:1px dashed #888;margin:6px 0}</style></head><body>' + body + '</body></html>';
    S.printHtml(html, 'Receipt ' + lastSale.name);
  };
  $('donebtn').onclick = function () { sheet('done', false); $('sq').value = ''; renderSellList(); };

  function sheet(id, open) {
    $(id).classList.toggle('hidden', !open);
    var anyOpen = !$('sale').classList.contains('hidden') || !$('done').classList.contains('hidden');
    $('sheetback').classList.toggle('hidden', !anyOpen);
    document.body.style.overflow = anyOpen ? 'hidden' : '';
  }

  // ------------------------------------------------------------------ stock
  var busy = {};
  function klog(text, kind) {
    var d = el('div', 'alert py-2 my-2 alert-' + (kind === 'ok' ? 'success' : kind === 'error' ? 'danger' : 'secondary'));
    d.appendChild(el('span', null, text));
    var log = $('klog'); log.insertBefore(d, log.firstChild);
    while (log.children.length > 8) log.removeChild(log.lastChild);
  }
  function unitsPerScan() {
    var n = whole($('kqty').value);
    if (!n) { klog('Units per scan must be a whole number from 1 to 1,000,000.', 'error'); return null; }
    return n;
  }
  function handleCode(raw) {
    var code = cleanCode(raw);
    if (!code || busy[code]) return;
    var qty = unitsPerScan(); if (!qty) return;
    busy[code] = true;
    try {
      var p = productByCode(code);
      if (!p) { showNew(code); return; }
      var r = queue('stock.add', {product: p.id, quantity: qty, source: 'scan'}, 'Counted ' + qty + ' × ' + p.name);
      if (r.ok) { klog('Counted ' + p.name + ' (+' + qty + '), now ' + (productById(p.id) || p).stock + ' in stock', 'ok'); if (navigator.vibrate) navigator.vibrate(60); }
      else klog(r.error, 'error');
    } finally { delete busy[code]; }
  }
  function showNew(code) {
    $('knew').dataset.code = code;
    $('kcodeshow').textContent = code;
    var sel = $('klink'); clear(sel);
    var none = products.filter(function (p) { return !p.barcode; });
    var o = el('option', null, 'Choose a product without a barcode'); o.value = ''; sel.appendChild(o);
    none.forEach(function (p) { var x = el('option', null, p.name + ' (' + p.stock + ' in stock)'); x.value = p.id; sel.appendChild(x); });
    $('klinkwrap').classList.toggle('hidden', none.length === 0);
    $('kname').value = ''; $('kprice').value = '';
    $('knew').classList.remove('hidden');
  }
  function hideNew() { $('knew').classList.add('hidden'); delete $('knew').dataset.code; }
  $('kskip').onclick = hideNew;
  $('klinkbtn').onclick = function () {
    var code = $('knew').dataset.code, id = $('klink').value, qty = unitsPerScan();
    if (!code || !qty) return;
    if (!id) { $('klink').focus(); return; }
    var p = productById(id);
    var r = queue('stock.add', {product: id, quantity: qty, source: 'scan', barcode: code}, 'Linked barcode ' + code + ' to ' + (p ? p.name : '') + ', counted ' + qty);
    if (r.ok) { hideNew(); klog('Linked the barcode to ' + (p ? p.name : 'the product') + ' (+' + qty + ')', 'ok'); }
    else klog(r.error, 'error');
  };
  $('ksave').onclick = function () {
    var code = $('knew').dataset.code, qty = unitsPerScan(), name = tidy($('kname').value);
    if (!code || !qty) return;
    if (!name) { klog('Enter the product name.', 'error'); $('kname').focus(); return; }
    var existing = productByName(name), r;
    if (existing) {
      if (existing.barcode) { klog(existing.name + ' already has barcode ' + existing.barcode + '. If this is a different product, give it a different name, for example with its size.', 'error'); return; }
      r = queue('stock.add', {product: existing.id, quantity: qty, source: 'scan', barcode: code}, 'Linked barcode ' + code + ' to ' + existing.name + ', counted ' + qty);
    } else {
      if (cents($('kprice').value) === null) { klog('Enter a valid price for the new product.', 'error'); $('kprice').focus(); return; }
      r = queue('product.create', {name: name, price: $('kprice').value.trim(), barcode: code, stock: qty}, 'Registered ' + name + ' with ' + qty + ' in stock');
    }
    if (r.ok) { hideNew(); klog((existing ? 'Linked the barcode to ' : 'Registered ') + name + ' (+' + qty + ')', 'ok'); }
    else klog(r.error, 'error');
  };
  $('kscan').onclick = function () { startCam('k', handleCode); };
  $('kadd').onclick = function () { var v = $('kcode').value.trim(); if (v) { handleCode(v); $('kcode').value = ''; $('kcode').focus(); } };
  $('kcode').onkeydown = function (e) { if (e.key === 'Enter') { e.preventDefault(); $('kadd').click(); } };

  $('mform').onsubmit = function (e) {
    e.preventDefault();
    var name = tidy($('mname').value), qty = whole($('mqty').value);
    if (!name) { klog('Enter the product name.', 'error'); return; }
    if (cents($('mprice').value) === null) { klog('Enter a valid price.', 'error'); return; }
    if (qty === null) { klog('How many must be a whole number.', 'error'); return; }
    var code = cleanCode($('mbar').value);
    var r = queue('product.create', {name: name, price: $('mprice').value.trim(), stock: qty, barcode: code, sku: $('msku').value.trim()}, 'Added ' + name + ' with ' + qty + ' in stock');
    if (r.ok) { this.reset(); $('mqty').value = '1'; klog('Added ' + name + '.', 'ok'); window.scrollTo(0, 0); }
    else klog(r.error, 'error');
  };

  function renderProducts() {
    var list = $('plist'), q = tidy($('pfilter').value).toLowerCase();
    clear(list);
    $('pcount').textContent = products.length;
    products.filter(function (p) { return !q || p.name.toLowerCase().indexOf(q) >= 0 || (p.barcode || '').indexOf(q) >= 0; }).forEach(function (p) {
      var row = el('div', 'row-item');
      var g = el('div', 'grow');
      g.appendChild(el('div', 't', p.name));
      var low = p.stock <= (p.reorder_level || 0);
      g.appendChild(el('div', 's', (p.stock <= 0 ? 'Out of stock' : p.stock + ' in stock' + (low ? ', low' : '')) + ', ' + money(cents(p.price) || 0) + ' each'));
      row.appendChild(g);
      var grp = el('div', 'input-group input-group-sm');
      var inp = el('input', 'form-control'); inp.inputMode = 'numeric'; inp.placeholder = 'Qty'; inp.setAttribute('aria-label', 'Units to add to ' + p.name);
      var add = el('button', 'btn btn-outline-primary', 'Add'); add.type = 'button';
      add.onclick = function () {
        var n = whole(inp.value);
        if (!n) { inp.focus(); return; }
        var r = queue('stock.add', {product: p.id, quantity: n, source: 'restock'}, 'Added ' + n + ' to ' + p.name);
        if (!r.ok) klog(r.error, 'error');
      };
      grp.appendChild(inp); grp.appendChild(add);
      row.appendChild(grp);
      list.appendChild(row);
    });
    if (!list.firstChild) list.appendChild(el('div', 'empty-note', products.length ? 'No product matches that.' : 'No products yet.'));
  }
  $('pfilter').oninput = renderProducts;

  // ------------------------------------------------------------------ clients
  function renderClients() {
    var list = $('clist'); clear(list);
    $('ccount').textContent = clients.length;
    clients.forEach(function (c) {
      var row = el('div', 'row-item'), g = el('div', 'grow');
      g.appendChild(el('div', 't', c.name));
      if (c.phone) g.appendChild(el('div', 's', c.phone));
      row.appendChild(g);
      if (c.id.indexOf('l:') === 0) row.appendChild(el('span', 'status-pill pending', 'Waiting to upload'));
      list.appendChild(row);
    });
    if (!clients.length) list.appendChild(el('div', 'empty-note', 'No clients yet.'));
  }
  $('cform').onsubmit = function (e) {
    e.preventDefault();
    var name = tidy($('cname').value);
    if (!name) { $('cname').focus(); return; }
    var r = queue('client.create', {name: name, phone: $('cphone').value.trim()}, 'Added client ' + name);
    if (r.ok) this.reset();
  };

  // ------------------------------------------------------------------ debtors
  function renderDebts() {
    var list = $('dlist'), sum = 0; clear(list);
    debts.forEach(function (d) {
      sum += cents(d.balance) || 0;
      var row = el('div', 'row-item'), g = el('div', 'grow');
      g.appendChild(el('div', 't', d.client));
      g.appendChild(el('div', 's', d.product + ' × ' + d.quantity + ', owes ' + money(cents(d.balance) || 0)));
      row.appendChild(g);
      if (d.local) { row.appendChild(el('span', 'status-pill pending', 'Waiting to upload')); }
      else {
        var grp = el('div', 'input-group input-group-sm');
        var inp = el('input', 'form-control'); inp.inputMode = 'decimal'; inp.placeholder = 'Amount'; inp.setAttribute('aria-label', 'Payment from ' + d.client);
        var pay = el('button', 'btn btn-primary', 'Pay'); pay.type = 'button';
        pay.onclick = function () {
          var c = cents(inp.value);
          if (!c) { inp.focus(); return; }
          var r = queue('payment.create', {sale: d.id, amount: inp.value.trim()}, 'Payment of ' + money(c) + ' from ' + d.client);
          if (!r.ok) alert(r.error);
        };
        grp.appendChild(inp); grp.appendChild(pay); row.appendChild(grp);
      }
      list.appendChild(row);
    });
    $('dtotal').textContent = money(sum);
    if (!debts.length) list.appendChild(el('div', 'empty-note', 'Nobody owes you anything.'));
  }

  // ------------------------------------------------------------------ changes
  function renderChanges() {
    var box = $('syncbox'); clear(box);
    var p = state.pending || 0;
    box.appendChild(el('div', 'fw-semibold', state.syncing ? 'Uploading…' : p ? p + (p === 1 ? ' change is' : ' changes are') + ' waiting to upload.' : 'Everything on this phone has been uploaded.'));
    box.appendChild(el('div', 'small text-body-secondary mb-2', state.last_sync ? 'Last synced ' + when(state.last_sync) + '.' : 'Not synced yet.'));
    if (state.error) box.appendChild(el('div', 'small text-danger mb-2', state.error));
    var b = el('button', 'btn btn-primary btn-sm align-self-start', 'Sync now'); b.type = 'button'; b.disabled = !!state.syncing;
    b.onclick = function () { $('syncbtn').click(); };
    box.appendChild(b);

    var list = $('olist'); clear(list);
    var ops = parse(S.ops(), []);
    var label = {pending: 'Waiting', done: 'Uploaded', failed: 'Not accepted'};
    ops.forEach(function (o) {
      var row = el('div', 'row-item'), g = el('div', 'grow');
      g.appendChild(el('div', 't', o.summary || o.kind));
      g.appendChild(el('div', 's', when(o.created_at)));
      if (o.error) g.appendChild(el('div', 's text-danger', o.error));
      if (o.warning) g.appendChild(el('div', 's text-warning-emphasis', o.warning));
      row.appendChild(g);
      row.appendChild(el('span', 'status-pill ' + o.status, label[o.status] || o.status));
      if (o.status === 'failed') {
        var x = el('button', 'btn btn-sm btn-link', 'Dismiss'); x.type = 'button';
        x.onclick = function () { S.dismiss(o.op_id); load(); renderAll(); };
        row.appendChild(x);
      }
      list.appendChild(row);
    });
    if (!ops.length) list.appendChild(el('div', 'empty-note', 'Nothing recorded on this phone yet.'));
    var u = state.user || {}, t = state.tenant || {};
    $('whoami').textContent = (u.name ? u.name + ' (' + u.email + ')' : '') + (t.name ? ' at ' + t.name : '') + (state.server ? '. Server: ' + state.server : '') + '. App ' + (state.version || '');
  }
  $('goonline').onclick = function () { S.openOnline(); };
  $('signout').onclick = function () {
    var r = parse(S.signOut(false), {});
    if (r.ok) return;
    if (r.waiting && confirm(r.waiting + (r.waiting === 1 ? ' change has' : ' changes have') + ' not reached the server yet. Signing out deletes ' +
        (r.waiting === 1 ? 'it' : 'them') + ' from this phone for good. Sign out anyway?')) S.signOut(true);
  };

  // ------------------------------------------------------------------ calls from the app
  window.TylonOffline = {
    onSync: function (st) {
      for (var k in st) if (Object.prototype.hasOwnProperty.call(st, k)) state[k] = st[k];
      if (st.syncing) { renderStatus(); return; }
      load();
      renderAll();
    },
    onNetwork: function (online) { state.online = !!online; renderStatus(); },
    back: function () {
      if (!$('done').classList.contains('hidden')) { sheet('done', false); return true; }
      if (!$('sale').classList.contains('hidden')) { sheet('sale', false); return true; }
      if (!$('knew').classList.contains('hidden')) { hideNew(); return true; }
      if (cams.s.stream || cams.k.stream) { stopCam('s'); stopCam('k'); return true; }
      if (tab !== 'sell') { show('sell'); return true; }
      return false;
    }
  };

  load();
  renderAll();
})();
