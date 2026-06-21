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
    }

    void update() override {
        // ── Overlay gate — CrescentMenu handles all touches while panel is open ─
        if (g_overlayOpen) {
            int16_t _tx, _ty;
            _wasTouch = M5StackChan.Display().getTouch(&_tx, &_ty);
            return;
        }

        // ── WiFi gate ──────────────────────────────────────────────────────────
        if (WiFi.status() != WL_CONNECTED) {
            face.setState(Ph3b3Face::CONNECTING);
            return;
        }

        // ── Touch detection ────────────────────────────────────────────────────
        int16_t tx = 0, ty = 0;
        bool touching = M5StackChan.Display().getTouch(&tx, &ty);
        // Reserve top-left 60×60 px — crescent tab zone handled by CrescentMenu
        bool tapped = (touching && !_wasTouch) && !(tx < 60 && ty < 60);
        _wasTouch = touching;

        // ── State machine ──────────────────────────────────────────────────────
        switch (_phase) {

        case PH_IDLE:
            face.setState(Ph3b3Face::IDLE);
            if (millis() - _lastTalkMs > SESSION_IDLE_RESET_MS) {
                _sessionId  = "sc-" + String(millis(), HEX);
                _lastTalkMs = millis();
            }
            if (tapped) {
                _lastTalkMs      = millis();
                _inConversation  = true;   // conversation begins
                _convLastValidMs = millis();
                _exitAfterTurn   = false;
                _startRecording();
            }
            break;

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
            if (tapped || vad || full || convIdle) {
                _stopRecordingAndDispatch();
            }
            break;
        }

        case PH_DONE:
            face.setState(Ph3b3Face::IDLE);
            if (millis() - _lastTalkMs > SESSION_IDLE_RESET_MS) {
                _sessionId  = "sc-" + String(millis(), HEX);
                _lastTalkMs = millis();
            }
            if (tapped) {
                _lastTalkMs = millis();
                _phase      = PH_IDLE;
                _heardText  = "";
                _replyText  = "";
            }
            break;

        case PH_ERROR:
            face.setState(Ph3b3Face::ERROR);
            if (tapped) {
                _phase = PH_IDLE;
            }
            break;
        }
    }

    void draw() override {}

    void exit() override {
        if (_phase == PH_RECORDING) {
            M5.Mic.end();
        }
        if (_pttBuf) { heap_caps_free(_pttBuf); _pttBuf = nullptr; }
        M5.Speaker.stop(0);
        face.begin();  // restore full-screen face
        _phase          = PH_IDLE;
        _sessionId      = "";  // will be regenerated on next init()
        _inConversation = false;
        _exitAfterTurn  = false;
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
    static constexpr uint32_t VAD_SILENCE_MS   = 900;    // continuous silence → end turn (was 1800 — too long for noisy room)
    static constexpr uint32_t VAD_MAX_MS       = 12000;  // hard time cap (backup for PTT_MAX)
    static constexpr float    VAD_THRESH_MULT  = 5.0f;   // threshold = noise_floor × this (was 3.0 — ambient spikes kept resetting window)
    static constexpr float    VAD_FLOOR_MIN    = 0.003f; // abs. minimum threshold

    // ── State ─────────────────────────────────────────────────────────────────
    enum Phase { PH_IDLE, PH_RECORDING, PH_DONE, PH_ERROR };
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
        _phase = PH_RECORDING;
    }

    void _stopRecordingAndDispatch() {
        M5.Mic.end();
        M5.Speaker.end();
        M5.Speaker.begin();
        M5.Speaker.setVolume(150);

        if (!_pttBuf || _pttSamples < PTT_RATE / 4) {
            if (_pttBuf) { heap_caps_free(_pttBuf); _pttBuf = nullptr; }
            bool withinIdle = _inConversation &&
                              (millis() - _convLastValidMs < CONV_IDLE_MS);
            if (withinIdle) {
                _startRecording();  // auto re-listen — don't flash ready
            } else {
                _inConversation = false;
                _phase = PH_IDLE;
            }
            return;
        }

        face.setState(Ph3b3Face::THINKING);
        face.update();

        _dispatch(_pttBuf, _pttSamples);
        heap_caps_free(_pttBuf);
        _pttBuf = nullptr;
    }

    // ── Main dispatch: encode → /transcribe → /chat → play ───────────────────
    void _dispatch(int16_t* audio, int numSamples) {
        // Idle check before expensive work — if conversation timed out, skip entirely
        if (_inConversation && _convLastValidMs > 0 &&
            millis() - _convLastValidMs > CONV_IDLE_MS) {
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
            Serial.println("[talk] OOM: failed to alloc JSON buffer");
            face.setState(Ph3b3Face::ERROR);
            _phase = PH_ERROR;
            return;
        }

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

        WiFiClientSecure tls2;
        tls2.setCACert(ISRG_ROOT_X1);
        tls2.setTimeout(20000);
        HTTPClient http2;
        http2.begin(tls2, HOST, PORT, "/transcribe", true);
        http2.setAuthorization(USER, PASS);
        http2.addHeader("Content-Type", "application/json");
        http2.addHeader("X-Ph3b3-Device", "stackchan");
        http2.setConnectTimeout(20000);
        http2.setTimeout(30000);

        int code = http2.POST((uint8_t*)jbuf, pos);
        heap_caps_free(jbuf); jbuf = nullptr;

        _heardText = "";
        if (code == HTTP_CODE_OK) {
            String body = http2.getString();
            JsonDocument doc;
            deserializeJson(doc, body);
            const char* t = doc["text"];
            if (t && *t) _heardText = String(t);
        }
        http2.end();
        Serial.printf("[talk] transcribe=%d heard='%s'\n", code, _heardText.c_str());

        if (_heardText.length() == 0) {
            String err = (code > 0) ? "http " + String(code) :
                         (code == 0) ? "timeout" : "err " + String(code);
            if (_inConversation && millis() - _convLastValidMs < CONV_IDLE_MS) {
                Serial.printf("[talk] transcribe error in conv: %s — re-listen\n", err.c_str());
                _startRecording(); return;
            }
            face.setState(Ph3b3Face::ERROR);
            _inConversation = false;
            _phase = PH_ERROR;
            return;
        }

        // Junk filter: short transcripts (noise artifacts) don't trigger /chat
        if (_isJunkTranscript(_heardText)) {
            Serial.printf("[talk] junk transcript '%s' — discarded\n", _heardText.c_str());
            if (_inConversation && millis() - _convLastValidMs < CONV_IDLE_MS) {
                _startRecording(); return;  // re-listen, idle clock unchanged
            }
            _inConversation = false;
            _phase = PH_IDLE;
            return;
        }

        // Exit word detection — will end conversation after current SPEAK
        _exitAfterTurn = _isExitWord(_heardText);

        face.setState(Ph3b3Face::THINKING);
        face.update();

        // ── Step 3: POST /chat ────────────────────────────────────────────────
        _replyText = _doChatAndPlay(_heardText);
        bool ok = !_replyText.startsWith("ERR") && !_replyText.startsWith("HTTP") &&
                  !_replyText.startsWith("(no");

        // Barge-in: tap during SPEAK → reset idle and go straight to LISTEN
        if (_bargeIn) {
            _bargeIn = false;
            _exitAfterTurn = false;
            if (ok) _convLastValidMs = millis();
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

        bool convIdle = (_inConversation && _convLastValidMs > 0 &&
                         millis() - _convLastValidMs > CONV_IDLE_MS);

        // Continuous loop: SPEAK done → auto-reopen LISTEN (no "ready" flash)
        if (ok && _inConversation && !convIdle) {
            _startRecording();
            return;
        }

        // Conversation over (idle timeout, error, or normal end)
        if (!ok || convIdle) _inConversation = false;
        face.setState(ok ? Ph3b3Face::IDLE : Ph3b3Face::ERROR);
        _phase = ok ? PH_DONE : PH_ERROR;
    }

    // ── Conversation helpers ──────────────────────────────────────────────────
    bool _isJunkTranscript(const String& text) {
        String t = text; t.trim();
        return t.length() < (uint32_t)JUNK_MIN_LEN;
    }

    bool _isExitWord(const String& text) {
        String t = text; t.toLowerCase(); t.trim();
        if (t.indexOf("goodbye")          >= 0) return true;
        if (t.indexOf("bye")              >= 0) return true;
        if (t.indexOf("stop listening")    >= 0) return true;
        if (t.indexOf("that's all")       >= 0) return true;
        if (t.indexOf("thats all")        >= 0) return true;
        if (t.indexOf("thanks phoebe")    >= 0) return true;
        if (t.indexOf("thank you phoebe") >= 0) return true;
        if (t.indexOf("see you later")    >= 0) return true;
        return false;
    }

    void _endConversation() {
        _inConversation  = false;
        _exitAfterTurn   = false;
        _convLastValidMs = 0;
        face.setState(Ph3b3Face::IDLE);
        _phase = PH_IDLE;
    }

    // ── /chat + streaming audio ───────────────────────────────────────────────
    String _doChatAndPlay(const String& message) {
        WiFiClientSecure tls;
        tls.setCACert(ISRG_ROOT_X1);

        HTTPClient http;
        if (!http.begin(tls, HOST, PORT, "/chat", true))
            return String("ERR: begin failed");

        http.setConnectTimeout(30000);
        http.setTimeout(60000);
        http.setAuthorization(USER, PASS);
        http.addHeader("Content-Type", "application/json");
        http.addHeader("X-Ph3b3-Device", "stackchan");

        JsonDocument body;
        body["message"]    = message;
        body["session_id"] = _sessionId;
        String payload;
        serializeJson(body, payload);

        face.update();
        int code = http.POST(payload);
        if (code != HTTP_CODE_OK) { http.end(); return "HTTP " + String(code); }

        face.update();

        // ── Phase A: first 6 KB captures the "response" text field ───────────
        static const int PEEK_MAX = 6144;
        static char peek[PEEK_MAX + 1];
        WiFiClient* raw = http.getStreamPtr();
        raw->setTimeout(60000);
        int peekLen = raw->readBytes(peek, PEEK_MAX);
        peek[peekLen] = '\0';

        JsonDocument filter; filter["response"] = true;
        JsonDocument jdoc;
        deserializeJson(jdoc, peek, peekLen, DeserializationOption::Filter(filter));
        const char* resp = jdoc["response"];
        String responseText = (resp && *resp) ? String(resp) : "";

        if (responseText.length() > 0) {
            _applyMoodReaction(responseText);
            face.setState(Ph3b3Face::SPEAKING);
            face.update();
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
                // RMS of chunk about to play → lip-sync via setSpeakingLevel (~22 Hz)
                float rms = 0.0f;
                for (int i = 0; i < chunkPos; i++) {
                    float s = pcmBuf[fillIdx][i] / 32768.0f;
                    rms += s * s;
                }
                face.setSpeakingLevel(min(1.0f, sqrtf(rms / chunkPos) * 5.0f));
                face.update();
                // Queue next chunk as soon as there's room (don't wait for empty —
                // waiting for empty causes a gap between every chunk = choppy audio)
                while (M5.Speaker.isPlaying(0) >= 2) delay(1);
                if (!keepGoing) return;
                M5.Speaker.playRaw(pcmBuf[fillIdx], chunkPos, 22050, false, 1, 0);
                fillIdx ^= 1;
                chunkPos = 0;
            };

            auto pushByte = [&](uint8_t b) {
                if (wavHdrSkipped++ < 44) return;
                if (!halfReady) { halfLo = b; halfReady = true; return; }
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
                    M5.update();
                    int16_t tx2, ty2;
                    if (M5StackChan.Display().getTouch(&tx2, &ty2)) {
                        M5.Speaker.stop(0);
                        M5.Speaker.end();  // fully release I2S before mic can start
                        face.setSpeakingLevel(0.0f);
                        _bargeIn   = true;
                        keepGoing  = false;
                        break;
                    }
                    int c = raw->read();
                    if (c < 0) { delay(1); continue; }
                    feedCh((char)c);
                }
            }

            flushChunk();
            http.end();

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
            http.end();
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
inline const char* TalkApp::USER = "REDACTED";
inline const char* TalkApp::PASS = "REDACTED";
