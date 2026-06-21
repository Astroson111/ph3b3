#pragma once
#include "AppBase.h"
#include <M5StackChan.h>
extern bool g_overlayOpen;
#include <M5Unified.h>
#include <SD.h>
#include <vector>

// ── Servo tilt safe window (BSP angle units: 10 = 1°) ──────────────────────
static const int K_TILT_MIN  =  50;  //  5°
static const int K_TILT_MAX  = 850;  // 85°
static const int K_TILT_HOME = 450;  // 45° — neutral center
static const int K_PAN_RANGE = 150;  // ±15° sway during karaoke

// ── Audio streaming ─────────────────────────────────────────────────────────
static const int  K_CHUNK    = 1024;   // PCM samples per buffer half
static const int  K_CHAN     = 0;      // M5 Speaker virtual channel

// ── Mic VU ──────────────────────────────────────────────────────────────────
static const int  K_MIC_SAMPLES = 256;

// ── LRC lyrics ──────────────────────────────────────────────────────────────
struct LyricLine { uint32_t ms; String text; };

// ── WAV header (44-byte standard PCM) ────────────────────────────────────────
struct WavHdr {
    char     riff[4];
    uint32_t fileSize;
    char     wave[4];
    char     fmt[4];
    uint32_t fmtSize;
    uint16_t audioFmt;
    uint16_t channels;
    uint32_t sampleRate;
    uint32_t byteRate;
    uint16_t blockAlign;
    uint16_t bitsPerSample;
    char     data[4];
    uint32_t dataSize;
} __attribute__((packed));

// ─────────────────────────────────────────────────────────────────────────────

class KaraokeApp : public AppBase {
public:
    void init() override {
        _state = STOPPED;
        face.begin(320, 160);  // top 160 px for face, bottom 80 for lyrics
        face.setState(Ph3b3Face::IDLE);

        // Mic — start continuous short recordings for VU meter
        M5.Mic.begin();
    }

    void exit() override {
        _stopPlayback();
        M5.Mic.end();
        face.begin();                           // restore full-screen face
    }

    void update() override {
        if (!g_overlayOpen) {
            int16_t tx = 0, ty = 0;
            bool touching = M5StackChan.Display().getTouch(&tx, &ty);
            // Reserve top-left 36×36 px for crescent tab
            bool tapped = (touching && !_wasTouch) && !(tx < 36 && ty < 36);
            _wasTouch = touching;

            if (tapped) {
                if (_state == STOPPED) _startPlayback();
                else                   _stopPlayback();
            }
        } else {
            int16_t _tx, _ty;
            _wasTouch = M5StackChan.Display().getTouch(&_tx, &_ty);
        }

        if (_state == PLAYING) {
            _streamAudio();
            _tickNod();
            _tickLeds();
            _tickMic();
            face.setState(Ph3b3Face::SPEAKING);
        } else {
            face.setState(Ph3b3Face::IDLE);
        }
    }

    void draw() override {
        // Lyrics in the bottom 80 px (y 160–240), drawn after face.update() pushes face sprite
        if (_state == PLAYING) _drawCurrentLyric();
    }

    const char* name() const override { return "Karaoke"; }

private:
    enum KState { STOPPED, PLAYING };
    KState _state     = STOPPED;
    bool   _wasTouch  = false;

    // ── Playback ────────────────────────────────────────────────────────────
    File     _wavFile;
    int16_t  _audioBuf[2][K_CHUNK];
    int      _fillIdx      = 0;
    uint32_t _sampleRate   = 44100;
    bool     _stereo       = false;
    String   _trackName;

    // ── Lyrics ──────────────────────────────────────────────────────────────
    std::vector<LyricLine> _lyrics;
    int      _lyricIdx     = 0;
    uint32_t _playStartMs  = 0;

    // ── Body language ───────────────────────────────────────────────────────
    bool     _nodUp        = false;
    uint32_t _nodTickMs    = 0;
    int      _panDir       = 1;
    uint32_t _swayTickMs   = 0;

    // ── Mic VU ──────────────────────────────────────────────────────────────
    int16_t  _micBuf[K_MIC_SAMPLES];
    uint8_t  _vuLevel      = 0;

    // ── SD path helpers ─────────────────────────────────────────────────────
    static constexpr const char* TRACK_WAV = "/karaoke/track.wav";
    static constexpr const char* TRACK_LRC = "/karaoke/track.lrc";

    // ────────────────────────────────────────────────────────────────────────

    bool _parseWavHeader() {
        WavHdr hdr;
        if (_wavFile.read((uint8_t*)&hdr, sizeof(hdr)) != sizeof(hdr)) return false;
        if (strncmp(hdr.riff, "RIFF", 4) || strncmp(hdr.wave, "WAVE", 4)) return false;
        _sampleRate = hdr.sampleRate;
        _stereo     = (hdr.channels == 2);
        return (hdr.audioFmt == 1 && hdr.bitsPerSample == 16);
    }

    void _loadLyrics(const char* path) {
        _lyrics.clear();
        File lrc = SD.open(path);
        if (!lrc) return;
        while (lrc.available()) {
            String line = lrc.readStringUntil('\n');
            line.trim();
            // Expect [mm:ss.xx] or [mm:ss.xxx]
            if (line.length() < 9 || line[0] != '[') continue;
            int close = line.indexOf(']');
            if (close < 0) continue;
            String ts = line.substring(1, close);
            String text = line.substring(close + 1);
            text.trim();
            // Parse mm:ss.xx
            int colon = ts.indexOf(':');
            int dot   = ts.indexOf('.');
            if (colon < 0 || dot < 0) continue;
            uint32_t mm  = ts.substring(0, colon).toInt();
            uint32_t ss  = ts.substring(colon + 1, dot).toInt();
            uint32_t hun = ts.substring(dot + 1).toInt();
            // Normalise hundredths → ms (handle 2- or 3-digit fractions)
            uint32_t fracMs = (ts.length() - dot - 1 >= 3) ? hun : hun * 10;
            uint32_t ms = (mm * 60 + ss) * 1000 + fracMs;
            if (text.length() > 0)
                _lyrics.push_back({ms, text});
        }
        lrc.close();
    }

    void _startPlayback() {
        if (!SD.begin(4)) {
            Serial.println("[karaoke] no SD card");
            return;
        }
        _wavFile = SD.open(TRACK_WAV);
        if (!_wavFile) {
            Serial.println("[karaoke] no track.wav");
            return;
        }
        _trackName = String(TRACK_WAV).substring(9);
        if (!_parseWavHeader()) {
            Serial.println("[karaoke] bad WAV header");
            _wavFile.close();
            return;
        }

        _loadLyrics(TRACK_LRC);
        _lyricIdx   = 0;
        _playStartMs = millis();
        _fillIdx     = 0;
        M5.Speaker.begin();
        M5.Speaker.setVolume(200);
        _state = PLAYING;

        // Pan to centre, set SPEAKING body language
        M5StackChan.Motion.moveX(0, 300);
        M5StackChan.Motion.moveY(K_TILT_HOME, 200);

        // Initial LED flash
        M5StackChan.showRgbColor(20, 0, 60);
    }

    void _stopPlayback() {
        if (_state != PLAYING) return;
        M5.Speaker.stop();
        _wavFile.close();
        _state = STOPPED;

        // Return servos to neutral
        M5StackChan.Motion.moveX(0, 200);
        M5StackChan.Motion.moveY(K_TILT_HOME, 200);
        M5StackChan.showRgbColor(0, 0, 0);
    }

    // ── Subsystem A+C: stream WAV from SD → M5.Speaker double-buffer ────────
    void _streamAudio() {
        // Queue next chunk only when the speaker channel has room
        if (!_wavFile.available()) { _stopPlayback(); return; }
        if (M5.Speaker.isPlaying(K_CHAN) >= 2) return;  // queue full, try next tick

        size_t bytes = _wavFile.read(
            (uint8_t*)_audioBuf[_fillIdx],
            K_CHUNK * sizeof(int16_t)
        );
        if (bytes == 0) { _stopPlayback(); return; }

        size_t samples = bytes / sizeof(int16_t);
        M5.Speaker.playRaw(_audioBuf[_fillIdx], samples, _sampleRate, _stereo,
                           1, K_CHAN, false);
        _fillIdx ^= 1;
    }

    // ── Subsystem B: lyrics overlay ─────────────────────────────────────────
    void _drawCurrentLyric() {
        if (_lyrics.empty()) return;
        uint32_t elapsed = millis() - _playStartMs;

        // Advance lyric index
        while (_lyricIdx + 1 < (int)_lyrics.size() &&
               _lyrics[_lyricIdx + 1].ms <= elapsed) {
            _lyricIdx++;
        }

        auto& d = M5StackChan.Display();
        int W = d.width();
        // Clear the lyric strip (below face canvas at y=160)
        d.fillRect(0, 160, W, 80, TFT_BLACK);
        d.setTextDatum(middle_center);
        d.setTextColor(TFT_YELLOW, TFT_BLACK);
        d.setTextSize(2);

        // Current line
        d.drawString(_lyrics[_lyricIdx].text, W / 2, 185);

        // Next line (preview, dimmed)
        if (_lyricIdx + 1 < (int)_lyrics.size()) {
            d.setTextColor(TFT_DARKGREY, TFT_BLACK);
            d.setTextSize(1);
            d.drawString(_lyrics[_lyricIdx + 1].text, W / 2, 215);
        }
    }

    // ── Subsystem D: gentle head bob / sway ─────────────────────────────────
    void _tickNod() {
        uint32_t now = millis();

        // Nod: alternate tilt every 600 ms while SPEAKING
        if (now - _nodTickMs > 600) {
            _nodTickMs = now;
            int tilt = _nodUp ? K_TILT_HOME + 30 : K_TILT_HOME - 30;
            tilt = constrain(tilt, K_TILT_MIN, K_TILT_MAX);
            M5StackChan.Motion.moveY(tilt, 400);
            _nodUp = !_nodUp;
        }

        // Sway: pan left/right every 1500 ms
        if (now - _swayTickMs > 1500) {
            _swayTickMs = now;
            M5StackChan.Motion.moveX(_panDir * K_PAN_RANGE, 600);
            _panDir = -_panDir;
        }
    }

    // ── Subsystem E: RGB LED beat flash ─────────────────────────────────────
    void _tickLeds() {
        // Simple alternating colour pulse — 500 ms period
        // Replace with FFT beat detection in a future rung
        static uint32_t ledMs = 0;
        static int      ledPhase = 0;
        if (millis() - ledMs < 500) return;
        ledMs = millis();
        ledPhase = (ledPhase + 1) % 4;
        static const uint8_t cols[4][3] = {
            {40,0,80}, {0,20,80}, {80,0,40}, {0,40,80}
        };
        // Left side: one colour, right side: complementary
        for (int i = 0; i < 6; i++)
            M5StackChan.setRgbColor(i,
                cols[ledPhase][0], cols[ledPhase][1], cols[ledPhase][2]);
        int c2 = (ledPhase + 2) % 4;
        for (int i = 6; i < 12; i++)
            M5StackChan.setRgbColor(i,
                cols[c2][0], cols[c2][1], cols[c2][2]);
        M5StackChan.refreshRgb();
    }

    // ── Subsystem F: mic VU → face speaking level ────────────────────────────
    // !! SIMULTANEITY FLAG: Speaker=I2S_NUM_1, Mic=I2S_NUM_0, shared BCK/WS(34/33).
    // If speaker audio cuts out when mic is active, disable Mic.begin() in init()
    // and comment out this function call in update(). Needs runtime verification.
    void _tickMic() {
        if (M5.Mic.isRecording()) return;  // wait for previous capture to finish
        M5.Mic.record(_micBuf, K_MIC_SAMPLES, 16000, false);

        // Compute RMS as speaking level for face lip-sync
        int64_t sum = 0;
        for (int i = 0; i < K_MIC_SAMPLES; i++) sum += (int64_t)_micBuf[i] * _micBuf[i];
        float rms = sqrtf((float)(sum / K_MIC_SAMPLES));
        float level = constrain(rms / 8000.0f, 0.0f, 1.0f);
        face.setSpeakingLevel(level);

        // LED brightness scales with singer's level
        uint8_t bright = (uint8_t)(level * 80);
        M5StackChan.showRgbColor(bright, 0, bright / 2);
    }

};
