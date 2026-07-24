    // ── DOM refs ─────────────────────────────────────────────────────────────
    const chatEl    = document.getElementById('chat');
    const inputEl   = document.getElementById('msg-input');
    const sendBtn   = document.getElementById('send-btn');
    const stopBtn   = document.getElementById('stop-btn');   // composer interrupt (both portals; may be null)
    const dotEl     = document.getElementById('status-dot');
    const statusEl  = document.getElementById('status-text');
    const btnAuto   = document.getElementById('btn-auto');
    const btnHold   = document.getElementById('btn-hold');
    const micCanvas = document.getElementById('mic-canvas');
    const micLabel  = document.getElementById('mic-label');
    const micCvx    = micCanvas.getContext('2d');

    // ── Status ───────────────────────────────────────────────────────────────
    const STATUS_COLORS = {
        Idle:      '#3d3660',
        Thinking:  '#f59e0b',
        Speaking:  '#38bdf8',
        Listening: '#22c55e',
    };

    function setStatus(s) {
        const c = STATUS_COLORS[s] || '#5b5280';
        dotEl.style.color    = c;
        statusEl.style.color = c;
        statusEl.textContent = s;
    }

    // ── Chat helpers ──────────────────────────────────────────────────────────
    let busy = false;

    // ── Interrupt state (explicit stop — STOP button + Esc) ─────────────────────
    // turnSeq is the client's per-turn token: bumping it supersedes the in-flight turn so
    // its late unwinding (aborted fetch, stopped audio) can't clobber the next turn's state.
    let turnSeq       = 0;
    let currentSource = null;   // active TTS BufferSourceNode — kept so it can be stopped
    let currentAbort  = null;   // AbortController for the in-flight /chat fetch

    function showStop() { if (stopBtn) stopBtn.style.display = ''; }
    function hideStop() { if (stopBtn) stopBtn.style.display = 'none'; }

    // Cut Phoebe off mid-answer and free the composer for the next turn immediately.
    // Halts audio, aborts the in-flight request, and tells the server to cancel generation
    // (freeing the GPU). Shared by the STOP button and Esc.
    function stopSpeaking() {
        if (!busy) return;                       // nothing active to interrupt
        turnSeq++;                               // supersede → the running turn's tail no-ops
        if (currentSource) { try { currentSource.stop(); } catch {} currentSource = null; }
        if (currentAbort)  { try { currentAbort.abort(); } catch {} currentAbort = null; }
        // server-side truth for both portals: cancel the turn + free the GPU
        fetch(api('/interrupt/web'), { method: 'POST', headers: { 'Authorization': authHeader } }).catch(() => {});
        busy = false;
        unlockInput();
        hideStop();
        setStatus('Idle');
    }

    function ts() {
        return new Date().toLocaleTimeString('en-GB', {
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
    }

    function addSys(text) {
        const el = document.createElement('div');
        el.className = 'msg-sys';
        el.textContent = `  ·  ${text}`;
        chatEl.appendChild(el);
        chatEl.scrollTop = chatEl.scrollHeight;
    }

    function addMsg(who, text) {
        const isUser = who === 'You';
        const header = document.createElement('div');
        header.style.marginTop = '10px';
        header.innerHTML =
            `<span class="msg-ts">${ts()}  </span>` +
            `<span class="msg-name-${isUser ? 'user' : 'bot'}">${who}</span>`;
        chatEl.appendChild(header);
        const body = document.createElement('div');
        body.className = `msg-text-${isUser ? 'user' : 'bot'}`;
        body.textContent = `  ${text}`;
        chatEl.appendChild(body);
        chatEl.scrollTop = chatEl.scrollHeight;
    }

    function addThinking() {
        const el = document.createElement('div');
        el.className = 'thinking';
        el.textContent = '  Ph3b3 is thinking…';
        chatEl.appendChild(el);
        chatEl.scrollTop = chatEl.scrollHeight;
        return el;
    }

    function lockInput() {
        sendBtn.disabled = true;
        inputEl.disabled = true;
    }

    function unlockInput() {
        sendBtn.disabled = false;
        inputEl.disabled = false;
        inputEl.focus();
    }

    // ── TTS audio playback ────────────────────────────────────────────────────
    let playCtx = null;

    function getPlayCtx() {
        if (!playCtx || playCtx.state === 'closed')
            playCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (playCtx.state === 'suspended') playCtx.resume();
        return playCtx;
    }

    async function playAudio(b64) {
        try {
            const binary = atob(b64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
            const ctx = getPlayCtx();
            const buffer = await ctx.decodeAudioData(bytes.buffer);
            return new Promise(resolve => {
                const src = ctx.createBufferSource();
                src.buffer = buffer;
                src.connect(ctx.destination);
                currentSource = src;                 // exposed so stopSpeaking() can halt it
                src.onended = () => { if (currentSource === src) currentSource = null; resolve(); };
                src.start();
            });
        } catch (e) {
            console.warn('Audio playback failed:', e);
        }
    }

    // ── Core chat fetch (caller manages busy + lock) ──────────────────────────
    // Kadmos reading state — the reader strip lives on /chat/ only; on /light/ these
    // elements are absent, so this returns defaults (no reading mode, auto routing).
    function _kadmosReading() {
        const t = document.getElementById('read-mode-toggle');
        const d = document.getElementById('doc-type');
        const i = document.getElementById('read-instr');
        return { reading_mode: !!(t && t.checked),
                 reading_instruction: (i && i.value.trim()) || '',
                 doc_mode: (d && d.value) || 'auto' };
    }

    async function doSend(text, myTurn) {
        setStatus('Thinking');
        const thinking = addThinking();
        const myAbort = new AbortController();
        currentAbort = myAbort;
        try {
            const res = await fetch(api('/chat'), {
                method:  'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': authHeader },
                body:    JSON.stringify(Object.assign({ message: text, session_id: 'web' }, _kadmosReading())),
                signal:  myAbort.signal,
            });
            thinking.remove();
            if (myTurn !== turnSeq) return;      // interrupted/superseded while awaiting headers
            if (res.status === 401) { _clearAuth(); _showLogin('Session expired — please reconnect.'); return; }
            if (!res.ok) { addSys(`Server error: ${res.status}`); return; }
            const data = await res.json();
            if (myTurn !== turnSeq || data.interrupted) return;   // stopped → no render, no audio
            addMsg('Ph3b3', data.response || '(no response)');
            if (data.audio) {
                setStatus('Speaking');
                await playAudio(data.audio);
            }
        } catch (e) {
            thinking.remove();
            if (!(e && e.name === 'AbortError')) addSys('Cannot reach server — is Ph3b3 running?');  // AbortError = deliberate stop
        } finally {
            if (currentAbort === myAbort) currentAbort = null;
        }
    }

    // ── Image request + inline render ─────────────────────────────────────────
    function addImage(objUrl, caption) {
        const header = document.createElement('div');
        header.style.marginTop = '10px';
        header.innerHTML =
            `<span class="msg-ts">${ts()}  </span>` +
            `<span class="msg-name-bot">Ph3b3</span>`;
        chatEl.appendChild(header);
        const img = document.createElement('img');
        img.className = 'chat-img';
        img.src = objUrl;
        img.alt = caption || 'generated image';
        chatEl.appendChild(img);
        if (caption) {
            const cap = document.createElement('div');
            cap.className = 'img-cap';
            cap.textContent = `  ${caption}`;
            chatEl.appendChild(cap);
        }
        chatEl.scrollTop = chatEl.scrollHeight;
    }

    async function sendImage(prompt) {
        addMsg('You', `🖼  ${prompt}`);
        setStatus('Thinking');
        const thinking = addThinking();
        try {
            const res = await fetch(api('/image'), {
                method:  'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': authHeader },
                body:    JSON.stringify({ prompt }),
            });
            thinking.remove();
            if (res.status === 401) { _clearAuth(); _showLogin('Session expired — please reconnect.'); return; }
            if (!res.ok) { addSys(`Image error: ${res.status}`); return; }
            const data = await res.json();
            if (!data.ok) {                        // floor block / gate refusal / empty gallery → clean line
                addSys(data.reason || data.error || 'Image request could not be completed.');
                return;
            }
            // <img> can't send the auth header, so fetch the bytes with auth → blob URL.
            const imgRes = await fetch(api(data.image_url), { headers: { 'Authorization': authHeader } });
            if (!imgRes.ok) { addSys('Could not load image.'); return; }
            const objUrl = URL.createObjectURL(await imgRes.blob());
            let cap = data.source === 'live'
                ? `live · ${data.gen_seconds != null ? data.gen_seconds + 's' : 'ok'}`
                : 'gallery';
            if (data.fell_back) cap += ' (live unavailable — fallback)';
            addImage(objUrl, cap);
        } catch {
            thinking.remove();
            addSys('Cannot reach server — is Ph3b3 running?');
        } finally {
            setStatus('Idle');
        }
    }

    // ── Text box send ─────────────────────────────────────────────────────────
    async function send() {
        const raw = inputEl.value.trim();
        if (!raw || busy) return;
        inputEl.value = '';
        const myTurn = ++turnSeq;
        busy = true;
        lockInput();
        showStop();
        const m = raw.match(/^\/(?:img|image)\s+([\s\S]+)/i);
        if (m) {
            await sendImage(m[1].trim());
        } else {
            addMsg('You', raw);
            await doSend(raw, myTurn);
        }
        // Only clean up if this turn wasn't superseded by an interrupt (which already did).
        if (myTurn === turnSeq) {
            busy = false;
            unlockInput();
            hideStop();
            setStatus('Idle');
        }
    }

    sendBtn.addEventListener('click', send);
    inputEl.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
    if (stopBtn) stopBtn.addEventListener('click', stopSpeaking);
    // Esc interrupts — but yields to closing an open overlay (gallery lightbox / status card).
    document.addEventListener('keydown', e => {
        if (e.key !== 'Escape' || !busy) return;
        if (document.querySelector('#gallery-lightbox.open, #gallery-overlay.open, #status-overlay.open')) return;
        e.preventDefault();
        stopSpeaking();
    });

    // ── Kadmos document upload (attach 📎) — ONE shared implementation, present on
    // BOTH portals (the attach button sits in each portal's #inputbar, same as the
    // web-access toggle's shared logic). Posts to /kadmos/upload with the SAME
    // session_id ('web') the chat uses, so "summarize this" finds the staged doc.
    // Local file only; the server validates by MAGIC BYTES (413 oversize / 400
    // non-readable). NOTHING is read until Phoebe's gate question is answered next
    // turn. The reader strip is /chat/-only; its refs are null on /light/. ────────
    const KADMOS_MAX_BYTES = 25 * 1024 * 1024;              // mirror server PDF_MAX_BYTES — cap surfaced pre-upload
    const KADMOS_ACCEPT    = /\.(pdf|docx|txt|md|jpe?g|png)$/i;
    const docBtn      = document.getElementById('doc-attach-btn');
    const docInput    = document.getElementById('doc-file-input');
    const readerStrip = document.getElementById('reader-strip');   // /chat/ only (may be null)
    const docTypeSel  = document.getElementById('doc-type');

    async function uploadDoc(file) {
        if (!file || busy) return;
        if (!KADMOS_ACCEPT.test(file.name)) {
            addSys('I can only read PDF, Word (.docx), text (.txt/.md), or a photo (.jpg/.png).');
            return;
        }
        if (file.size > KADMOS_MAX_BYTES) {
            addSys('That file is too large for me to read (max 25 MB).');
            return;
        }
        if (docBtn) docBtn.disabled = true;
        addSys('uploading ' + file.name + '…');
        try {
            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch(api('/kadmos/upload?session_id=web'), {
                method: 'POST', headers: { 'Authorization': authHeader }, body: fd });
            if (res.status === 401) { _clearAuth(); _showLogin('Session expired — please reconnect.'); return; }
            if (!res.ok) {
                let detail = '';
                try { detail = (await res.json()).detail || ''; } catch (_) {}
                const msg = res.status === 413 ? 'That file is too large for me to read.'
                          : res.status === 400 ? (detail || "That file isn't something I can read.")
                          : ('Upload failed (' + res.status + ').');
                addMsg('Ph3b3', '📄 ' + msg);
                return;
            }
            const data = await res.json();
            // Confirmation gate: Phoebe asks before reading. Show her question; the
            // user's next chat reply (yes / no / look) is the go/no-go.
            addMsg('Ph3b3', '📄 ' + (data.gate_prompt || ('Loaded ' + data.filename + '. Want me to read it?')));
            if (readerStrip) {
                if (docTypeSel && data.label) docTypeSel.options[0].text = 'Auto (' + data.label + ')';
                if (docTypeSel) docTypeSel.value = 'auto';   // override is per-document
                readerStrip.hidden = false;
            }
        } catch (e) {
            addSys('Upload error: ' + e.message);
        } finally {
            if (docBtn) docBtn.disabled = false;
            if (docInput) docInput.value = '';               // allow re-selecting the same file
        }
    }
    if (docBtn && docInput) {
        docBtn.addEventListener('click', () => { if (!busy) docInput.click(); });
        docInput.addEventListener('change', () => uploadDoc(docInput.files[0]));
    }
    // Reading-mode toggle persists across turns (chat portal only).
    const readModeToggle = document.getElementById('read-mode-toggle');
    if (readModeToggle) {
        readModeToggle.checked = localStorage.getItem('ph3b3_reading_mode') === '1';
        readModeToggle.addEventListener('change', () =>
            localStorage.setItem('ph3b3_reading_mode', readModeToggle.checked ? '1' : '0'));
    }

    // ── WAV encoding (Float32 PCM → 16-bit WAV) ───────────────────────────────
    function encodeWAV(chunks, sampleRate) {
        let total = chunks.reduce((n, c) => n + c.length, 0);
        const flat = new Float32Array(total);
        let off = 0;
        for (const c of chunks) { flat.set(c, off); off += c.length; }

        const pcm = new Int16Array(flat.length);
        for (let i = 0; i < flat.length; i++)
            pcm[i] = Math.max(-32768, Math.min(32767, flat[i] * 32768));

        const buf = new ArrayBuffer(44 + pcm.byteLength);
        const v   = new DataView(buf);
        const ws  = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
        ws(0, 'RIFF');  v.setUint32(4, 36 + pcm.byteLength, true);
        ws(8, 'WAVE');  ws(12, 'fmt ');
        v.setUint32(16, 16, true);        // fmt chunk size
        v.setUint16(20,  1, true);        // PCM
        v.setUint16(22,  1, true);        // mono
        v.setUint32(24, sampleRate, true);
        v.setUint32(28, sampleRate * 2, true);  // byte rate
        v.setUint16(32,  2, true);        // block align
        v.setUint16(34, 16, true);        // bits per sample
        ws(36, 'data'); v.setUint32(40, pcm.byteLength, true);
        new Uint8Array(buf, 44).set(new Uint8Array(pcm.buffer));
        return buf;
    }

    function chunksToB64(chunks, sr) {
        const wav = encodeWAV(chunks, sr);
        const b = new Uint8Array(wav);
        let s = '';
        for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
        return btoa(s);
    }

    // ── Transcribe → chat ─────────────────────────────────────────────────────
    async function transcribeAndChat(chunks, sr) {
        const b64 = chunksToB64(chunks, sr);
        let text = '';
        try {
            const tr = await fetch(api('/transcribe'), {
                method:  'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': authHeader },
                body:    JSON.stringify({ audio: b64 }),
            });
            const td = await tr.json();
            text = (td.text || '').trim();
        } catch (e) {
            addSys(`Transcription error: ${e.message}`);
            return false;
        }
        if (!text) { addSys('(no speech detected)'); return false; }

        addMsg('You', text);
        const myTurn = ++turnSeq;
        busy = true;
        lockInput();
        showStop();
        try {
            await doSend(text, myTurn);
        } finally {
            if (myTurn === turnSeq) {      // skip if an interrupt superseded this turn
                busy = false;
                unlockInput();
                hideStop();
                setStatus('Idle');
            }
        }
        return true;
    }
