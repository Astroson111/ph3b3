    // ── Image-mode control ────────────────────────────────────────────────────
    const imgBtns = Array.from(document.querySelectorAll('.img-mode-btn'));

    function paintImgMode(mode, liveEnabled) {
        imgBtns.forEach(b => {
            const m = b.dataset.mode;
            b.classList.toggle('active', m === mode);
            const gated = (m === 'live' || m === 'auto') && !liveEnabled;
            b.disabled = gated;
            b.title    = gated ? 'not enabled on this build' : '';
        });
    }

    async function initImageMode() {
        try {
            const r = await fetch(api('/image/config'), { headers: { 'Authorization': authHeader } });
            if (!r.ok) return;
            const d = await r.json();
            paintImgMode(d.mode, d.live_enabled);
        } catch {}
    }

    imgBtns.forEach(b => b.addEventListener('click', async () => {
        if (b.disabled) return;
        try {
            const r = await fetch(api('/image/mode'), {
                method:  'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': authHeader },
                body:    JSON.stringify({ mode: b.dataset.mode }),
            });
            if (!r.ok) { addSys('Could not switch image mode'); return; }
            const d = await r.json();
            paintImgMode(d.mode, d.live_enabled);
            addSys(`Image mode → ${d.mode}`);
        } catch { addSys('Could not switch image mode'); }
    }));

    // ── Gallery view ──────────────────────────────────────────────────────────
    const galleryOverlay     = document.getElementById('gallery-overlay');
    const galleryGrid        = document.getElementById('gallery-grid');
    const galleryCount       = document.getElementById('gallery-count');
    const galleryLightbox    = document.getElementById('gallery-lightbox');
    const galleryLightboxImg = document.getElementById('gallery-lightbox-img');
    let galleryUrls = [];   // active blob URLs; revoked on close to free memory

    function closeGallery() {
        galleryOverlay.classList.remove('open');
        galleryLightbox.classList.remove('open');
        galleryUrls.forEach(u => URL.revokeObjectURL(u));
        galleryUrls = [];
        galleryGrid.innerHTML = '';
    }

    async function openGallery() {
        galleryOverlay.classList.add('open');
        galleryGrid.innerHTML = '<div id="gallery-msg">Loading gallery…</div>';
        galleryCount.textContent = '';
        let names;
        try {
            const r = await fetch(api('/image/gallery'), { headers: { 'Authorization': authHeader } });
            if (r.status === 401) { closeGallery(); _clearAuth(); _showLogin('Session expired — please reconnect.'); return; }
            if (!r.ok) { galleryGrid.innerHTML = '<div id="gallery-msg">Could not load gallery.</div>'; return; }
            names = (await r.json()).images || [];
        } catch { galleryGrid.innerHTML = '<div id="gallery-msg">Cannot reach server — is Ph3b3 running?</div>'; return; }

        if (!names.length) {
            galleryGrid.innerHTML = '<div id="gallery-msg">No images yet — generate one with /img &lt;prompt&gt;.</div>';
            return;
        }
        galleryGrid.innerHTML = '';
        galleryCount.textContent = `${names.length} image${names.length === 1 ? '' : 's'}`;
        // <img> can't send the auth header, so fetch each with auth → blob URL.
        for (const name of names) {
            try {
                const ir = await fetch(api('/image/file/' + encodeURIComponent(name)), { headers: { 'Authorization': authHeader } });
                if (!ir.ok) continue;
                const url = URL.createObjectURL(await ir.blob());
                galleryUrls.push(url);
                const cell = document.createElement('div');
                cell.className = 'gallery-cell';
                const im = document.createElement('img');
                im.src = url; im.alt = name; im.loading = 'lazy';
                im.addEventListener('click', () => { galleryLightboxImg.src = url; galleryLightbox.classList.add('open'); });
                const cap = document.createElement('div');
                cap.className = 'gcap'; cap.textContent = name;
                cell.appendChild(im); cell.appendChild(cap);
                galleryGrid.appendChild(cell);
            } catch {}
        }
    }

    document.getElementById('gallery-open').addEventListener('click', openGallery);
    document.getElementById('gallery-back').addEventListener('click', closeGallery);
    galleryLightbox.addEventListener('click', () => galleryLightbox.classList.remove('open'));
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        if (galleryLightbox.classList.contains('open'))      galleryLightbox.classList.remove('open');
        else if (galleryOverlay.classList.contains('open'))  closeGallery();
    });

    // ── Power / OFF button ────────────────────────────────────────────────────
    document.getElementById('power-off').addEventListener('click', async () => {
        if (!confirm('Shut down Ph3b3? The server will stop and must be restarted from the desktop shortcut.')) return;
        try {
            const r = await fetch(api('/power/off'), { method: 'POST', headers: { 'Authorization': authHeader } });
            if (r.status === 401) { _clearAuth(); _showLogin('Session expired — please reconnect.'); return; }
            addSys('Ph3b3 is shutting down…  (restart with the desktop shortcut)');
            setStatus('Idle');
            lockInput();
        } catch { addSys('Shutdown request failed.'); }
    });
