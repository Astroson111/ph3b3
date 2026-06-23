#pragma once
#include "AppBase.h"
#include <M5StackChan.h>
extern bool g_overlayOpen;
#include <M5Unified.h>
#include <SD.h>
#include <vector>
#include <algorithm>

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
        _state = BROWSING;
        face.begin(320, 160);  // top 160 px for face, bottom 80 for browser/lyrics
        face.setState(Ph3b3Face::IDLE);

        // Mount SD once per mode entry — avoids 200-500ms SPI init blocking every tap.
        _sdMounted = SD.begin(4);
        if (_sdMounted) {
            _scanTracks();
        } else {
            Serial.println("[karaoke] no SD card at init");
            _tracks.clear();
        }
        if (_trackSel >= (int)_tracks.size()) _trackSel = 0;

        // 30ms settle: BCK/WS lines are shared with speaker I2S (GPIO 34/33).
        // TalkApp.exit() calls Speaker.end() immediately before we run; without
        // this delay Mic.begin() can initialise against an unsettled clock.
        delay(30);
        M5.Mic.begin();
    }

    void exit() override {
        _stopPlayback();
        M5.Mic.end();
        _sdMounted = false;  // reset so next init() re-mounts (handles card swap)
        _tracks.clear();
        face.begin();                           // restore full-screen face
    }

    void update() override {
        if (!g_overlayOpen) {
            int16_t tx = 0, ty = 0;
            bool touching = M5StackChan.Display().getTouch(&tx, &ty);
            // Reserve top-left 60×60 px for crescent tab
            bool tapped = (touching && !_wasTouch) && !(tx < 60 && ty < 60);
            _wasTouch = touching;

            if (tapped) {
                if (_state == BROWSING) {
                    int H = M5StackChan.Display().height();  // 240
                    if (ty < H / 3) {
                        // Top third → prev track (wraps)
                        if (!_tracks.empty())
                            _trackSel = (_trackSel > 0) ? _trackSel - 1 : (int)_tracks.size() - 1;
                    } else if (ty > 2 * H / 3) {
                        // Bottom third → next track (wraps)
                        if (!_tracks.empty())
                            _trackSel = (_trackSel + 1) % (int)_tracks.size();
                    } else {
                        // Centre → play selected track
                        if (!_tracks.empty()) _startPlayback();
                    }
                } else {
                    _stopPlayback();
                }
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
        if (_state == PLAYING) _drawCurrentLyric();
        else                   _drawBrowser();
    }

    const char* name() const override { return "Karaoke"; }

private:
    enum KState { BROWSING, PLAYING };
    KState _state    = BROWSING;
    bool   _wasTouch = false;

    // ── Track browser ────────────────────────────────────────────────────────
    std::vector<String> _tracks;
    int      _trackSel    = 0;

    // ── Playback ────────────────────────────────────────────────────────────
    bool     _sdMounted    = false;
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
    bool     _nodUp      = false;
    uint32_t _nodTickMs  = 0;
    int      _panDir     = 1;
    uint32_t _swayTickMs = 0;

    // ── Mic VU ──────────────────────────────────────────────────────────────
    int16_t  _micBuf[K_MIC_SAMPLES];
    uint8_t  _vuLevel    = 0;


    // ────────────────────────────────────────────────────────────────────────

    // Scan /karaoke/ for .wav files and populate _tracks with their stems.
    void _scanTracks() {
        _tracks.clear();
        File dir = SD.open("/karaoke");
        if (!dir || !dir.isDirectory()) {
            Serial.println("[KAR] /karaoke dir not found");
            return;
        }
        for (;;) {
            File f = dir.openNextFile();
            if (!f) break;
            String nm = String(f.name());
            f.close();
            // SD lib may return just the filename or the full path — normalise.
            int slash = nm.lastIndexOf('/');
            if (slash >= 0) nm = nm.substring(slash + 1);
            String lower = nm; lower.toLowerCase();
            if (lower.endsWith(".wav"))
                _tracks.push_back(nm.substring(0, nm.length() - 4));
        }
        dir.close();
        std::sort(_tracks.begin(), _tracks.end());
        Serial.printf("[KAR] found %d track(s)\n", (int)_tracks.size());
    }

    // Draw track browser in the bottom 80 px strip (y 160–239).
    // Full-screen touch zones: top third = prev, centre = play, bottom third = next.
    void _drawBrowser() {
        auto& d = M5StackChan.Display();
        int W = d.width();  // 320
        d.fillRect(0, 160, W, 80, TFT_BLACK);
        d.drawFastHLine(0, 161, W, d.color565(40, 20, 80));

        if (_tracks.empty()) {
            d.setTextDatum(middle_center);
            d.setTextSize(1);
            d.setTextColor(_sdMounted ? d.color565(160, 80, 80) : d.color565(120, 60, 60), TFT_BLACK);
            d.drawString(_sdMounted ? "no tracks on SD" : "no SD card", W / 2, 200);
            return;
        }

        // Navigation hint
        d.setTextDatum(top_center);
        d.setTextSize(1);
        d.setTextColor(d.color565(60, 40, 100), TFT_BLACK);
        d.drawString("^ prev  |  center: play  |  next v", W / 2, 164);

        // Track name — dashes → spaces, truncate to 20 chars
        String nm = _tracks[_trackSel];
        for (int i = 0; i < (int)nm.length(); i++) if (nm[i] == '-') nm[i] = ' ';
        if ((int)nm.length() > 20) { nm = nm.substring(0, 18); nm += ".."; }

        d.setTextDatum(middle_center);
        d.setTextSize(2);
        d.setTextColor(TFT_CYAN, TFT_BLACK);
        d.drawString(nm, W / 2, 196);

        // Track counter
        d.setTextDatum(bottom_center);
        d.setTextSize(1);
        d.setTextColor(d.color565(100, 80, 160), TFT_BLACK);
        d.drawString(String(_trackSel + 1) + " / " + String(_tracks.size()), W / 2, 237);
    }

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
            if (line.length() < 9 || line[0] != '[') continue;
            int close = line.indexOf(']');
            if (close < 0) continue;
            String ts   = line.substring(1, close);
            String text = line.substring(close + 1);
            text.trim();
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
        if (!_sdMounted) {
            _sdMounted = SD.begin(4);
            if (!_sdMounted) { Serial.println("[karaoke] no SD card"); return; }
        }

        String stem    = _tracks[_trackSel];
        String wavPath = "/karaoke/" + stem + ".wav";
        String lrcPath = "/karaoke/" + stem + ".lrc";

        _wavFile = SD.open(wavPath.c_str());
        if (!_wavFile) {
            Serial.printf("[karaoke] can't open %s\n", wavPath.c_str());
            return;
        }
        _trackName = stem;
        if (!_parseWavHeader()) {
            Serial.println("[karaoke] bad WAV header");
            _wavFile.close();
            return;
        }

        _loadLyrics(lrcPath.c_str());
        _lyricIdx       = 0;
        _playStartMs    = millis();
        _fillIdx        = 0;
        M5.Speaker.begin();
        M5.Speaker.setVolume(200);
        _state = PLAYING;

        M5StackChan.Motion.moveX(0, 300);
        M5StackChan.Motion.moveY(K_TILT_HOME, 200);
        M5StackChan.showRgbColor(20, 0, 60);
        Serial.printf("[karaoke] playing: %s\n", stem.c_str());
    }

    void _stopPlayback() {
        if (_state != PLAYING) return;
        M5.Speaker.stop();
        _wavFile.close();
        _state = BROWSING;

        M5StackChan.Motion.moveX(0, 200);
        M5StackChan.Motion.moveY(K_TILT_HOME, 200);
        M5StackChan.showRgbColor(0, 0, 0);
    }

    // ── Subsystem A+C: stream WAV from SD → M5.Speaker double-buffer ────────
    void _streamAudio() {
        if (!_wavFile.available()) { _stopPlayback(); return; }
        if (M5.Speaker.isPlaying(K_CHAN) >= 2) return;

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

        while (_lyricIdx + 1 < (int)_lyrics.size() &&
               _lyrics[_lyricIdx + 1].ms <= elapsed) {
            _lyricIdx++;
        }

        auto& d = M5StackChan.Display();
        int W = d.width();
        d.fillRect(0, 160, W, 80, TFT_BLACK);
        d.setTextDatum(middle_center);
        d.setTextColor(TFT_YELLOW, TFT_BLACK);
        d.setTextSize(2);
        d.drawString(_lyrics[_lyricIdx].text, W / 2, 185);

        if (_lyricIdx + 1 < (int)_lyrics.size()) {
            d.setTextColor(TFT_DARKGREY, TFT_BLACK);
            d.setTextSize(1);
            d.drawString(_lyrics[_lyricIdx + 1].text, W / 2, 215);
        }
    }

    // ── Subsystem D: gentle head bob / sway ─────────────────────────────────
    void _tickNod() {
        uint32_t now = millis();

        if (now - _nodTickMs > 600) {
            _nodTickMs = now;
            int tilt = _nodUp ? K_TILT_HOME + 30 : K_TILT_HOME - 30;
            tilt = constrain(tilt, K_TILT_MIN, K_TILT_MAX);
            M5StackChan.Motion.moveY(tilt, 400);
            _nodUp = !_nodUp;
        }

        if (now - _swayTickMs > 1500) {
            _swayTickMs = now;
            M5StackChan.Motion.moveX(_panDir * K_PAN_RANGE, 600);
            _panDir = -_panDir;
        }
    }

    // ── Subsystem E: RGB LED beat flash ─────────────────────────────────────
    void _tickLeds() {
        static uint32_t ledMs    = 0;
        static int      ledPhase = 0;
        if (millis() - ledMs < 500) return;
        ledMs = millis();
        ledPhase = (ledPhase + 1) % 4;
        static const uint8_t cols[4][3] = {
            {40,0,80}, {0,20,80}, {80,0,40}, {0,40,80}
        };
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
        if (M5.Mic.isRecording()) return;
        M5.Mic.record(_micBuf, K_MIC_SAMPLES, 16000, false);

        int64_t sum = 0;
        for (int i = 0; i < K_MIC_SAMPLES; i++) sum += (int64_t)_micBuf[i] * _micBuf[i];
        float rms   = sqrtf((float)(sum / K_MIC_SAMPLES));
        float level = constrain(rms / 8000.0f, 0.0f, 1.0f);
        face.setSpeakingLevel(level);

        uint8_t bright = (uint8_t)(level * 80);
        M5StackChan.showRgbColor(bright, 0, bright / 2);
    }

};
