/* TylonERP service worker {{ version }}: caches static files only; pages always come from the network. */
const CACHE = 'tylonerp-static-{{ version }}';
const PRECACHE = [
  '{{ url_for("pwa.offline") }}',
  '{{ url_for("static", filename="style.css") }}',
  '{{ url_for("static", filename="app.js") }}',
  '{{ url_for("static", filename="theme.js") }}',
  '{{ url_for("static", filename="vendor/bootstrap.min.css") }}',
  '{{ url_for("static", filename="vendor/bootstrap.bundle.min.js") }}',
  '{{ url_for("static", filename="fonts/instrument-sans.woff2") }}',
  '{{ url_for("static", filename="fonts/bricolage-grotesque.woff2") }}',
  '{{ url_for("static", filename="icons/icon-192.png") }}',
];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('tylonerp-') && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/static/')) {
    // Static files: cache first, refreshed in the background.
    e.respondWith(caches.open(CACHE).then(async c => {
      const hit = await c.match(req);
      const net = fetch(req).then(r => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match('{{ url_for("pwa.offline") }}')));
  }
});
