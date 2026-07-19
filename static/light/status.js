// ── Status view: voice & language (ph3b3-light) ─────────────────────────────
// Thin client: all state lives on the SELECTED server (via api()). No local
// persistence, no registry logic — just render what the server reports and POST
// changes back. Reuses the shared api()/authHeader/playAudio()/addSys() globals.
(function () {
    const overlay      = document.getElementById('status-overlay');
    const voiceSel     = document.getElementById('voice-select');
    const langSel      = document.getElementById('lang-select');
    const previewBtn   = document.getElementById('voice-preview-btn');
    const voiceCurrent = document.getElementById('voice-current');
    const langNote     = document.getElementById('lang-note');

    function openStatus()  { overlay.classList.add('open'); loadVoices(); loadLanguages(); }
    function closeStatus() { overlay.classList.remove('open'); }

    async function apiGet(path) {
        const r = await fetch(api(path), { headers: { 'Authorization': authHeader } });
        if (r.status === 401) { _clearAuth(); _showLogin('Session expired — please reconnect.'); throw new Error('401'); }
        if (r.status === 404) throw new Error('404');
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
    }
    async function apiPost(path, body) {
        const r = await fetch(api(path), {
            method:  'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': authHeader },
            body:    JSON.stringify(body),
        });
        if (r.status === 401) { _clearAuth(); _showLogin('Session expired — please reconnect.'); throw new Error('401'); }
        return r;
    }

    async function loadVoices() {
        voiceSel.innerHTML = '<option>Loading…</option>';
        voiceCurrent.textContent = '';
        previewBtn.disabled = true;
        try {
            const d = await apiGet('/voice');
            voiceSel.innerHTML = '';
            let rendered = 0;
            for (const v of d.voices || []) {
                // Server owns approval. Honor it defensively: an unreviewed voice
                // (approved === false) never renders in light. Voices with no
                // approved field (e.g. local standalone) are shown as before.
                if (v.approved === false) continue;
                const o = document.createElement('option');
                o.value = v.id; o.textContent = v.label;
                if (v.id === d.current) o.selected = true;
                voiceSel.appendChild(o);
                rendered++;
            }
            const cur = (d.voices || []).find(v => v.id === d.current && v.approved !== false);
            voiceCurrent.textContent = cur ? `Current: ${cur.label}` : '';
            previewBtn.disabled = rendered === 0;
        } catch (e) {
            if (e.message === '404') {
                voiceSel.innerHTML = '<option>Not supported by this server</option>';
                voiceCurrent.textContent = 'This server does not expose voice controls.';
            } else if (e.message !== '401') {
                voiceSel.innerHTML = '<option>Unavailable</option>';
            }
        }
    }

    async function loadLanguages() {
        langSel.innerHTML = '<option>Loading…</option>';
        langNote.innerHTML = '';
        try {
            const d = await apiGet('/language');
            langSel.innerHTML = '';
            const mk = (label, arr) => {
                if (!arr.length) return;
                const og = document.createElement('optgroup'); og.label = label;
                for (const l of arr) {
                    const o = document.createElement('option');
                    o.value = l.code; o.textContent = l.label;
                    if (l.code === d.current) o.selected = true;
                    og.appendChild(o);
                }
                langSel.appendChild(og);
            };
            mk('Native voice (strong)',   (d.languages || []).filter(l => l.tier === 'strong'));
            mk('Translation (functional)', (d.languages || []).filter(l => l.tier === 'functional'));
            langNote.innerHTML =
                '<span class="tier-strong">Strong</span> = native voice installed · ' +
                '<span class="tier-functional">Functional</span> = translated, spoken with the current voice.';
        } catch (e) {
            if (e.message === '404') langSel.innerHTML = '<option>Not supported by this server</option>';
            else if (e.message !== '401') langSel.innerHTML = '<option>Unavailable</option>';
        }
    }

    voiceSel.addEventListener('change', async () => {
        const label = voiceSel.options[voiceSel.selectedIndex]?.text || voiceSel.value;
        try { await apiPost('/voice', { id: voiceSel.value }); await loadVoices(); await loadLanguages(); addSys(`Voice → ${label}`); }
        catch {}
    });
    langSel.addEventListener('change', async () => {
        const label = langSel.options[langSel.selectedIndex]?.text || langSel.value;
        try {
            const r = await apiPost('/language', { code: langSel.value });
            const d = await r.json().catch(() => ({}));
            await loadVoices(); await loadLanguages();
            addSys(`Language → ${label}` + (d.note ? ` — ${d.note}` : ''));
        } catch {}
    });
    previewBtn.addEventListener('click', async () => {
        const old = previewBtn.textContent;
        previewBtn.disabled = true; previewBtn.textContent = '…';
        try {
            const r = await apiPost('/voice/preview', { id: voiceSel.value });
            const d = await r.json().catch(() => ({}));
            if (d.audio) await playAudio(d.audio);
        } catch {}
        finally { previewBtn.textContent = old; previewBtn.disabled = false; }
    });

    document.getElementById('status-open').addEventListener('click', openStatus);
    document.getElementById('status-back').addEventListener('click', closeStatus);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay.classList.contains('open')) closeStatus();
    });
})();
