/* The Register: a cart-based point of sale.
   The page prices the cart the same way the server does so the cashier sees totals at once, but the server
   recalculates everything on checkout and its numbers are the ones recorded.
   The cart and held carts live in this browser (localStorage), so a refresh or a dropped connection loses nothing.
   Product names come from the business's own data and are always inserted as text, never as HTML. */
(function () {
  'use strict';
  var D = JSON.parse(document.getElementById('regData').textContent);
  var cfg = D.cfg, T = D.t, $ = function (id) { return document.getElementById(id); };
  var products = D.products, byId = {};
  products.forEach(function (p) { byId[p.id] = p; });
  var DEC = cfg.decimals, POW = Math.pow(10, DEC), RATE = parseFloat(cfg.tax.rate) || 0, INCL = cfg.tax.inclusive;
  var ALT = cfg.alt, ALT_RATE = ALT ? parseFloat(ALT.rate) : 0, ALT_POW = ALT ? Math.pow(10, ALT.decimals) : 1;
  var KEY = 'tt-cart-' + D.slug, HELD = 'tt-held-' + D.slug;

  function t(s, vals) { var out = T[s] || s; if (vals) Object.keys(vals).forEach(function (k) { out = out.replace('{' + k + '}', vals[k]); }); return out; }
  function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || 'null'); localStorage.setItem(k, JSON.stringify(v)); } catch (e) { return null; } }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  // ------------------------------------------------------------ money
  var fmtCache = {};
  function fmt(minor, code, pow, decimals) {
    code = code || cfg.currency; pow = pow || POW; decimals = decimals == null ? DEC : decimals;
    var key = code + decimals, f = fmtCache[key];
    if (!f) {
      try { f = new Intl.NumberFormat(cfg.locale, {style: 'currency', currency: code, minimumFractionDigits: decimals, maximumFractionDigits: decimals}); }
      catch (e) { f = {format: function (v) { return code + ' ' + v.toFixed(decimals); }}; }
      fmtCache[key] = f;
    }
    var out = f.format(minor / pow);
    var sym = code === cfg.currency ? cfg.symbol : (ALT && code === ALT.currency ? ALT.symbol : null);
    return sym && out.indexOf(code) >= 0 && sym !== code ? out.replace(code, sym) : out;
  }
  function fmtAlt(minor) { return fmt(minor, ALT.currency, ALT_POW, ALT.decimals); }
  function toMinor(v, pow) { var n = parseFloat(String(v == null ? '' : v).replace(/[^\d.\-]/g, '')); return isFinite(n) ? Math.round(n * (pow || POW)) : null; }
  function priceMinor(p) { return Math.round(parseFloat(p.price) * 100); }  // stored with 2 decimals

  // ------------------------------------------------------------ cart
  var cart = store(KEY) || {lines: [], discount: null, client: ''};
  cart.lines = (cart.lines || []).filter(function (l) { return byId[l.id]; });
  function save() { store(KEY, cart); }

  function price() {
    var rows = cart.lines.map(function (l) {
      var p = byId[l.id], gross = Math.round(priceMinor(p) * l.qty * POW / 100);
      var ld = l.pct ? Math.round(gross * l.pct / 100) : 0;
      return {l: l, p: p, gross: gross, ld: ld, after: gross - ld};
    });
    var base = rows.reduce(function (a, r) { return a + r.after; }, 0), od = 0;
    if (cart.discount && base > 0) {
      od = cart.discount.type === 'pct' ? Math.round(base * Math.min(cart.discount.value, 100) / 100) : Math.min(toMinor(cart.discount.value), base);
    }
    var left = od, sub = 0, disc = 0, tax = 0, total = 0;
    rows.forEach(function (r, i) {
      var share = i === rows.length - 1 ? left : (base ? Math.round(od * r.after / base) : 0);
      share = Math.min(share, r.after, left); left -= share;
      var net = r.after - share, tx = RATE > 0 ? Math.round(INCL ? net * RATE / (100 + RATE) : net * RATE / 100) : 0;
      r.total = INCL ? net : net + tx;
      sub += r.gross; disc += r.ld + share; tax += tx; total += r.total;
    });
    return {rows: rows, sub: sub, disc: disc, tax: tax, total: total};
  }

  function inCart(id) { return cart.lines.reduce(function (a, l) { return a + (l.id === id ? l.qty : 0); }, 0); }

  function add(id, qty) {
    var p = byId[id]; qty = qty || 1;
    if (!p) return;
    if (inCart(id) + qty > p.stock) { toast(p.stock > 0 ? t('Only {n} in stock', {n: p.stock}) : t('Out of stock'), true); return; }
    var line = cart.lines.find(function (l) { return l.id === id && !l.pct; });
    if (line) line.qty += qty; else cart.lines.push({id: id, qty: qty, pct: 0});
    save(); render(id);
  }

  // ------------------------------------------------------------ shelf
  var cat = '', query = '';
  function initials(name) {
    var words = name.split(/\s+/).map(function (w) { return w.replace(/[^\p{L}\p{N}]/gu, ''); }).filter(Boolean);
    return words.slice(0, 2).map(function (w) { return Array.from(w)[0]; }).join('').toUpperCase() || '•';
  }
  function hue(name) { var h = 0; for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360; return h; }
  function drawGrid() {
    var grid = $('grid'); grid.textContent = '';
    var q = query.toLowerCase().trim(), shown = 0;
    products.forEach(function (p) {
      if (cat && p.category !== cat) return;
      if (q && (p.name + ' ' + p.barcode + ' ' + p.sku + ' ' + p.category).toLowerCase().indexOf(q) < 0) return;
      if (shown >= 300) return;
      shown++;
      var b = el('button', 'tile' + (p.stock <= 0 ? ' out' : '')); b.type = 'button'; b.dataset.id = p.id;
      var pic = el('span', 'tile-pic');
      if (p.photo) { var img = el('img'); img.src = p.photo; img.alt = ''; img.loading = 'lazy'; pic.appendChild(img); }
      else { pic.textContent = initials(p.name); pic.style.setProperty('--h', hue(p.name)); }
      b.appendChild(pic);
      b.appendChild(el('span', 'tile-name', p.name));
      var foot = el('span', 'tile-foot');
      foot.appendChild(el('b', null, fmt(Math.round(priceMinor(p) * POW / 100))));
      foot.appendChild(el('small', p.stock <= 0 ? 'zero' : '', p.stock <= 0 ? t('Out of stock') : String(p.stock)));
      b.appendChild(foot);
      var n = inCart(p.id); if (n) b.appendChild(el('span', 'tile-qty', String(n)));
      b.setAttribute('aria-label', p.name + ', ' + foot.firstChild.textContent);
      grid.appendChild(b);
    });
    $('none').classList.toggle('hidden', shown > 0 || !products.length);
  }
  $('grid').addEventListener('click', function (e) { var b = e.target.closest('.tile'); if (b && !b.classList.contains('out')) add(+b.dataset.id); });
  document.querySelectorAll('.reg-cats .chip').forEach(function (c) {
    c.addEventListener('click', function () { cat = c.dataset.cat; document.querySelectorAll('.reg-cats .chip').forEach(function (x) { x.classList.toggle('on', x === c); }); drawGrid(); });
  });

  // ------------------------------------------------------------ ticket
  function render(flash) {
    var pr = price(), ol = $('lines'); ol.textContent = '';
    pr.rows.forEach(function (r, i) {
      var li = el('li', 'tk-line' + (r.l.id === flash ? ' flash' : ''));
      var top = el('div', 'tk-row');
      top.appendChild(el('span', 'tk-name', r.p.name));
      top.appendChild(el('b', 'tk-amt', fmt(r.gross - r.ld)));
      li.appendChild(top);
      var bot = el('div', 'tk-row tk-sub');
      var step = el('div', 'stepper');
      var minus = el('button', null, '−'); minus.type = 'button'; minus.setAttribute('aria-label', t('Remove') + ' 1');
      var qty = el('input'); qty.value = r.l.qty; qty.inputMode = 'numeric'; qty.setAttribute('aria-label', r.p.name);
      var plus = el('button', null, '+'); plus.type = 'button'; plus.setAttribute('aria-label', '+1');
      minus.onclick = function () { r.l.qty -= 1; if (r.l.qty <= 0) cart.lines.splice(i, 1); save(); render(); };
      plus.onclick = function () { if (inCart(r.l.id) + 1 > r.p.stock) return toast(t('Only {n} in stock', {n: r.p.stock}), true); r.l.qty += 1; save(); render(); };
      qty.onchange = function () { var n = parseInt(qty.value, 10); var other = inCart(r.l.id) - r.l.qty; if (!(n > 0)) { cart.lines.splice(i, 1); } else { r.l.qty = Math.min(n, r.p.stock - other); if (n > r.p.stock - other) toast(t('Only {n} in stock', {n: r.p.stock}), true); } save(); render(); };
      step.appendChild(minus); step.appendChild(qty); step.appendChild(plus);
      bot.appendChild(step);
      var info = el('span', 'tk-each', '× ' + fmt(Math.round(priceMinor(r.p) * POW / 100)) + (r.l.pct ? '  −' + r.l.pct + '%' : ''));
      info.title = t('Discount'); info.tabIndex = 0;
      info.onclick = function () { var v = prompt(t('Discount') + ' % — ' + r.p.name, r.l.pct || ''); if (v === null) return; var n = parseFloat(v); r.l.pct = n > 0 && n <= 100 ? n : 0; save(); render(); };
      bot.appendChild(info);
      li.appendChild(bot);
      ol.appendChild(li);
    });
    var items = cart.lines.reduce(function (a, l) { return a + l.qty; }, 0);
    $('tkEmpty').classList.toggle('hidden', items > 0);
    $('count').textContent = items ? items + ' ' + (items === 1 ? t('Item') : t('Items')).toLowerCase() : '';
    $('sub').textContent = fmt(pr.sub);
    $('disc').textContent = pr.disc ? '−' + fmt(pr.disc) : '';
    document.querySelector('.tk-disc').classList.toggle('has', pr.disc > 0);
    if ($('tax')) { $('taxLabel').textContent = (INCL ? t('includes') + ' ' : '') + cfg.tax.name + ' ' + cfg.tax.rate.replace(/\.?0+$/, '') + '%'; $('tax').textContent = fmt(pr.tax); }
    $('total').textContent = fmt(pr.total);
    if (ALT && $('altTotal')) $('altTotal').textContent = '≈ ' + fmtAlt(Math.round(pr.total / POW * ALT_RATE * ALT_POW));
    $('chargeBtn').disabled = !items;
    $('barCount').textContent = items ? items + ' ' + (items === 1 ? t('Item') : t('Items')) : t('Cart is empty');
    $('barTotal').textContent = fmt(pr.total);
    $('cust').value = cart.client || '';
    drawGrid();
    if (flash) setTimeout(function () { var f = ol.querySelector('.flash'); if (f) { f.scrollIntoView({block: 'nearest'}); f.classList.remove('flash'); } }, 400);
    return pr;
  }
  $('cust').onchange = function () { cart.client = this.value; save(); };
  $('clearBtn').onclick = function () { if (!cart.lines.length || confirm(t('Clear the cart?'))) { cart = {lines: [], discount: null, client: ''}; save(); render(); } };

  // mobile: the ticket slides up over the shelf
  $('openTicket').onclick = function () { document.body.classList.add('ticket-open'); };
  $('closeTicket').onclick = function () { document.body.classList.remove('ticket-open'); };

  // ------------------------------------------------------------ hold and resume
  function held() { return store(HELD) || []; }
  function drawHeld() {
    var list = held(), m = $('heldMenu'); m.textContent = '';
    $('heldPip').classList.toggle('hidden', !list.length);
    if (!list.length) { m.appendChild(el('div', 'dropdown-item-text text-body-secondary small', t('Nothing held'))); return; }
    m.appendChild(el('h6', 'dropdown-header', t('Held carts')));
    list.forEach(function (h, i) {
      var b = el('button', 'dropdown-item d-flex justify-content-between gap-3'); b.type = 'button';
      b.appendChild(el('span', null, h.label));
      b.appendChild(el('small', 'text-body-secondary', new Date(h.at).toLocaleTimeString(cfg.locale, {hour: '2-digit', minute: '2-digit'})));
      b.onclick = function () {
        var l = held(); var pick = l.splice(i, 1)[0]; if (cart.lines.length) l.push(snapshot()); store(HELD, l);
        cart = pick.cart; cart.lines = cart.lines.filter(function (x) { return byId[x.id]; }); save(); render(); drawHeld(); toast(t('Resume'));
      };
      m.appendChild(b);
    });
  }
  function snapshot() {
    var n = cart.lines.reduce(function (a, l) { return a + l.qty; }, 0), c = $('cust').selectedOptions[0];
    return {cart: cart, at: Date.now(), label: (cart.client && c ? c.textContent : fmt(price().total)) + ' · ' + n + ' ' + (n === 1 ? t('Item') : t('Items'))};
  }
  $('holdBtn').onclick = function () {
    if (!cart.lines.length) return toast(t('Cart is empty'), true);
    var l = held(); l.push(snapshot()); store(HELD, l);
    cart = {lines: [], discount: null, client: ''}; save(); render(); drawHeld(); toast(t('Saved for later'));
  };

  // ------------------------------------------------------------ discount
  var discModal = null;
  $('discBtn').onclick = function () {
    discModal = discModal || new bootstrap.Modal($('discModal'));
    var d = cart.discount || {type: 'pct', value: ''};
    $(d.type === 'amt' ? 'damt' : 'dpct').checked = true; $('dval').value = d.value || '';
    discModal.show(); setTimeout(function () { $('dval').focus(); }, 300);
  };
  document.querySelectorAll('[data-dq]').forEach(function (b) { b.onclick = function () { $('dpct').checked = true; $('dval').value = b.dataset.dq; }; });
  $('dapply').onclick = function () {
    var v = parseFloat($('dval').value), type = $('damt').checked ? 'amt' : 'pct';
    cart.discount = v > 0 ? {type: type, value: type === 'pct' ? Math.min(v, 100) : v} : null; save(); render(); discModal.hide();
  };
  $('dclear').onclick = function () { cart.discount = null; save(); render(); discModal.hide(); };

  // ------------------------------------------------------------ search and scanning
  function bkey(code) { var c = String(code || '').replace(/[\x00-\x1f\x7f\s]+/g, '').replace(/^\][A-Za-z][0-9A-Za-z]/, ''); return /^\d+$/.test(c) ? c.replace(/^0+/, '') : c.toLowerCase(); }
  function byCode(code) {
    var k = bkey(code); if (!k) return null;
    return products.find(function (p) { return (p.barcode && bkey(p.barcode) === k) || (p.sku && p.sku.toLowerCase() === k); });
  }
  async function scanned(code) {
    var p = byCode(code);
    if (p) { add(p.id); beep(); return true; }
    try {  // the server also matches a UPC-A label against its EAN-13 form
      var r = await TT.post(D.urls.match, {barcode: code});
      if (r.matches && r.matches.length && byId[r.matches[0].id]) { add(r.matches[0].id); beep(); return true; }
    } catch (e) {}
    toast(t('Unknown barcode') + ': ' + code, true); return false;
  }
  $('q').addEventListener('input', function () { query = this.value; drawGrid(); });
  $('q').addEventListener('keydown', async function (e) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    var v = this.value.trim(); if (!v) return;
    if (byCode(v) || /^\d{6,}$/.test(v)) { if (await scanned(v)) { this.value = ''; query = ''; drawGrid(); } return; }
    var first = $('grid').querySelector('.tile:not(.out)'); if (first) { add(+first.dataset.id); this.select(); }
  });
  // A hardware scanner types fast and ends with Enter. Catch it even when the search box does not have focus.
  var buf = '', last = 0;
  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if (e.key === 'F2' || (e.key === '/' && tag !== 'input' && tag !== 'textarea' && tag !== 'select')) { e.preventDefault(); $('q').focus(); $('q').select(); return; }
    if ((e.key === 'F9' || (e.key === 'Enter' && (e.ctrlKey || e.metaKey))) && !$('chargeBtn').disabled) { e.preventDefault(); openPay(); return; }
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || document.querySelector('.modal.show')) return;
    var now = Date.now();
    if (now - last > 60) buf = '';
    last = now;
    if (e.key === 'Enter') { if (buf.length >= 4) { e.preventDefault(); scanned(buf); } buf = ''; }
    else if (e.key.length === 1) buf += e.key;
  });
  var stopScan = null, stream = null;
  $('camBtn').onclick = async function () {
    if (stopScan || stream) { if (stopScan) stopScan(); TT.stopCamera(stream, $('v')); stopScan = stream = null; $('camWrap').classList.add('hidden'); this.classList.remove('active'); return; }
    try {
      $('camWrap').classList.remove('hidden'); this.classList.add('active');
      stream = await TT.startCamera($('v'));
      stopScan = await TT.scanBarcodes($('v'), function (code) { scanned(code); }, function (h) { $('hint').textContent = h; });
    } catch (e) { $('camWrap').classList.add('hidden'); this.classList.remove('active'); toast(e.message, true); }
  };
  var ac = null;
  function beep() {
    try { ac = ac || new (window.AudioContext || window.webkitAudioContext)(); var o = ac.createOscillator(), g = ac.createGain(); o.frequency.value = 1320; g.gain.value = .06; o.connect(g); g.connect(ac.destination); o.start(); o.stop(ac.currentTime + .07); } catch (e) {}
    if (navigator.vibrate) navigator.vibrate(30);
  }

  // ------------------------------------------------------------ toast
  var toastEl = null, toastTimer = null;
  function toast(msg, bad) {
    if (!toastEl) { toastEl = el('div', 'reg-toast'); toastEl.setAttribute('role', 'status'); document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.classList.toggle('bad', !!bad); toastEl.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { toastEl.classList.remove('show'); }, 2200);
  }

  // ------------------------------------------------------------ payment
  var payModal = null, method = 'cash', due = 0, ref = null;
  function tenderAlt() { return ALT && $('talt') && $('talt').checked; }
  function openPay() {
    var pr = render(); due = pr.total; if (!cart.lines.length) return;
    ref = ref || TT.uid();
    payModal = payModal || new bootstrap.Modal($('payModal'));
    $('payDue').textContent = fmt(due);
    if (ALT && $('payDueAlt')) $('payDueAlt').textContent = fmtAlt(Math.round(due / POW * ALT_RATE * ALT_POW)) + '  ·  1 ' + cfg.currency + ' = ' + ALT.rate.replace(/\.?0+$/, '') + ' ' + ALT.currency;
    $('tendered').value = ''; $('cpaid').value = ''; $('payErr').classList.add('hidden');
    $('ccust').value = cart.client || '';
    setMethod(method === 'ecocash' && !document.querySelector('[data-m=ecocash]') ? 'cash' : method);
    quick(); change();
    payModal.show();
    setTimeout(function () { var f = document.querySelector('.pp:not(.hidden) input'); if (f && window.innerWidth > 600) f.focus(); }, 300);
  }
  $('chargeBtn').onclick = openPay;
  function setMethod(m) {
    method = m;
    document.querySelectorAll('.pm').forEach(function (b) { b.classList.toggle('on', b.dataset.m === m); b.setAttribute('aria-checked', b.dataset.m === m); b.setAttribute('role', 'radio'); });
    document.querySelectorAll('.pp').forEach(function (p) { p.classList.toggle('hidden', p.dataset.p !== m); });
    $('payErr').classList.add('hidden');
  }
  document.querySelectorAll('.pm').forEach(function (b) { b.onclick = function () { setMethod(b.dataset.m); }; });
  function dueIn() { return tenderAlt() ? {minor: Math.round(due / POW * ALT_RATE * ALT_POW), pow: ALT_POW, f: fmtAlt} : {minor: due, pow: POW, f: function (v) { return fmt(v); }}; }
  function quick() {
    var q = $('quick'); q.textContent = ''; var d = dueIn(), unit = d.pow, amt = d.minor / unit;
    var steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000];
    var opts = [d.minor];
    steps.forEach(function (s) { var v = Math.ceil(amt / s) * s * unit; if (v > d.minor && opts.indexOf(v) < 0 && opts.length < 5) opts.push(v); });
    opts.forEach(function (v, i) {
      var b = el('button', 'btn btn-outline-secondary', i === 0 ? t('Exact') : d.f(v)); b.type = 'button';
      b.onclick = function () { $('tendered').value = (v / unit).toFixed(Math.round(Math.log10(unit))); change(); };
      q.appendChild(b);
    });
  }
  function change() {
    var d = dueIn(), raw = $('tendered').value.trim(), got = raw ? toMinor(raw, d.pow) : d.minor;
    var box = $('changeBox');
    if (got == null) { box.className = 'pay-change'; $('change').textContent = ''; return; }
    var diff = got - d.minor;
    box.className = 'pay-change ' + (diff >= 0 ? 'ok' : 'short');
    $('changeLbl').textContent = diff >= 0 ? t('Change due') : t('Short by');
    $('change').textContent = d.f(Math.abs(diff));
  }
  $('tendered').addEventListener('input', change);
  $('tendered').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); pay(); } });
  document.querySelectorAll('[name=tcur]').forEach(function (r) { r.onchange = function () { $('tendered').value = ''; quick(); change(); }; });

  function payErr(msg) { var e = $('payErr'); e.textContent = msg; e.classList.remove('hidden'); }
  var lastReceipt = null;
  async function pay() {
    var body = {ref: ref, method: method, client_id: cart.client || '',
      items: cart.lines.map(function (l) { return {product_id: l.id, quantity: l.qty, discount_pct: l.pct || 0}; }),
      discount: cart.discount ? {type: cart.discount.type, value: String(cart.discount.value)} : null};
    if (method === 'cash') {
      body.tendered = $('tendered').value.trim(); body.tender_currency = tenderAlt() ? ALT.currency : cfg.currency;
      var d = dueIn(), got = body.tendered ? toMinor(body.tendered, d.pow) : d.minor;
      if (got == null) return payErr(t('Enter the cash received'));
      if (got < d.minor && !cart.client) return payErr(t('Not enough cash') + '. ' + t('Choose a customer for credit or part payment'));
    } else if (method === 'card') { body.payment_ref = $('cardRef').value; }
    else if (method === 'bank') { body.payment_ref = $('bref').value; }
    else if (method === 'mobile') { body.provider = $('provider').value; body.phone = $('mphone').value; body.payment_ref = $('mref').value.trim(); if (!body.payment_ref) return payErr(t('Enter the transaction code')); }
    else if (method === 'ecocash') { body.phone = $('ephone').value.trim(); if (!body.phone) return payErr(t("Enter the customer's EcoCash number")); }
    else if (method === 'credit') { body.client_id = $('ccust').value; body.paid = $('cpaid').value.trim(); if (!body.client_id) return payErr(t('Choose a customer for credit or part payment')); }
    var btn = $('payBtn'); btn.disabled = true; btn.classList.add('is-busy');
    if (method === 'ecocash') payErr(t('Waiting for the customer to approve…'));
    var r;
    try { r = await TT.post(D.urls.checkout, body); }
    catch (e) { r = {error: t('No connection. Check the network and try again.'), offline: true}; }
    btn.disabled = false; btn.classList.remove('is-busy');
    if (!r.ok) {
      if (r.stock != null && r.product && byId[r.product]) { byId[r.product].stock = r.stock; render(); }
      return payErr(r.error || t('Checkout failed'));
    }
    Object.keys(r.stock || {}).forEach(function (id) { if (byId[id]) byId[id].stock = r.stock[id]; });
    payModal.hide();
    lastReceipt = r.receipt;
    $('doneSub').textContent = t('Receipt') + ' #' + String(r.number).padStart(6, '0') + ' · ' + r.total_fmt + (r.balance_fmt ? ' · ' + t('Still owed') + ' ' + r.balance_fmt : '');
    $('doneChangeBox').classList.toggle('hidden', !r.change_fmt); $('doneChange').textContent = r.change_fmt || '';
    $('doneWarn').classList.toggle('hidden', !r.warning); $('doneWarn').textContent = r.warning || '';
    cart = {lines: [], discount: null, client: ''}; ref = null; save(); render();
    document.body.classList.remove('ticket-open');
    new bootstrap.Modal($('doneModal')).show();
    setTimeout(function () { $('newSale').focus(); }, 300);
  }
  $('payBtn').onclick = pay;
  $('newSale').onclick = function () { bootstrap.Modal.getInstance($('doneModal')).hide(); setTimeout(function () { if (window.innerWidth > 991) $('q').focus(); }, 200); };
  $('printBtn').onclick = function () {
    if (!lastReceipt) return;
    var url = new URL(lastReceipt.replace('print=1', 'print=0'), location.href).href;
    if (window.TylonAndroid && TylonAndroid.printUrl) { TylonAndroid.printUrl(url); return; }
    if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.printUrl) { window.webkit.messageHandlers.printUrl.postMessage(url); return; }
    var old = $('rframe'); if (old) old.remove();
    var f = el('iframe'); f.id = 'rframe'; f.style.cssText = 'position:fixed;width:0;height:0;border:0;opacity:0'; f.src = url;
    f.onload = function () { try { f.contentWindow.focus(); f.contentWindow.print(); } catch (e) { window.open(url, '_blank'); } };
    document.body.appendChild(f);
  };

  render(); drawHeld();
  window.addEventListener('pagehide', function () { if (stopScan) stopScan(); if (stream) TT.stopCamera(stream, $('v')); });
})();
