/* Service worker: l'app funziona anche senza rete.
   - guscio dell'app (pagina, icone): dalla cache, aggiornato in background (alla prossima apertura vedi la versione nuova);
   - dati (config.json, dati/dati.json): prima la rete, la cache solo se sei offline;
   - le richieste verso api.github.com (pulsante Aggiorna) non passano di qui. */
const VERSIONE = 'pendolo-@@VERSIONE@@';
const GUSCIO = ['./', 'index.html', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSIONE).then((c) => c.addAll(GUSCIO)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSIONE && k !== 'pendolo-dati').map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  const dati = /\/dati\//.test(url.pathname) || /\/config\.json$/.test(url.pathname);
  if (dati) {
    e.respondWith(fetch(req).then((r) => {
      if (r.ok) { const copia = r.clone(); caches.open('pendolo-dati').then((c) => c.put(url.pathname, copia)); }
      return r;
    }).catch(() => caches.open('pendolo-dati').then((c) => c.match(url.pathname)).then((r) => r || Response.error())));
    return;
  }
  e.respondWith(caches.open(VERSIONE).then((c) => c.match(req, { ignoreSearch: true }).then((hit) => {
    const rete = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
    return hit || rete;
  })));
});
