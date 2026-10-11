/* Runs in <head>, before first paint, so the page never flashes the wrong
   theme. An explicit choice (stored by sphere.js) wins; otherwise the OS
   preference decides through CSS and we only mirror it as .is-dark. */
(function () {
  var root = document.documentElement, t = null;
  try { t = localStorage.getItem('sphere-theme'); } catch (e) { /* storage blocked */ }
  if (t === 'light' || t === 'dark') root.setAttribute('data-theme', t);
  var dark = t ? t === 'dark' : !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
  root.classList.toggle('is-dark', dark);
  root.classList.remove('no-js');
})();
