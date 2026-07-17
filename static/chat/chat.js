// ── Main-portal bootstrap ───────────────────────────────────────────────────
// Consumes the shared core (api.js, chat.js, mic.js, gallery.js). Kept separate
// from the light bootstrap so each portal owns its identity (title) and boot.
async function initApp() {
    try {
        const res = await fetch(api('/health'), { headers: { 'Authorization': authHeader } });
        if (res.status === 401) { _clearAuth(); _showLogin('Access denied.'); return; }
        const d = await res.json();
        document.title = `Ph3b3 · ${currentServer().label} — Boot #${d.boot}`;
        addSys(`Connected · Boot #${d.boot} · ${d.model}`);
        initImageMode();
        addSys('Type  /img <prompt>  to generate an image.');
    } catch {
        addSys('Server offline — launch Ph3b3 first');
    }
    if (!MIC_OK) {
        addSys('Microphone requires HTTPS or a browser exception for this origin.');
        addSys('Firefox: open about:config → set  media.devices.insecure.enabled = true  → reload');
        addSys('Chrome:  open chrome://flags/#unsafely-treat-insecure-origin-as-secure → add this page\'s URL → relaunch');
    }
    inputEl.focus();
}

if (authHeader) initApp();

// ── PWA service worker (installability; no-op on insecure/HTTP contexts) ─────
// navigator.serviceWorker is undefined on non-secure origins, so this silently
// does nothing over plain HTTP and activates once on HTTPS.
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/chat/sw.js', { scope: '/chat/' }).catch(() => {});
}
