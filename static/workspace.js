"use strict";
function showWorkspaceView() {
  const view = location.hash.slice(1);
  document.body.dataset.view = ['history', 'activity', 'admin-users'].includes(view) ? view : 'workspace';
  document.querySelectorAll('.sidebar nav a').forEach(link => {
    const active = link.hash === '#' + document.body.dataset.view;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}
window.addEventListener('hashchange', showWorkspaceView);
showWorkspaceView();
document.querySelector('#new-essay').addEventListener('click', () => {
  document.body.classList.remove('has-result');
  document.querySelector('#result').hidden = true;
  location.hash = 'workspace';
  document.querySelector('#file').focus();
});
