/* First sign-in on the phone. The phone's bridge (TylonStore) does the network call. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var S = window.TylonStore;

  function say(text, kind) {
    var m = $('msg');
    m.innerHTML = '';
    if (!text) return;
    var d = document.createElement('div');
    d.className = 'alert alert-' + (kind === 'ok' ? 'success' : 'danger');
    var s = document.createElement('span'); s.textContent = text; d.appendChild(s);
    m.appendChild(d);
  }

  function busy(on) {
    var b = $('go');
    b.disabled = on;
    b.textContent = on ? 'Signing in…' : 'Sign in';
  }

  var d = {};
  try { d = JSON.parse(S.defaults()); } catch (e) { d = {}; }
  $('server').value = d.server && d.server !== 'https://' ? d.server : '';
  $('slug').value = d.slug || '';
  $('email').value = d.email || '';
  if (!$('server').value || !d.slug) $('serverbox').open = true;  // first sign-in: show where it will connect

  $('pwt').onclick = function () {
    var i = $('password'), on = i.type === 'password';
    i.type = on ? 'text' : 'password';
    this.setAttribute('aria-pressed', String(on));
    this.setAttribute('aria-label', on ? 'Hide password' : 'Show password');
  };

  // A pasted sign-in link fills the server address too.
  $('slug').addEventListener('change', function () {
    var v = this.value.trim(), i = v.indexOf('/t/');
    if (i > 0 && /^https?:\/\//.test(v)) {
      $('server').value = v.slice(0, i);
      this.value = v.slice(i + 3).split('/')[0];
    }
  });

  $('f').addEventListener('submit', function (e) {
    e.preventDefault();
    var server = $('server').value.trim(), slug = $('slug').value.trim(), email = $('email').value.trim(), pw = $('password').value;
    if (!server) { $('serverbox').open = true; $('server').focus(); say('Enter the server address.'); return; }
    if (!slug) { $('slug').focus(); say('Enter your business sign-in name.'); return; }
    if (!email || !pw) { (email ? $('password') : $('email')).focus(); say('Enter your email and password.'); return; }
    say('');
    busy(true);
    S.login(server, slug, email, pw);
  });

  window.TylonSetup = {
    onLogin: function (r) {
      if (r && r.ok) {
        say(r.must_change_password ? 'Signed in. You will be asked to choose a new password.' : 'Signed in. Opening your workspace…', 'ok');
        $('go').textContent = 'Opening…';
      } else {
        busy(false);
        say((r && r.error) || 'Sign-in failed. Try again.');
      }
    }
  };
})();
