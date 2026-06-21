/*
 * stackchan_rung2.ino
 * Ph3b3 / Stack-Chan — Rung 2: app framework + karaoke
 *
 * FQBN: m5stack:esp32:m5stack_cores3
 *
 * Face: ph3b3_face.h (Iris's engine). Self-fits 320×240 via begin().
 *   - No SC_FACE_BGR defined → normal RGB color order for CoreS3.
 *   - If eyes render orange after flash, add: #define SC_FACE_BGR
 *     before the ph3b3_face.h include and recompile.
 *
 * Face state IS the single source driving both display and servo body language.
 * applyBodyLanguage() translates state → servo commands every frame.
 *
 * Servo safety: tilt stays 50–850 (5°–85°) throughout. Pan sways ≤ ±150 (±15°).
 *
 * Boot sequence:
 *   1. BSP init (servos, LEDs, display, speaker, mic)
 *   2. Safe homing (tilt first, then pan), one axis at a time
 *   3. face.begin() → self-fits 320×240
 *   4. App manager: register Menu → Karaoke → Ph3b3-stub
 *   5. Start on Menu
 *
 * SD card layout (microSD, CS=GPIO4):
 *   /karaoke/track.wav   — 16-bit PCM WAV (any sample rate, mono or stereo)
 *   /karaoke/track.lrc   — LRC lyric file  [mm:ss.xx]text
 */

// #define SC_FACE_BGR   // uncomment if eyes come up orange on CoreS3

#include "ph3b3_face.h"
#include "AppBase.h"
#include "AppManager.h"
#include "StubApp.h"
#include "MenuApp.h"
#include "KaraokeApp.h"

// ── Globals (extern'd by AppBase.h / MenuApp.h) ─────────────────────────────
Ph3b3Face  face;
AppManager appMgr;

// ── App instances ────────────────────────────────────────────────────────────
static MenuApp    menuApp;
static KaraokeApp karaokeApp;
static StubApp    stubApp;

// ── Servo tilt safe bounds (repeated here for homing) ───────────────────────
static const int TILT_HOME = 450;
static const int TILT_MIN  =  50;
static const int TILT_MAX  = 850;

// ── Body language ────────────────────────────────────────────────────────────
// Called every loop frame. Translates face state → servo motion.
// KaraokeApp drives its own servo nod; this only fires for non-karaoke states.
static Ph3b3Face::State _lastBLState = Ph3b3Face::BOOT;

static void applyBodyLanguage(Ph3b3Face::State s) {
    if (s == _lastBLState) return;
    _lastBLState = s;

    switch (s) {
        case Ph3b3Face::LISTENING:
            // Turn toward the user (their left = robot's right = positive X pan)
            M5StackChan.Motion.moveX(200, 300);
            M5StackChan.Motion.moveY(TILT_HOME + 30, 200);  // slight look-up = attentive
            break;
        case Ph3b3Face::THINKING:
            M5StackChan.Motion.moveX(0, 200);
            M5StackChan.Motion.moveY(TILT_HOME - 50, 200);  // slight look-down = contemplating
            break;
        case Ph3b3Face::IDLE:
        case Ph3b3Face::CONNECTING:
        case Ph3b3Face::ERROR:
            M5StackChan.Motion.moveX(0, 200);
            M5StackChan.Motion.moveY(TILT_HOME, 200);
            break;
        case Ph3b3Face::SPEAKING:
            // KaraokeApp drives nod internally; for non-karaoke SPEAKING just centre
            M5StackChan.Motion.moveX(0, 200);
            break;
        default: break;
    }
}

// ── Safe homing (same approach as Rung 1) ────────────────────────────────────
static void waitAxis(bool (*fn)()) {
    uint32_t t0 = millis();
    while (fn() && millis() - t0 < 5000) delay(10);
}

static void safeHome() {
    M5StackChan.Motion.moveY(TILT_HOME, 200);
    waitAxis([]() { return M5StackChan.Motion.isYMoving(); });
    delay(200);
    M5StackChan.Motion.moveX(0, 200);
    waitAxis([]() { return M5StackChan.Motion.isXMoving(); });
}

// ── setup ────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("[rung2] boot");

    M5StackChan.begin();

    // Boot splash before homing
    M5StackChan.Display().fillScreen(TFT_BLACK);
    M5StackChan.Display().setTextDatum(middle_center);
    M5StackChan.Display().setTextSize(2);
    M5StackChan.Display().setTextColor(TFT_CYAN, TFT_BLACK);
    M5StackChan.Display().drawString("Ph3b3", M5StackChan.Display().width() / 2,
                                     M5StackChan.Display().height() / 2 - 20);
    M5StackChan.Display().setTextSize(1);
    M5StackChan.Display().setTextColor(TFT_WHITE, TFT_BLACK);
    M5StackChan.Display().drawString("homing servos...",
                                     M5StackChan.Display().width() / 2,
                                     M5StackChan.Display().height() / 2 + 16);

    safeHome();
    Serial.println("[rung2] homed");

    // Face init — reads 320×240 from M5.Display
    face.begin();

    // Register apps: Menu must be last so its self-index detection works
    appMgr.registerApp(&karaokeApp);
    appMgr.registerApp(&stubApp);
    appMgr.registerApp(&menuApp);

    // Start on Menu (index 2)
    appMgr.begin(2);
    Serial.println("[rung2] setup done");
}

// ── loop ─────────────────────────────────────────────────────────────────────
void loop() {
    M5StackChan.update();

    // Active app sets face state + runs its logic
    appMgr.update();

    // Render face (always, full or partial canvas per active app's begin() call)
    face.update();

    // Active app draws overlays on top of face (e.g. karaoke lyrics)
    appMgr.draw();

    // Servo body language follows face state
    applyBodyLanguage(face.getState());

    delay(16);
}
