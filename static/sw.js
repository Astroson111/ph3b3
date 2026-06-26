const CACHE = 'ph3b3-v2';
const STATIC = ['/static/icon-192.png', '/static/icon-512.png', '/static/panel.webmanifest'];

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE)
            .then(c => Promise.allSettled(STATIC.map(u => c.add(u))))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', e => {
    if (e.request.method !== 'GET') return;
    const path = new URL(e.request.url).pathname;
    // Network-first for API + panel (auth-gated, must stay fresh)
    if (!path.startsWith('/static/')) {
        e.respondWith(fetch(e.request));
        return;
    }
    // Cache-first for static assets
    e.respondWith(
        caches.match(e.request).then(cached =>
            cached || fetch(e.request).then(resp => {
                const clone = resp.clone();
                caches.open(CACHE).then(c => c.put(e.request, clone));
                return resp;
            })
        )
    );
});
