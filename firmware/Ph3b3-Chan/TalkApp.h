#pragma once
#include "AppBase.h"
#include <M5StackChan.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// Defined once in stackchan_rung4.ino
extern const char ISRG_ROOT_X1[];
extern bool g_overlayOpen;
extern bool g_crescentTapped;

// ── TalkApp — full Ph3b3 voice round-trip ────────────────────────────────────
//
// Flow:  tap screen → LISTENING (record) → release or 5s max → THINKING
//        → POST /transcribe → show heard text → POST /chat → stream audio
//        → SPEAKING (play) → back to IDLE
//
// WiFi must be connected (managed by main sketch). If offline, shows notice.
//
// Sequential: mic records THEN speaker plays — no BCK/WS simultaneity issue.
// Pattern: M5.Mic.begin() → record → M5.Mic.end() → M5.Speaker.begin() → play.

class TalkApp : public AppBase {
public:
    void init() override {
        M5StackChan.Display().fillScreen(TFT_BLACK);
        face.begin();  // full-screen face — no panel
        face.setStatusVisible(false);
        face.setCrescentTabVisible(true);
        _phase      = PH_IDLE;
        _pttBuf     = nullptr;
        _pttSamples = 0;
        _wasTouch   = false;
        _recAmp     = 0.0f;
        _bargeIn         = false;
        _heardText       = "";
        _replyText       = "";
        _sessionId       = "sc-" + String(millis(), HEX);  // stable for this conversation
        _lastTalkMs      = millis();
        _inConversation  = false;
        _convLastValidMs = 0;
        _exitAfterTurn   = false;
        _awaitFloor      = 0.0f;
        _awaitAccum      = 0.0f;
        _awaitSamples    = 0;
        _awaitOnsetMs    = 0;
        _awaitCalibEnd   = 0;
        // One-time TLS setup — cert pointer stays valid (ISRG_ROOT_X1 is in flash).
        // setTimeout() takes SECONDS on WiFiClientSecure — 90s covers LLM+TTS latency.
        // setReuse(true) tells HTTPClient to preserve the socket after http.end()
        // when the server responds with Connection: keep-alive.
        _tls.setCACert(ISRG_ROOT_X1);
        _tls.setTimeout(90);
        _http.setReuse(true);
    }

    void update() override {
        // ── Overlay gate — CrescentMenu handles all touches while panel is open ─
        if (g_overlayOpen) {
            int16_t _tx, _ty;
            _wasTouch = M5StackChan.Display().getTouch(&_tx, &_ty);
            return;
        }

        // Drain crescentTap here even if gated below — flag must not linger
        bool crescentTap = g_crescentTapped;
        g_crescentTapped = false;
        if (crescentTap) Serial.printf("[Talk] crescentTap seen — wifi=%d phase=%d\n",
                                       (int)(WiFi.status() == WL_CONNECTED), (int)_phase);

        // ── WiFi gate ──────────────────────────────────────────────────────────
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("[Talk] WiFi gate fired — crescentTap lost");
            face.setState(Ph3b3Face::CONNECTING);
            return;
        }

        // ── Touch detection ────────────────────────────────────────────────────
        int16_t tx = 0, ty = 0;
        bool touching = M5StackChan.Display().getTouch(&tx, &ty);
        bool tapped = crescentTap || ((touching && !_wasTouch) && !(tx < 60 && ty < 60));
        _wasTouch = touching;
        if (tapped) Serial.printf("[Talk] tapped — crescentTap=%d bodyTap=%d phase=%d\n",
                                  (int)crescentTap,
                                  (int)((touching && !crescentTap) && !(tx < 60 && ty < 60)),
                                  (int)_phase);
        // ── State machine ──────────────────────────────────────────────────────
        switch (_phase) {

        case PH_IDLE:
            face.setState(Ph3b3Face::IDLE);
            if (tapped) {
                _lastTalkMs      = millis();
                _inConversation  = true;
                _convLastValidMs = millis();
                _exitAfterTurn   = false;
                _startRecording();   // tap → immediate LISTENING, not ambient wait
            }
            break;

        case PH_AWAITING: {
            face.setState(Ph3b3Face::IDLE);
            if (millis() - _lastTalkMs > SESSION_IDLE_RESET_MS) {
                _sessionId  = "sc-" + String(millis(), HEX);
                _lastTalkMs = millis();
            }

            // Record a small monitoring chunk
            static int16_t monBuf[MONITOR_CHUNK];
            M5.Mic.record(monBuf, MONITOR_CHUNK, PTT_RATE);

            float rms = 0.0f;
            for (int i = 0; i < MONITOR_CHUNK; i++) {
                float s = monBuf[i] / 32768.0f;
                rms += s * s;
            }
            rms = sqrtf(rms / MONITOR_CHUNK);

            uint32_t now = millis();

            // Calibrate noise floor during initial window
            if (now < _awaitCalibEnd) {
                _awaitAccum += rms * rms;
                _awaitSamples++;
            } else if (_awaitFloor == 0.0f && _awaitSamples > 0) {
                _awaitFloor = max(VAD_FLOOR_MIN, sqrtf(_awaitAccum / _awaitSamples));
                Serial.printf("[await] floor=%.4f\n", _awaitFloor);
            }

            // Speech onset: loud enough for long enough → start recording
            if (_awaitFloor > 0.0f && rms > _awaitFloor * ONSET_THRESH) {
                if (_awaitOnsetMs == 0) _awaitOnsetMs = now;
                if (now - _awaitOnsetMs >= ONSET_MIN_MS) {
                    Serial.printf("[await] onset rms=%.4f floor=%.4f\n", rms, _awaitFloor);
                    _awaitOnsetMs    = 0;
                    _lastTalkMs      = now;
                    _inConversation  = true;
                    _convLastValidMs = now;
                    _exitAfterTurn   = false;
                    M5.Mic.end();
                    _startRecording();
                }
            } else {
                _awaitOnsetMs = 0;
            }

            // Tap override — immediate recording without waiting for onset
            if (tapped) {
                _awaitOnsetMs    = 0;
                _lastTalkMs      = now;
                _inConversation  = true;
                _convLastValidMs = now;
                _exitAfterTurn   = false;
                M5.Mic.end();
                _startRecording();
            }
            break;
        }

        case PH_RECORDING: {
            if (_pttBuf && _pttSamples < PTT_MAX) {
                int chunk = min(512, PTT_MAX - _pttSamples);
                M5.Mic.record(&_pttBuf[_pttSamples], chunk, PTT_RATE);

                // RMS of fresh chunk — ring visualizer + VAD input
                float rms = 0.0f;
                for (int i = 0; i < chunk; i++) {
                    float s = _pttBuf[_pttSamples + i] / 32768.0f;
                    rms += s * s;
                }
                rms = sqrtf(rms / chunk);
                _recAmp = _recAmp * 0.6f + rms * 0.4f;
                _pttSamples += chunk;

                uint32_t elapsed = millis() - _recStartMs;

                // Noise-floor calibration — first VAD_CALIBRATE_MS of real time
                if (elapsed < VAD_CALIBRATE_MS) {
                    _noiseAccum += rms * rms;
                    _noiseSamples++;
                } else if (_noiseFloor == 0.0f && _noiseSamples > 0) {
                    _noiseFloor = max(VAD_FLOOR_MIN,
                                     sqrtf(_noiseAccum / _noiseSamples) * VAD_THRESH_MULT);
                    Serial.printf("[vad] floor=%.4f (from %d samples)\n",
                                  _noiseFloor, _noiseSamples);
                }

                // VAD: track silence window after min duration
                if (_noiseFloor > 0.0f && elapsed >= VAD_MIN_MS) {
                    if (rms < _noiseFloor) {
                        if (_silenceStartMs == 0) _silenceStartMs = millis();
                    } else {
                        _silenceStartMs = 0;
                    }
                }
            }

            uint32_t elapsed  = millis() - _recStartMs;
            bool vad      = (_silenceStartMs > 0 && millis() - _silenceStartMs >= VAD_SILENCE_MS);
            bool full     = (elapsed >= VAD_MAX_MS || _pttSamples >= PTT_MAX);
            bool convIdle = (_inConversation && _convLastValidMs > 0 &&
                             millis() - _convLastValidMs > CONV_IDLE_MS);
            if (tapped && _inConversation && millis() - _recStartMs >= VAD_MIN_MS) {
                // Tap during active conversation loop → exit cleanly without dispatching.
                // VAD_MIN_MS guard (600ms) rejects capacitive ghost bounces from the
                // entry tap, which arrive within ~100ms and would otherwise immediately
                // exit the conversation before any speech is captured.
                M5.Mic.end();
                if (_pttBuf) { heap_caps_free(_pttBuf); _pttBuf = nullptr; }
                _pttSamples = 0;
                _endConversation();
            } else if (vad || full || convIdle || tapped) {
                _stopRecordingAndDispatch();
            }
            break;
        }

        case PH_DONE:
            // Auto-return to always-listening after conversation ends
            _heardText = "";
            _replyText = "";
            _startAwaiting();
            break;

        case PH_ERROR:
            face.setState(Ph3b3Face::ERROR);
            if (tapped) {
                _startAwaiting();
            }
            break;
        }
    }

    void draw() override {}

    void exit() override {
        if (_phase == PH_RECORDING || _phase == PH_AWAITING) {
            M5.Mic.end();
        }
        if (_pttBuf) { heap_caps_free(_pttBuf); _pttBuf = nullptr; }
        M5.Speaker.stop(0);
        M5.Speaker.end();
        face.begin();  // restore full-screen face
        _phase          = PH_IDLE;
        _sessionId      = "";  // will be regenerated on next init()
        _inConversation = false;
        _exitAfterTurn  = false;
        // Drop the persistent TLS socket when leaving TalkApp — it will be
        // stale by the time the user returns anyway.
        // Cap the TLS close-notify wait to 500ms: with setReuse(true) the socket
        // may be live (keep-alive), and the default 30s timeout would freeze the
        // display for up to 30 seconds while the TCP FIN/ACK completes.
        _http.end();
        _tls.setTimeout(500);
        _tls.stop();
    }

    const char* name() const override { return "Talk / Ph3b3"; }

private:
    // ── Constants ─────────────────────────────────────────────────────────────
    static const char* HOST;
    static const char* USER;
    static const char* PASS;
    static constexpr int PORT       = 443;
    static constexpr uint32_t SESSION_IDLE_RESET_MS = 60000;  // 60s idle resets conversation
    static constexpr uint32_t CONV_IDLE_MS          = 9000;   // 9s no valid speech → end loop
    static constexpr int      JUNK_MIN_LEN          = 2;      // transcript chars below this → noise
    static constexpr int      PTT_RATE      = 16000;
    static constexpr int      PTT_MAX       = PTT_RATE * 12;  // 12s hard cap = 384 KB PSRAM
    static constexpr int      CHUNK_SAMP    = 2048;           // ~93 ms @ 22050 Hz; larger = fewer gaps
    // VAD consts — millis()-based so timing is correct regardless of M5.Mic.record() blocking
    static constexpr uint32_t VAD_CALIBRATE_MS = 200;    // noise floor window
    static constexpr uint32_t VAD_MIN_MS       = 600;    // minimum recording before VAD fires
    static constexpr uint32_t VAD_SILENCE_MS   = 700;    // 700ms: was 1800 (laggy) -> 900 (still long) -> 500 (clipped natural pauses) -> 700, tuned for hesitant first-time speakers at the public demo.
    static constexpr uint32_t VAD_MAX_MS       = 12000;  // hard time cap (backup for PTT_MAX)
    static constexpr float    VAD_THRESH_MULT  = 5.0f;   // threshold = noise_floor × this (was 3.0 — ambient spikes kept resetting window)
    static constexpr float    VAD_FLOOR_MIN    = 0.003f; // abs. minimum threshold
    // Always-listening onset detection
    static constexpr int      MONITOR_CHUNK   = 256;     // samples per onset-check frame (~16 ms @ 16 kHz)
    static constexpr uint32_t ONSET_MIN_MS    = 150;     // ms of loud signal before auto-trigger
    static constexpr float    ONSET_THRESH    = 6.0f;    // × noise floor → speech onset

    // ── State ─────────────────────────────────────────────────────────────────
    enum Phase { PH_IDLE, PH_AWAITING, PH_RECORDING, PH_DONE, PH_ERROR };
    Phase    _phase      = PH_IDLE;
    int16_t* _pttBuf     = nullptr;
    int      _pttSamples = 0;
    uint32_t _recStartMs = 0;
    bool     _wasTouch   = false;
    float    _recAmp     = 0.0f;   // smoothed mic RMS during recording
    bool     _bargeIn    = false;  // set when tap interrupts playback → restart listening
    // VAD state
    float    _noiseFloor     = 0.0f;
    float    _noiseAccum     = 0.0f;
    int      _noiseSamples   = 0;
    uint32_t _silenceStartMs = 0;   // millis() when current silence window began; 0 = not in silence
    String   _heardText;
    String   _replyText;
    String   _sessionId;          // generated on init(), stable for a conversation, reset on exit/idle
    uint32_t _lastTalkMs      = 0;  // tracks idle time for session reset
    // Continuous conversation
    bool     _inConversation  = false;
    uint32_t _convLastValidMs = 0;   // millis() of last successful /chat; idle clock measures from here
    bool     _exitAfterTurn   = false; // set when exit word detected — end after current SPEAK
    // Always-listening state
    float    _awaitFloor    = 0.0f;
    float    _awaitAccum    = 0.0f;
    int      _awaitSamples  = 0;
    uint32_t _awaitOnsetMs  = 0;      // millis() when onset window opened; 0 = no onset
    uint32_t _awaitCalibEnd = 0;      // millis() when noise-floor calibration ends

    // Persistent TLS connection — cert set once; reused for /transcribe then /chat
    // within the same turn so only one TLS handshake is needed per turn.
    // HTTPClient::setReuse(true) keeps the socket alive across http.end() calls
    // as long as the server responds with Connection: keep-alive.
    WiFiClientSecure _tls;
    HTTPClient       _http;

    // ── Base64 helpers ────────────────────────────────────────────────────────
    static int _b64val(char c) {
        if (c >= 'A' && c <= 'Z') return c - 'A';
        if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52;
        if (c == '+') return 62;
        if (c == '/') return 63;
        return -1;
    }
    static const char* _b64enc() {
        return "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    }

    static void _buildWavHdr(uint8_t* h, int samples, int rate) {
        int d = samples * 2, f = 36 + d, br = rate * 2;
        memcpy(h, "RIFF", 4);
        h[4]=f; h[5]=f>>8; h[6]=f>>16; h[7]=f>>24;
        memcpy(h+8, "WAVE", 4); memcpy(h+12, "fmt ", 4);
        h[16]=16; h[17]=0; h[18]=0; h[19]=0;
        h[20]=1; h[21]=0; h[22]=1; h[23]=0;
        h[24]=rate; h[25]=rate>>8; h[26]=rate>>16; h[27]=rate>>24;
        h[28]=br; h[29]=br>>8; h[30]=br>>16; h[31]=br>>24;
        h[32]=2; h[33]=0; h[34]=16; h[35]=0;
        memcpy(h+36, "data", 4);
        h[40]=d; h[41]=d>>8; h[42]=d>>16; h[43]=d>>24;
    }

    // ── Always-listening ──────────────────────────────────────────────────────
    void _startAwaiting() {
        M5.Speaker.stop(0);
        M5.Speaker.end();
        delay(30);
        auto mcfg = M5.Mic.config();
        mcfg.sample_rate   = PTT_RATE;
        mcfg.magnification = 16;
        M5.Mic.config(mcfg);
        M5.Mic.begin();
        _awaitFloor    = 0.0f;
        _awaitAccum    = 0.0f;
        _awaitSamples  = 0;
        _awaitOnsetMs  = 0;
        _awaitCalibEnd = millis() + VAD_CALIBRATE_MS;
        // Snapshot live touch state so a still-held tap (e.g. exit tap from PH_RECORDING)
        // is not re-detected as a new entry tap on the very next frame.
        { int16_t _tx, _ty; _wasTouch = M5StackChan.Display().getTouch(&_tx, &_ty); }
        face.setState(Ph3b3Face::IDLE);
        face.clearBubble();
        _phase = PH_AWAITING;
        Serial.println("[await] armed — waiting for speech");
    }

    // ── Recording ─────────────────────────────────────────────────────────────
    void _startRecording() {
        // Allocate in PSRAM — 5s × 16kHz × 2 bytes = 160 KB
        _pttBuf = (int16_t*)heap_caps_malloc(PTT_MAX * sizeof(int16_t),
                                              MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!_pttBuf) {
            Serial.println("[talk] OOM: failed to alloc PTT buffer");
            face.setState(Ph3b3Face::ERROR);
            _phase = PH_ERROR;
            return;
        }
        _pttSamples     = 0;
        _recStartMs     = millis();
        _noiseFloor     = 0.0f;
        _noiseAccum     = 0.0f;
        _noiseSamples   = 0;
        _silenceStartMs = 0;

        // Ensure speaker I2S is fully released before mic claims the shared BCK/WS bus.
        // _doChatAndPlay() ends it after normal drain, but _startRecording() can also
        // be called from PH_IDLE (first turn) where the speaker may not have been used.
        M5.Speaker.stop(0);
        M5.Speaker.end();
        delay(30);  // let shared BCK/WS lines settle; prevents switching noise from polluting VAD calibration
        Serial.println("[i2s] mic.begin() — speaker torn down");

        auto mcfg = M5.Mic.config();
        mcfg.sample_rate   = PTT_RATE;
        mcfg.magnification = 16;
        M5.Mic.config(mcfg);
        M5.Mic.begin();

        face.setState(Ph3b3Face::LISTENING);
        face.clearBubble();
        _phase = PH_RECORDING;
    }

    void _stopRecordingAndDispatch() {
        M5.Mic.end();
        M5.Speaker.end();
        M5.Speaker.begin();
        M5.Speaker.setVolume(150);

        if (!_pttBuf || _pttSamples < PTT_RATE / 4) {
            if (_pttBuf) { heap_caps_free(_pttBuf); _pttBuf = nullptr; }
            if (!(millis() - _convLastValidMs < CONV_IDLE_MS)) _inConversation = false;
            _startAwaiting();  // re-arm voice detection
            return;
        }

        face.setState(Ph3b3Face::THINKING);
        face.update();

        // Clear _pttBuf BEFORE dispatch so the CC re-arm path inside _dispatch()
        // can safely call _startRecording() and assign a fresh buffer to _pttBuf.
        // If we free _pttBuf AFTER dispatch, we'd free the new turn-2 buffer instead.
        int16_t* audio      = _pttBuf;
        int      numSamples = _pttSamples;
        _pttBuf     = nullptr;
        _pttSamples = 0;

        _dispatch(audio, numSamples);
        heap_caps_free(audio);
    }

    // ── Main dispatch: encode → /transcribe → /chat → play ───────────────────
    void _dispatch(int16_t* audio, int numSamples) {
        Serial.printf("[D1] dispatch samples=%d sess=%s inConv=%d validAge=%lums\n",
                      numSamples, _sessionId.c_str(), (int)_inConversation,
                      _convLastValidMs ? millis() - _convLastValidMs : 0);

        // Idle check: only abort pre-dispatch if we're not in a conversation loop.
        // In the conversation loop, the re-arm calls _startRecording() immediately —
        // recording can run up to VAD_MAX_MS (12 s), which exceeds CONV_IDLE_MS.
        // Unlimited loop exit is via tap or farewell phrase only.
        if (!_inConversation && _convLastValidMs > 0 &&
            millis() - _convLastValidMs > CONV_IDLE_MS) {
            Serial.println("[D1] idle timeout at dispatch entry — ending conv");
            _endConversation();
            return;
        }

        // ── Step 1: build {"audio":"<base64 WAV>"} in PSRAM ──────────────────
        uint8_t wavHdr[44];
        _buildWavHdr(wavHdr, numSamples, PTT_RATE);
        int wavBytes = 44 + numSamples * 2;
        int b64Len   = ((wavBytes + 2) / 3) * 4;
        int jLen     = 10 + b64Len + 2;   // {"audio":"..."}
        char* jbuf   = (char*)heap_caps_malloc(jLen + 1,
                                               MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!jbuf) {
            Serial.printf("[D2] OOM jbuf jLen=%d\n", jLen);
            face.setState(Ph3b3Face::ERROR);
            _phase = PH_ERROR;
            return;
        }
        Serial.printf("[D2] jbuf OK %d bytes\n", jLen);

        // Inline base64 encoder — feeds WAV header then PCM
        memcpy(jbuf, "{\"audio\":\"", 10);
        int pos = 10;
        const char* enc = _b64enc();
        uint8_t tri[3]; int triPos = 0;

        auto flushTri = [&](int valid) {
            while (triPos < 3) tri[triPos++] = 0;
            jbuf[pos++] = enc[(tri[0]>>2)&0x3F];
            jbuf[pos++] = enc[((tri[0]&3)<<4)|((tri[1]>>4)&0xF)];
            jbuf[pos++] = valid < 2 ? '=' : enc[((tri[1]&0xF)<<2)|((tri[2]>>6)&0x3)];
            jbuf[pos++] = valid < 3 ? '=' : enc[tri[2]&0x3F];
            triPos = 0;
        };
        auto feedB = [&](uint8_t b) {
            tri[triPos++] = b;
            if (triPos == 3) flushTri(3);
        };

        for (int i = 0; i < 44; i++) feedB(wavHdr[i]);
        for (int i = 0; i < numSamples; i++) {
            feedB((uint8_t)(audio[i] & 0xFF));
            feedB((uint8_t)((audio[i] >> 8) & 0xFF));
        }
        if (triPos > 0) flushTri(triPos);
        jbuf[pos++] = '"'; jbuf[pos++] = '}'; jbuf[pos] = '\0';

        // ── Step 2: POST /transcribe ──────────────────────────────────────────
        // Use the persistent _tls/_http pair.  _tls may already be connected
        // (between-turn reuse); if not, HTTPClient reconnects automatically.

        _http.begin(_tls, HOST, PORT, "/transcribe", true);
        _http.setAuthorization(USER, PASS);
        _http.addHeader("Content-Type", "application/json");
        _http.addHeader("X-Ph3b3-Device", "stackchan");
        _http.setConnectTimeout(20000);
        _http.setTimeout(30000);

        int code = _http.POST((uint8_t*)jbuf, pos);
        heap_caps_free(jbuf); jbuf = nullptr;

        _heardText = "";
        if (code == HTTP_CODE_OK) {
            String body = _http.getString();
            JsonDocument doc;
            deserializeJson(doc, body);
            const char* t = doc["text"];
            if (t && *t) _heardText = String(t);
        }
        _http.end();  // keeps _tls alive if server returned Connection: keep-alive
        Serial.printf("[talk] transcribe=%d heard='%s'\n", code, _heardText.c_str());

        if (_heardText.length() == 0) {
            String err = (code > 0) ? "http " + String(code) :
                         (code == 0) ? "timeout" : "err " + String(code);
            if (_inConversation && millis() - _convLastValidMs < CONV_IDLE_MS) {
                Serial.printf("[talk] transcribe error in conv: %s — re-await\n", err.c_str());
                _startAwaiting(); return;
            }
            face.setState(Ph3b3Face::ERROR);
            _inConversation = false;
            _phase = PH_ERROR;
            return;
        }

        // Gaze intent — on-device keyword match, no server contract change
        if (_isGazeIntent(_heardText)) face.setGaze(0.0f, 0.0f);

        // Junk filter: short transcripts (noise artifacts) don't trigger /chat
        if (_isJunkTranscript(_heardText)) {
            Serial.printf("[talk] junk transcript '%s' — discarded\n", _heardText.c_str());
            if (_inConversation && millis() - _convLastValidMs >= CONV_IDLE_MS) {
                _inConversation = false;
            }
            _startAwaiting(); return;  // always re-await; idle clock unchanged
        }

        // Exit phrase detection — "goodbye" + Phoebe-name variant required; bare "goodbye" stays in loop
        _exitAfterTurn = _isFarewellToName(_heardText);

        face.setState(Ph3b3Face::THINKING);
        face.update();
        // Thinking tell — direct servo command: loop() is blocked here, can't use applyBodyLanguage.
        M5StackChan.Motion.moveX(160, 200);   // 16° off-axis contemplative look
        M5StackChan.Motion.moveY(390, 180);   // 39° — soft upward gaze

        // ── Step 3: POST /chat ────────────────────────────────────────────────
        Serial.printf("[D3] /chat heard='%s'\n", _heardText.c_str());
        _replyText = _doChatAndPlay(_heardText);
        bool ok = !_replyText.startsWith("ERR") && !_replyText.startsWith("HTTP") &&
                  !_replyText.startsWith("(no");
        Serial.printf("[D4] /chat reply='%.60s' ok=%d\n", _replyText.c_str(), (int)ok);

        // Barge-in: tap during SPEAK → reset idle and go straight to LISTEN
        if (_bargeIn) {
            _bargeIn = false;
            _exitAfterTurn = false;
            if (ok) _convLastValidMs = millis();
            face.releaseGaze();
            _startRecording();
            return;
        }

        // Update idle clock on a good turn (only if not exit-word — exit closes the session)
        if (ok && !_exitAfterTurn) _convLastValidMs = millis();

        // Exit word: give the sign-off, then drop to ready
        if (_exitAfterTurn) {
            _exitAfterTurn = false;
            _endConversation();
            return;
        }

        // Continuous loop: SPEAK done → re-arm directly to LISTENING (no ambient wait).
        // Exit conditions are tap (handled in PH_RECORDING) and farewell phrase only.
        if (ok && _inConversation) {
            _convLastValidMs = millis();
            face.releaseGaze();   // release any gaze lock so LISTENING settle fires in loop()
            Serial.println("[D5] CC re-arm → LISTEN");
            _startRecording();
            return;
        }

        Serial.printf("[D5] conv end ok=%d inConv=%d\n", (int)ok, (int)_inConversation);
        face.setState(ok ? Ph3b3Face::IDLE : Ph3b3Face::ERROR);
        _phase = ok ? PH_DONE : PH_ERROR;
    }

    // ── Conversation helpers ──────────────────────────────────────────────────
    bool _isJunkTranscript(const String& text) {
        String t = text; t.trim();
        return t.length() < (uint32_t)JUNK_MIN_LEN;
    }

    bool _isGazeIntent(const String& text) {
        String t = text; t.toLowerCase();
        return t.indexOf("look at me")  >= 0
            || t.indexOf("face me")     >= 0
            || t.indexOf("eyes up")     >= 0
            || t.indexOf("look here")   >= 0;
    }

    bool _isPhoebeName(const String& t) {
        // t must already be lowercased; covers common Whisper transcription variants
        return t.indexOf("phoebe")  >= 0
            || t.indexOf("pheobe")  >= 0
            || t.indexOf("phoeby")  >= 0
            || t.indexOf("feeby")   >= 0
            || t.indexOf("phoebee") >= 0
            || t.indexOf("phoebi")  >= 0
            || t.indexOf("feebs")   >= 0
            || t.indexOf("foebe")   >= 0
            || t.indexOf("pheeby")  >= 0
            || t.indexOf("feebe")   >= 0;
    }

    bool _isFarewellToName(const String& text) {
        String t = text; t.toLowerCase(); t.trim();
        bool hasGoodbye = t.indexOf("goodbye") >= 0 || t.indexOf("good bye") >= 0;
        return hasGoodbye && _isPhoebeName(t);
    }

    void _endConversation() {
        face.releaseGaze();
        _inConversation  = false;
        _exitAfterTurn   = false;
        _convLastValidMs = 0;
        _startAwaiting();
    }

    // ── /chat + streaming audio ───────────────────────────────────────────────
    String _doChatAndPlay(const String& message) {
        // Reuse the same _tls/_http that carried /transcribe — no second handshake.
        if (!_http.begin(_tls, HOST, PORT, "/chat", true))
            return String("ERR: begin failed");

        _http.setConnectTimeout(90000);
        _http.setTimeout(120000);
        _http.setAuthorization(USER, PASS);
        _http.addHeader("Content-Type", "application/json");
        _http.addHeader("X-Ph3b3-Device", "stackchan");

        JsonDocument body;
        body["message"]    = message;
        body["session_id"] = _sessionId;
        String payload;
        serializeJson(body, payload);

        face.update();
        int code = _http.POST(payload);
        Serial.printf("[D3b] /chat POST code=%d\n", code);
        if (code != HTTP_CODE_OK) { _http.end(); return "HTTP " + String(code); }

        face.update();

        // ── Phase A: first 6 KB captures the "response" text field ───────────
        // Poll available() rather than blocking readBytes(6144) — the response body
        // may be smaller than 6KB, causing readBytes to hang until socket timeout.
        static const int PEEK_MAX = 6144;
        static char peek[PEEK_MAX + 1];
        auto* raw = _http.getStreamPtr();
        raw->setTimeout(30000);
        int peekLen = 0;
        uint32_t peekDeadline = millis() + 60000;
        while (peekLen < PEEK_MAX && millis() < peekDeadline) {
            int avail = raw->available();
            if (avail > 0) {
                int n = min(avail, PEEK_MAX - peekLen);
                peekLen += raw->readBytes(peek + peekLen, n);
                peek[peekLen] = '\0';
                if (peekLen > 50 && strstr(peek, "\"audio\":\"")) break;
            } else if (!raw->connected()) {
                break;
            } else {
                face.update();
                delay(10);
            }
        }
        peek[peekLen] = '\0';

        JsonDocument filter; filter["response"] = true;
        JsonDocument jdoc;
        deserializeJson(jdoc, peek, peekLen, DeserializationOption::Filter(filter));
        const char* resp = jdoc["response"];
        String responseText = (resp && *resp) ? String(resp) : "";

        uint32_t speakSweepMs = 0;  // speaking emphasis timer; first sweep after 800ms
        if (responseText.length() > 0) {
            _applyMoodReaction(responseText);
            face.setState(Ph3b3Face::SPEAKING);
            face.setBubble(responseText);
            face.update();
            // Speaking start pose — direct command (loop() blocked by _doChatAndPlay).
            M5StackChan.Motion.moveX(0, 280);
            M5StackChan.Motion.moveY(450, 280);
            speakSweepMs = millis() + 800;
        }

        // ── Phase B: stream-decode "audio":"<base64>" field ──────────────────
        const char* audioTag  = "\"audio\":\"";
        char* foundTag = strstr(peek, audioTag);
        int audioStart = foundTag ? (int)(foundTag - peek) + (int)strlen(audioTag) : -1;

        if (audioStart >= 0) {
            // Double-buffered decode — same pattern as Iris
            static int16_t pcmBuf[2][CHUNK_SAMP];
            int   fillIdx       = 0;
            int   chunkPos      = 0;
            int   wavHdrSkipped = 0;
            uint8_t halfLo      = 0;
            bool  halfReady     = false;
            char  b4[4]; int b4pos = 0;
            bool  keepGoing     = true;

            auto flushChunk = [&]() {
                if (chunkPos == 0) return;
                // RMS → lip-sync level (face.update() happens in outer loop, not here)
                float rms = 0.0f;
                for (int i = 0; i < chunkPos; i++) {
                    float s = pcmBuf[fillIdx][i] / 32768.0f;
                    rms += s * s;
                }
                face.setSpeakingLevel(min(1.0f, sqrtf(rms / chunkPos) * 5.0f));
                // Queue next chunk as soon as there's room
                while (M5.Speaker.isPlaying(0) >= 2) delay(1);
                if (!keepGoing) return;
                M5.Speaker.playRaw(pcmBuf[fillIdx], chunkPos, 22050, false, 1, 0);
                fillIdx ^= 1;
                chunkPos = 0;
            };

            auto pushByte = [&](uint8_t b) {
                if (wavHdrSkipped++ < 44) return;
                if (!halfReady) { halfLo = b; halfReady = true; return; }
                // Race guard: pcmBuf[fillIdx] was queued two iterations ago and may
                // still be playing. Wait until it leaves the queue before overwriting it.
                if (chunkPos == 0) {
                    while (M5.Speaker.isPlaying(0) >= 2) delay(1);
                }
                pcmBuf[fillIdx][chunkPos++] = (int16_t)((b << 8) | halfLo);
                halfReady = false;
                if (chunkPos == CHUNK_SAMP) flushChunk();
            };

            auto feedCh = [&](char ch) {
                if (!keepGoing) return;
                if (ch == '"') { keepGoing = false; return; }
                int v = _b64val(ch);
                if (v < 0) return;
                b4[b4pos++] = ch;
                if (b4pos == 4) {
                    int v0=_b64val(b4[0]), v1=_b64val(b4[1]),
                        v2=_b64val(b4[2]), v3=_b64val(b4[3]);
                    if (v0 >= 0 && v1 >= 0) {
                        pushByte((uint8_t)((v0<<2)|(v1>>4)));
                        if (v2 >= 0 && b4[2] != '=') {
                            pushByte((uint8_t)((v1<<4)|(v2>>2)));
                            if (v3 >= 0 && b4[3] != '=') pushByte((uint8_t)((v2<<6)|v3));
                        }
                    }
                    b4pos = 0;
                }
            };

            // Decode from peek buffer first, then stream remaining bytes
            for (int i = audioStart; i < peekLen; i++) feedCh(peek[i]);

            if (keepGoing) {
                face.update();

                uint32_t deadline = millis() + 90000;
                while (keepGoing && millis() < deadline) {
                    // Drain all available TCP bytes before doing any UI work —
                    // single-byte reads with M5.update() between each byte was
                    // too slow (≈200 chars/s) to sustain 22050 Hz audio decode.
                    while (keepGoing && raw->available() > 0) {
                        feedCh((char)raw->read());
                    }
                    // Touch/face update only when TCP buffer is momentarily empty
                    M5.update();
                    face.update();
                    int16_t tx2, ty2;
                    bool _touched = M5StackChan.Display().getTouch(&tx2, &ty2);
                    if (_touched) {
                        M5.Speaker.stop(0);
                        M5.Speaker.end();  // fully release I2S before mic can start
                        face.setSpeakingLevel(0.0f);
                        _bargeIn   = true;
                        keepGoing  = false;
                        break;
                    }
                    // Speaking emphasis: gentle pan/tilt on phrase boundaries during playback.
                    if (speakSweepMs > 0 && millis() >= speakSweepMs) {
                        M5StackChan.Motion.moveX(random(-200, 201), 210);
                        M5StackChan.Motion.moveY(450 + random(-25, 26), 190);
                        speakSweepMs = millis() + 900 + random(800);
                    }
                    delay(1);
                }
            }

            flushChunk();
            _http.end();

            while (M5.Speaker.isPlaying(0)) {
                M5.update();
                int16_t tx2, ty2;
                if (M5StackChan.Display().getTouch(&tx2, &ty2)) {
                    M5.Speaker.stop(0);
                    M5.Speaker.end();
                    face.setSpeakingLevel(0.0f);
                    _bargeIn = true;
                    break;
                }
                face.update();
                delay(50);
            }

            // Release speaker I2S unconditionally after playback.
            // BCK/WS are shared with mic (GPIO 34/33); if speaker I2S stays
            // initialised, the next M5.Mic.begin() gets the bus in a broken
            // state and records zeros. Barge-in already calls end() above;
            // this covers the normal non-interrupted drain path.
            if (!_bargeIn) {
                Serial.println("[i2s] speaker.end() — normal drain complete");
                M5.Speaker.end();
                delay(15);  // let shared clock lines settle before mic takes the bus
            }
        } else {
            _http.end();
        }

        return responseText.length() > 0 ? responseText : String("(no response)");
    }

    // ── Mood reaction — expression beat before TTS plays ─────────────────────
    void _applyMoodReaction(const String& text) {
        String t = text; t.toLowerCase();
        Ph3b3Face::State mood = Ph3b3Face::SPEAKING;

        if (t.indexOf("obviously") >= 0 || t.indexOf("clearly") >= 0 ||
            t.indexOf("actually")  >= 0 || t.indexOf("sarcas")  >= 0 ||
            t.indexOf("really")    >= 0) {
            mood = Ph3b3Face::THINKING;   // sly squint before the quip

        } else if (t.indexOf("sorry")   >= 0 || t.indexOf("unfortunately") >= 0 ||
                   t.indexOf("can't")   >= 0 || t.indexOf("cannot")        >= 0 ||
                   t.indexOf("unable")  >= 0) {
            mood = Ph3b3Face::ERROR;      // blue "bad news" look

        } else if (t.indexOf("fascinating") >= 0 || t.indexOf("interesting") >= 0 ||
                   t.indexOf("love")        >= 0 || t.indexOf("brilliant")   >= 0 ||
                   t.indexOf("excellent")   >= 0) {
            mood = Ph3b3Face::LISTENING;  // wide-eyed excitement
        }

        if (mood != Ph3b3Face::SPEAKING) {
            face.setState(mood);
            for (int i = 0; i < 5; i++) { face.update(); delay(60); }
        }
    }

};

// Static member definitions
inline const char* TalkApp::HOST = "ph3b3.<tailnet>.ts.net";
inline const char* TalkApp::USER = SC_PH3B3_USER;
inline const char* TalkApp::PASS = SC_PH3B3_PASS;
