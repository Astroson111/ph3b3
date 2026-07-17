    // ── DOM refs ─────────────────────────────────────────────────────────────
    const chatEl    = document.getElementById('chat');
    const inputEl   = document.getElementById('msg-input');
    const sendBtn   = document.getElementById('send-btn');
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
                src.onended = resolve;
                src.start();
            });
        } catch (e) {
            console.warn('Audio playback failed:', e);
        }
    }

    // ── Core chat fetch (caller manages busy + lock) ──────────────────────────
    async function doSend(text) {
        setStatus('Thinking');
        const thinking = addThinking();
        try {
            const res = await fetch(api('/chat'), {
                method:  'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': authHeader },
                body:    JSON.stringify({ message: text, session_id: 'web' }),
            });
            thinking.remove();
            if (res.status === 401) { _clearAuth(); _showLogin('Session expired — please reconnect.'); return; }
            if (!res.ok) {
                addSys(`Server error: ${res.status}`);
            } else {
                const data = await res.json();
                addMsg('Ph3b3', data.response || '(no response)');
                if (data.audio) {
                    setStatus('Speaking');
                    await playAudio(data.audio);
                }
            }
        } catch {
            thinking.remove();
            addSys('Cannot reach server — is Ph3b3 running?');
        }
        setStatus('Idle');
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
        busy = true;
        lockInput();
        const m = raw.match(/^\/(?:img|image)\s+([\s\S]+)/i);
        if (m) {
            await sendImage(m[1].trim());
        } else {
            addMsg('You', raw);
            await doSend(raw);
        }
        busy = false;
        unlockInput();
    }

    sendBtn.addEventListener('click', send);
    inputEl.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });

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
        busy = true;
        lockInput();
        try {
            await doSend(text);
        } finally {
            busy = false;
            unlockInput();
        }
        return true;
    }
