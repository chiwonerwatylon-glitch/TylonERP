/* Colour theme: light, dark or follow the device. Stored per browser. */
(function () {
  var KEY = 'tt-theme', root = document.documentElement, mq = window.matchMedia('(prefers-color-scheme: dark)');
  function pref() { try { return localStorage.getItem(KEY) || 'auto'; } catch (e) { return 'auto'; } }
  function apply() {
    var p = pref();
    root.setAttribute('data-bs-theme', p === 'auto' ? (mq.matches ? 'dark' : 'light') : p);
    root.setAttribute('data-theme-pref', p);
    var m = document.querySelector('meta[name=theme-color]');
    if (m) m.content = root.getAttribute('data-bs-theme') === 'dark' ? '#1b1f23' : '#ffffff';
  }
  window.TTTheme = {set: function (v) { try { localStorage.setItem(KEY, v); } catch (e) {} apply(); }};
  apply();
  (mq.addEventListener ? mq.addEventListener('change', apply) : mq.addListener(apply));
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-theme-set]'); if (b) TTTheme.set(b.getAttribute('data-theme-set'));
  });
  window.addEventListener('storage', function (e) { if (e.key === KEY) apply(); });
})();
