/* Browser-only integration. Session bearer cookies remain HttpOnly. */
(() => {
  'use strict';
  const csrf = () => document.cookie.split(';').map(x => x.trim())
    .find(x => x.startsWith('__Host-calibre-csrf='))?.split('=')[1] || '';
  const urls = new WeakMap();
  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    urls.set(this, new URL(url, location.href).origin);
    return open.call(this, method, url, ...args);
  };
  XMLHttpRequest.prototype.send = function(...args) {
    const token = csrf();
    if (token && urls.get(this) === location.origin) this.setRequestHeader('X-Calibre-CSRF', token);
    return send.apply(this, args);
  };
  const fetch = window.fetch.bind(window);
  window.fetch = function(input, init) {
    const request = new Request(input, init);
    const token = csrf();
    if (token && new URL(request.url).origin === location.origin) {
      const headers = new Headers(request.headers);
      headers.set('X-Calibre-CSRF', token);
      return fetch(new Request(request, {headers}));
    }
    return fetch(request);
  };
  document.addEventListener('DOMContentLoaded', () => {
    if (window !== window.top) return;
    const link = document.createElement('a');
    link.textContent = 'Account · sign out';
    link.href = new URL('auth/sessions', location.href.split('#')[0]).href;
    Object.assign(link.style, {position:'fixed',right:'12px',bottom:'12px',zIndex:'9999',
      padding:'7px 12px',borderRadius:'6px',background:'#202938',color:'#fff',font:'14px system-ui'});
    const update = () => { link.style.display = location.hash.includes('mode=read_book') ? 'none' : 'inline-block'; };
    window.addEventListener('hashchange', update);
    update();
    document.body.appendChild(link);
  });
})();
