/* Behaviour shared by every page.
   - A form posts once: its submit button locks while the request is on its way, so a double tap cannot
     record a sale, a payment or a client twice.
   - <form data-confirm="Question?"> asks first in a styled dialog instead of the browser's own pop-up.
     Optional: data-confirm-ok="Remove" (button text), data-confirm-danger (red button). */
(function () {
  'use strict';

  function lock(form, submitter) {
    // After the browser has collected the form's values, so a named submit button still sends its value.
    setTimeout(function () { lockNow(form, submitter); }, 0);
  }
  function lockNow(form, submitter) {
    var btns = submitter ? [submitter] : form.querySelectorAll('button[type=submit], button:not([type]), input[type=submit]');
    Array.prototype.forEach.call(btns, function (b) {
      b.disabled = true;
      b.setAttribute('aria-busy', 'true');
      b.classList.add('is-busy');
    });
  }

  function unlockAll() {
    Array.prototype.forEach.call(document.querySelectorAll('form[data-busy]'), function (f) { f.dataset.busy = ''; });
    Array.prototype.forEach.call(document.querySelectorAll('.is-busy'), function (b) {
      b.disabled = false; b.removeAttribute('aria-busy'); b.classList.remove('is-busy');
    });
  }
  // Coming back with the browser's Back button shows the page from cache: make its buttons usable again.
  window.addEventListener('pageshow', function (e) { if (e.persisted) unlockAll(); });

  var dialog = null, pending = null;
  function getDialog() {
    if (dialog) return dialog;
    var el = document.createElement('div');
    el.className = 'modal fade';
    el.tabIndex = -1;
    el.setAttribute('aria-hidden', 'true');
    el.setAttribute('aria-labelledby', 'confirmTitle');
    el.innerHTML =
      '<div class="modal-dialog modal-dialog-centered"><div class="modal-content">' +
      '<div class="modal-body"><h2 class="h5 mb-2" id="confirmTitle"></h2><p class="text-body-secondary mb-0" id="confirmText"></p></div>' +
      '<div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>' +
      '<button type="button" class="btn" id="confirmOk"></button></div></div></div>';
    document.body.appendChild(el);
    var modal = window.bootstrap ? new bootstrap.Modal(el) : null;
    el.querySelector('#confirmOk').addEventListener('click', function () {
      var p = pending; pending = null;
      if (modal) modal.hide();
      if (p) { p.form.dataset.confirmed = '1'; lock(p.form, p.submitter); p.form.submit(); }
    });
    dialog = {el: el, modal: modal};
    return dialog;
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || e.defaultPrevented) return;
    if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;
    var question = form.getAttribute('data-confirm');
    if (question && form.dataset.confirmed !== '1') {
      e.preventDefault();
      var d = getDialog();
      if (!d.modal) { if (window.confirm(question)) { form.dataset.confirmed = '1'; lock(form, e.submitter); form.submit(); } return; }
      var parts = question.split('\n');
      d.el.querySelector('#confirmTitle').textContent = parts[0];
      d.el.querySelector('#confirmText').textContent = parts.slice(1).join(' ') || '';
      d.el.querySelector('#confirmText').classList.toggle('d-none', parts.length < 2);
      var ok = d.el.querySelector('#confirmOk');
      ok.textContent = form.getAttribute('data-confirm-ok') || 'Continue';
      ok.className = 'btn ' + (form.hasAttribute('data-confirm-danger') ? 'btn-danger' : 'btn-primary');
      pending = {form: form, submitter: e.submitter};
      d.modal.show();
      return;
    }
    if (form.dataset.busy === '1') { e.preventDefault(); return; }
    form.dataset.busy = '1';
    lock(form, e.submitter);
    // Downloads and new tabs leave this page in place; let its form be used again.
    if (form.target === '_blank') setTimeout(function () { form.dataset.busy = ''; unlockAll(); }, 1500);
  });
})();
