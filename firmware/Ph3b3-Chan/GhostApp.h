#pragma once
#include "AppBase.h"
#include <M5StackChan.h>
#include <M5Unified.h>
#include <SD.h>

// ── Ghost Hunting — Rung 3 stub ──────────────────────────────────────────────
//
// EVIDENCE ARCHITECTURE (must be right before sensors are added):
//
//   Append-only invariant:
//   - SD log opened with FILE_APPEND only — NEVER FILE_WRITE (which truncates).
//   - NEVER seek backward. NEVER close + reopen for editing.
//   - flush() after every write so each entry survives a crash.
//   - The file only ever grows. This is what makes it evidence, not a note.
//
//   Format: one entry per line, monotonic ms timestamp.
//     [ms=0000000000] EVENT_TYPE key=value ...
//
//   Next ghost rung: add real IMU / mic / env sensor reads here.
//   They slot in as additional EVENT_TYPE lines — no format change needed.

class GhostApp : public AppBase {
public:
    void init() override {
        face.setState(Ph3b3Face::FOCUSED);
        _logOpen = false;
        _sessionStartMs = millis();
        _lastHeartbeatMs = 0;

        if (!SD.begin(4)) {
            Serial.println("[ghost] no SD card");
            return;
        }

        if (!SD.exists("/ghost")) SD.mkdir("/ghost");
        _buildFilename();

        _log = SD.open(_fname, FILE_APPEND);
        if (!_log) {
            Serial.printf("[ghost] log open failed: %s\n", _fname);
            return;
        }
        _logOpen = true;
        _appendLine("SESSION_START", "rung=3 source=stub");
        Serial.printf("[ghost] logging to %s\n", _fname);
    }

    void update() override {
        face.setState(Ph3b3Face::FOCUSED);

        uint32_t now = millis();
        if (_logOpen && now - _lastHeartbeatMs >= 5000) {
            _lastHeartbeatMs = now;
            _appendLine("HEARTBEAT", "source=stub sensor=none");
        }
    }

    void exit() override {
        if (_logOpen) {
            _appendLine("SESSION_END", "source=stub");
            _log.close();
            _logOpen = false;
        }
    }

    const char* name() const override { return "Ghost Hunting"; }

private:
    File     _log;
    bool     _logOpen        = false;
    uint32_t _sessionStartMs = 0;
    uint32_t _lastHeartbeatMs = 0;
    char     _fname[48];

    void _buildFilename() {
        if (M5.Rtc.isEnabled()) {
            auto d = M5.Rtc.getDate();
            auto t = M5.Rtc.getTime();
            snprintf(_fname, sizeof(_fname),
                     "/ghost/ev_%04d%02d%02d_%02d%02d%02d.log",
                     (int)d.year, (int)d.month, (int)d.date,
                     (int)t.hours, (int)t.minutes, (int)t.seconds);
        } else {
            snprintf(_fname, sizeof(_fname),
                     "/ghost/ev_%010lu.log", (unsigned long)millis());
        }
    }

    // Core append primitive — the ONLY path that touches the log file.
    // Appends one line: [ms=XXXXXXXXXX] EVENT key=value\n
    // Flushes immediately so each entry survives a crash.
    void _appendLine(const char* event, const char* kv) {
        if (!_logOpen) return;
        uint32_t ms = millis() - _sessionStartMs;
        char line[128];
        snprintf(line, sizeof(line), "[ms=%010lu] %s %s\n",
                 (unsigned long)ms, event, kv ? kv : "");
        _log.print(line);
        _log.flush();  // every write, every time
    }

};
