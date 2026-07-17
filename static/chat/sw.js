// Ph3b3 — minimal service worker (scope /chat/).
// Purpose: provide a registered fetch handler so the portal is installable
// as an Android WebAPK (its own home-screen app) once served over HTTPS.
// Deliberately a network passthrough: the app is Basic-auth gated and can
// talk to selectable backends, so we do NOT cache authenticated responses
// here. No offline behavior is promised — this exists for installability.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => { /* passthrough — let the network handle it */ });
