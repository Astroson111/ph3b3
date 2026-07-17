    // ── Servers (selectable Ph3b3 backends: Local / Iris / Dio / Nyx) ──────────
    // Each entry is a FULL Ph3b3 instance. This page is a thin client that talks
    // to whichever server is selected in the top-bar dropdown. base:'' means
    // same-origin (the server that served this page). Fill in Iris/Dio/Nyx with
    // their real hosts via the ⚙ button — the list is saved in this browser.
    // NOTE: for a remote server to answer this page, that server's .env must add
    // this page's origin to PH3B3_CORS_ORIGINS (else the browser blocks the call).
    const SERVERS_KEY = 'ph3b3_servers';
    const ACTIVE_KEY  = 'ph3b3_active_server';
    const DEFAULT_SERVERS = [
        { id: 'local',  label: 'Local (this machine)', base: '',                          user: 'astroson' },
        { id: 'ph3b3',  label: 'Ph3b3 (main)',         base: 'http://100.82.221.100:7331', user: 'astroson' },
        { id: 'helios', label: 'Helios',               base: 'http://100.68.222.78:7331',  user: 'astroson' },
    ];
    function loadServers() {
        try {
            const raw = localStorage.getItem(SERVERS_KEY);
            if (raw) { const a = JSON.parse(raw); if (Array.isArray(a) && a.length) return a; }
        } catch {}
        return DEFAULT_SERVERS.slice();
    }
    function saveServers(list) { localStorage.setItem(SERVERS_KEY, JSON.stringify(list)); }
    let SERVERS = loadServers();
    let currentServerId = localStorage.getItem(ACTIVE_KEY) || SERVERS[0].id;
    function currentServer() { return SERVERS.find(s => s.id === currentServerId) || SERVERS[0]; }
    // Build a full API URL for the active server. Absolute URLs pass through
    // unchanged (e.g. image_url that a remote server returns as its own origin).
    function api(path) {
        if (/^https?:\/\//i.test(path)) return path;
        return (currentServer().base || '') + path;
    }

    // ── Auth (per-server Basic auth, mobile-safe) ─────────────────────────────
    let authHeader = '';
    function _credKey(id) { return 'ph3b3_creds_' + id; }
    function _loadStoredAuth() {
        const b64 = localStorage.getItem(_credKey(currentServerId));
        authHeader = b64 ? 'Basic ' + b64 : '';
    }
    function _storeAuth(password) {
        const b64 = btoa(currentServer().user + ':' + password);
        localStorage.setItem(_credKey(currentServerId), b64);
        authHeader = 'Basic ' + b64;
    }
    function _clearAuth() {
        localStorage.removeItem(_credKey(currentServerId));
        authHeader = '';
    }
    function _showLogin(msg) {
        document.getElementById('login-sub').textContent = 'Connect to ' + currentServer().label;
        document.getElementById('login-err').textContent = msg || '';
        document.getElementById('login-pass').value = '';
        document.getElementById('login-overlay').classList.add('visible');
        setTimeout(() => document.getElementById('login-pass').focus(), 50);
    }
    function _hideLogin() {
        document.getElementById('login-overlay').classList.remove('visible');
    }
    async function _tryLogin(password) {
        if (!password) return;
        _storeAuth(password);
        try {
            const r = await fetch(api('/health'), { headers: { 'Authorization': authHeader } });
            if (r.ok) { _hideLogin(); initApp(); return; }
        } catch {}
        _clearAuth();
        document.getElementById('login-err').textContent =
            'Wrong password (or server unreachable) — try again.';
        document.getElementById('login-pass').value = '';
        document.getElementById('login-pass').focus();
    }
    document.getElementById('login-pass').addEventListener('keydown', e => {
        if (e.key === 'Enter') _tryLogin(e.target.value);
    });
    document.getElementById('login-btn').addEventListener('click', () => {
        _tryLogin(document.getElementById('login-pass').value);
    });

    // ── Server switching / editor ─────────────────────────────────────────────
    function renderServerSelect() {
        const sel = document.getElementById('server-select');
        sel.innerHTML = '';
        for (const s of SERVERS) {
            const o = document.createElement('option');
            o.value = s.id; o.textContent = s.label;
            if (s.id === currentServerId) o.selected = true;
            sel.appendChild(o);
        }
    }
    function switchServer(id) {
        if (!SERVERS.find(s => s.id === id)) return;
        currentServerId = id;
        localStorage.setItem(ACTIVE_KEY, id);
        const s = currentServer();
        addSys('→ ' + s.label + (s.base ? '  (' + s.base + ')' : '  (local)'));
        _loadStoredAuth();
        if (!authHeader) { _showLogin(); return; }
        initApp();
    }
    function openServerEditor() {
        const text = SERVERS.map(s => [s.id, s.label, s.base, s.user].join(' | ')).join('\n');
        const next = prompt(
            'Edit Ph3b3 servers — one per line:\n' +
            '  id | label | base-url | user\n' +
            '(base-url empty = this machine; e.g.  iris | Iris | http://iris:7331 | astroson )',
            text);
        if (next == null) return;
        const list = [];
        for (const line of next.split('\n')) {
            const t = line.trim(); if (!t) continue;
            const [id, label, base, user] = t.split('|').map(x => (x || '').trim());
            if (!id) continue;
            list.push({ id, label: label || id, base: base || '', user: user || 'astroson' });
        }
        if (!list.length) return;
        SERVERS = list; saveServers(SERVERS);
        if (!SERVERS.find(s => s.id === currentServerId)) currentServerId = SERVERS[0].id;
        renderServerSelect();
        switchServer(currentServerId);
    }
    renderServerSelect();
    document.getElementById('server-select').addEventListener('change', e => switchServer(e.target.value));
    document.getElementById('server-edit').addEventListener('click', openServerEditor);

    _loadStoredAuth();
    if (!authHeader) _showLogin();
