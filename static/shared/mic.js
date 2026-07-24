    // ── Mic canvas ────────────────────────────────────────────────────────────
    const CX = 60, CY = 60, CR = 54;

    function drawMic(fill, ring, emoji) {
        micCvx.clearRect(0, 0, 120, 120);
        micCvx.beginPath();
        micCvx.arc(CX, CY, CR + 4, 0, 2 * Math.PI);
        micCvx.strokeStyle = ring;
        micCvx.lineWidth = 3;
        micCvx.stroke();
        micCvx.beginPath();
        micCvx.arc(CX, CY, CR, 0, 2 * Math.PI);
        micCvx.fillStyle = fill;
        micCvx.fill();
        micCvx.font = '30px monospace';
        micCvx.textAlign = 'center';
        micCvx.textBaseline = 'middle';
        micCvx.fillStyle = emoji;
        micCvx.fillText('🎤', CX, CY);
    }

    // ── Mic availability ─────────────────────────────────────────────────────
    const MIC_OK = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

    // ── Mic state ─────────────────────────────────────────────────────────────
    let micMode       = 'hold';   // 'hold' | 'auto'
    let autoOn        = false;
    let holdRecording = false;
    let autoCapturing = false;

    // Web Audio objects (recreated each session)
    let micStream    = null;
    let micCtx       = null;
    let micSource    = null;
    let micProc      = null;
    let micAnalyser  = null;
    let micSR        = 44100;  // filled from micCtx.sampleRate

    // Sample buffers
    let holdChunks     = [];
    let capturedChunks = [];
    let preRollChunks  = [];
    const PRE_ROLL_MAX = 6;  // ~6 × 256ms ≈ 1.5 s ring buffer

    // VAD
    let vadState    = 'waiting'; // 'waiting' | 'capturing' | 'submitting'
    let vadThresh   = 0.018;
    let silenceN    = 0;
    let captureT    = 0;
    let autoItvl    = null;

    const VAD_SILENCE_MS  = 1400;
    const VAD_MIN_SECS    = 0.4;
    const VAD_TICK_MS     = 80;
    const VAD_SILENCE_TKS = Math.ceil(VAD_SILENCE_MS / VAD_TICK_MS);  // 18 ticks

    // ── Mode buttons ──────────────────────────────────────────────────────────
    function refreshButtons() {
        if (micMode === 'auto') {
            btnAuto.style.background = autoOn ? '#22c55e' : '#15803d';
            btnAuto.style.color      = autoOn ? 'black'   : 'white';
            btnHold.style.background = '#18182e';
            btnHold.style.color      = '#5b5280';
        } else {
            btnAuto.style.background = '#18182e';
            btnAuto.style.color      = '#5b5280';
            btnHold.style.background = '#7c3aed';
            btnHold.style.color      = 'white';
        }
    }

    // ── Pulse animation ───────────────────────────────────────────────────────
    let pulseN = 0;
    setInterval(() => {
        pulseN = (pulseN + 1) % 20;
        const hi = pulseN < 10;
        if (holdRecording) {
            drawMic(hi ? '#4c1d95' : '#1e1730', hi ? '#a855f7' : '#4a3880', hi ? 'white' : '#5b5280');
        } else if (autoCapturing) {
            drawMic(hi ? '#14532d' : '#071510', hi ? '#22c55e' : '#166534', hi ? '#86efac' : '#5b5280');
        } else if (autoOn) {
            drawMic('#071510', hi ? '#166534' : '#0d2b1a', '#5b5280');
        } else if (hi) {
            drawMic('#1e1730', '#4a3880', '#5b5280');
        }
    }, 130);

    // ── Mic teardown helper ───────────────────────────────────────────────────
    function teardownMic() {
        if (autoItvl)   { clearInterval(autoItvl); autoItvl = null; }
        if (micProc)    { micProc.disconnect();    micProc  = null; }
        if (micAnalyser){ micAnalyser.disconnect();micAnalyser = null; }
        if (micSource)  { micSource.disconnect();  micSource = null; }
        if (micStream)  { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
        if (micCtx)     { micCtx.close();          micCtx   = null; }
    }

    // ── HOLD mode ─────────────────────────────────────────────────────────────
    async function startHold() {
        if (!MIC_OK || holdRecording || busy) return;
        holdRecording = true;
        holdChunks = [];
        try {
            micStream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
            });
            micCtx   = new AudioContext();
            micSR    = micCtx.sampleRate;
            micSource = micCtx.createMediaStreamSource(micStream);
            micProc   = micCtx.createScriptProcessor(4096, 1, 1);
            micProc.onaudioprocess = e => {
                if (holdRecording)
                    holdChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
            };
            micSource.connect(micProc);
            micProc.connect(micCtx.destination);
        } catch (e) {
            addSys(`Mic error: ${e.message}`);
            holdRecording = false;
            teardownMic();
            return;
        }
        setStatus('Listening');
        micLabel.textContent = 'recording…';
    }

    async function stopHold() {
        if (!holdRecording) return;
        holdRecording = false;
        const chunks = holdChunks.splice(0);
        const sr = micSR;
        teardownMic();

        if (!chunks.length) {
            setStatus('Idle');
            micLabel.textContent = 'hold to speak';
            return;
        }
        micLabel.textContent = 'transcribing…';
        await transcribeAndChat(chunks, sr);
        setStatus('Idle');
        micLabel.textContent = 'hold to speak';
    }

    // ── AUTO mode ─────────────────────────────────────────────────────────────
    async function startAutoLoop() {
        if (!MIC_OK || autoOn) return;
        autoOn = true;
        vadState       = 'waiting';
        capturedChunks = [];
        preRollChunks  = [];
        silenceN       = 0;
        refreshButtons();
        micLabel.textContent = 'calibrating…';
        setStatus('Listening');

        try {
            micStream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
            });
            micCtx    = new AudioContext();
            micSR     = micCtx.sampleRate;
            micSource = micCtx.createMediaStreamSource(micStream);

            // Analyser for RMS-based VAD
            micAnalyser         = micCtx.createAnalyser();
            micAnalyser.fftSize = 1024;
            const vadBuf        = new Float32Array(micAnalyser.fftSize);

            // ScriptProcessor collects PCM into the right bucket
            micProc = micCtx.createScriptProcessor(4096, 1, 1);
            micProc.onaudioprocess = e => {
                const chunk = new Float32Array(e.inputBuffer.getChannelData(0));
                if (vadState === 'waiting') {
                    if (preRollChunks.length >= PRE_ROLL_MAX) preRollChunks.shift();
                    preRollChunks.push(chunk);
                } else if (vadState === 'capturing') {
                    capturedChunks.push(chunk);
                }
                // 'submitting': discard
            };

            micSource.connect(micAnalyser);
            micSource.connect(micProc);
            micProc.connect(micCtx.destination);

            // Calibrate noise floor over ~700 ms
            const noiseSamples = [];
            await new Promise(resolve => {
                const calId = setInterval(() => {
                    micAnalyser.getFloatTimeDomainData(vadBuf);
                    let sum = 0; for (const s of vadBuf) sum += s * s;
                    noiseSamples.push(Math.sqrt(sum / vadBuf.length));
                    if (noiseSamples.length >= 9) { clearInterval(calId); resolve(); }
                }, VAD_TICK_MS);
            });
            const noise = noiseSamples.reduce((a, b) => a + b, 0) / noiseSamples.length;
            vadThresh = Math.max(0.018, noise * 3.5);
            addSys(`Auto · noise ${noise.toFixed(4)} · threshold ${vadThresh.toFixed(4)}`);
            micLabel.textContent = 'listening…';

            // VAD tick loop
            autoItvl = setInterval(() => {
                if (!autoOn) { clearInterval(autoItvl); autoItvl = null; return; }
                if (busy || vadState === 'submitting') return;

                micAnalyser.getFloatTimeDomainData(vadBuf);
                let sum = 0; for (const s of vadBuf) sum += s * s;
                const rms = Math.sqrt(sum / vadBuf.length);

                if (vadState === 'waiting') {
                    if (rms >= vadThresh) {
                        capturedChunks = preRollChunks.splice(0);
                        silenceN   = 0;
                        captureT   = Date.now();
                        vadState   = 'capturing';
                        autoCapturing = true;
                    }
                } else if (vadState === 'capturing') {
                    if (rms < vadThresh) {
                        silenceN++;
                        if (silenceN >= VAD_SILENCE_TKS) {
                            // End of utterance
                            vadState      = 'submitting';
                            autoCapturing = false;
                            const chunks  = capturedChunks.splice(0);
                            preRollChunks = [];
                            silenceN      = 0;
                            const secs    = (Date.now() - captureT) / 1000;

                            if (secs < VAD_MIN_SECS) {
                                vadState = 'waiting';
                                return;
                            }

                            micLabel.textContent = 'transcribing…';
                            const sr = micSR;
                            transcribeAndChat(chunks, sr).then(() => {
                                if (autoOn) {
                                    vadState = 'waiting';
                                    setStatus('Listening');
                                    micLabel.textContent = 'listening…';
                                }
                            });
                        }
                    } else {
                        silenceN = 0;
                    }
                }
            }, VAD_TICK_MS);

        } catch (e) {
            addSys(`Mic error: ${e.message}`);
            stopAutoLoop();
        }
    }

    function stopAutoLoop() {
        autoOn        = false;
        autoCapturing = false;
        vadState      = 'waiting';
        teardownMic();
        refreshButtons();
        micLabel.textContent = 'tap to start';
        setStatus('Idle');
    }

    // ── Mode switching ────────────────────────────────────────────────────────
    function setMicMode(mode) {
        if (mode === micMode) {
            // Re-clicking same mode toggles auto loop
            if (mode === 'auto') { autoOn ? stopAutoLoop() : startAutoLoop(); }
            return;
        }
        if (micMode === 'auto' && autoOn) stopAutoLoop();
        micMode = mode;
        refreshButtons();
        micLabel.textContent = mode === 'hold' ? 'hold to speak' : 'tap to start';
    }

    btnAuto.addEventListener('click', () => setMicMode('auto'));
    btnHold.addEventListener('click', () => setMicMode('hold'));

    // ── Mic canvas events ─────────────────────────────────────────────────────
    micCanvas.addEventListener('mousedown', () => {
        if (micMode === 'hold') startHold();
        else autoOn ? stopAutoLoop() : startAutoLoop();
    });
    micCanvas.addEventListener('mouseup',    () => { if (micMode === 'hold') stopHold(); });
    micCanvas.addEventListener('mouseleave', () => { if (micMode === 'hold' && holdRecording) stopHold(); });

    // Ensure mouseup outside canvas still stops HOLD recording
    document.addEventListener('mouseup', () => { if (micMode === 'hold' && holdRecording) stopHold(); });

    micCanvas.addEventListener('touchstart', e => {
        e.preventDefault();
        if (micMode === 'hold') startHold();
        else autoOn ? stopAutoLoop() : startAutoLoop();
    }, { passive: false });
    micCanvas.addEventListener('touchend', e => {
        e.preventDefault();
        if (micMode === 'hold') stopHold();
    }, { passive: false });

    // ── Init ──────────────────────────────────────────────────────────────────
    refreshButtons();

    if (!MIC_OK) {
        // Draw mic disabled (red-tinted, locked cursor)
        drawMic('#1a0a0a', '#4a1010', '#5b5280');
        micCanvas.style.cursor = 'not-allowed';
        micLabel.textContent   = 'mic unavailable';
        btnAuto.disabled = true; btnAuto.style.opacity = '0.35'; btnAuto.style.cursor = 'not-allowed';
        btnHold.disabled = true; btnHold.style.opacity = '0.35'; btnHold.style.cursor = 'not-allowed';
    } else {
        drawMic('#1e1730', '#4a3880', '#5b5280');
    }
