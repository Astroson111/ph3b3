/*
 * stackchan_rung3.ino
 * Ph3b3 / Stack-Chan — Rung 3: mode menu front door + four modes
 *
 * FQBN: m5stack:esp32:m5stack_cores3
 *
 * Boot sequence:
 *   1. BSP init (servos, LEDs, display, speaker, mic)
 *   2. Safe servo homing (tilt first, then pan)
 *   3. face.begin() — self-fits 320×240
 *   4. Register: Menu (0) → Talk (1) → Network (2) → Karaoke (3) → Ghost (4)
 *   5. Start on Menu (index 0)
 *
 * Return to menu: hold the top-left 60×60 px corner for 1 s from ANY mode.
 *   A dim "hold ↑ menu" hint is drawn in that corner by AppManager::draw().
 *
 * Face state is the single source driving both display and servo body language.
 *   applyBodyLanguage() translates state → servo motion every frame.
 *   KaraokeApp drives its own nod internally; all other modes use the table below.
 *
 * Servo safety: tilt stays 50–850 (5°–85°). Pan sways ≤ ±200 from centre.
 *
 * SD card layout (microSD, CS=GPIO4):
 *   /karaoke/track.wav  — 16-bit PCM WAV, any sample rate
 *   /karaoke/track.lrc  — LRC lyrics  [mm:ss.xx]text
 *   /ghost/ev_*.log     — append-only evidence logs (created by GhostApp on entry)
 *
 * If eyes render orange after flash, uncomment SC_FACE_BGR and recompile.
 */

// #define SC_FACE_BGR

#include "ph3b3_face.h"
#include "AppBase.h"
#include "AppManager.h"
#include "MenuApp.h"
#include "TalkApp.h"
#include "NetworkApp.h"
#include "KaraokeApp.h"
#include "GhostApp.h"

// ── Globals ───────────────────────────────────────────────────────────────────
Ph3b3Face  face;
AppManager appMgr;

// ── App instances (order = menu index) ───────────────────────────────────────
static MenuApp    menuApp;      // 0 — always the front door
static TalkApp    talkApp;      // 1
static NetworkApp networkApp;   // 2
static KaraokeApp karaokeApp;   // 3
static GhostApp   ghostApp;     // 4

// ── Servo constants ───────────────────────────────────────────────────────────
static const int TILT_HOME = 450;
static const int TILT_MIN  =  50;
static const int TILT_MAX  = 850;

// ── Body language ─────────────────────────────────────────────────────────────
static Ph3b3Face::State _lastBLState = Ph3b3Face::BOOT;

static void applyBodyLanguage(Ph3b3Face::State s) {
    if (s == _lastBLState) return;
    _lastBLState = s;
    switch (s) {
        case Ph3b3Face::LISTENING:
            M5StackChan.Motion.moveX(200, 300);
            M5StackChan.Motion.moveY(TILT_HOME + 30, 200);
            break;
        case Ph3b3Face::THINKING:
            M5StackChan.Motion.moveX(0, 200);
            M5StackChan.Motion.moveY(TILT_HOME - 50, 200);
            break;
        case Ph3b3Face::SPEAKING:
            M5StackChan.Motion.moveX(0, 200);
            break;
        case Ph3b3Face::IDLE:
        case Ph3b3Face::CONNECTING:
        case Ph3b3Face::ERROR:
        default:
            M5StackChan.Motion.moveX(0, 200);
            M5StackChan.Motion.moveY(TILT_HOME, 200);
            break;
    }
}

// ── Safe homing ───────────────────────────────────────────────────────────────
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

// ── Global return-to-menu gesture ─────────────────────────────────────────────
// Hold the top-left 60×60 px corner for 1 s → returnToMenu().
// Runs before appMgr.update() so the app never processes this touch.
static uint32_t _menuHoldMs = 0;

static bool checkMenuReturn() {
    if (appMgr.isOnMenu()) { _menuHoldMs = 0; return false; }
    int16_t tx = 0, ty = 0;
    bool t = M5StackChan.Display().getTouch(&tx, &ty);
    if (t && tx < 60 && ty < 60) {
        if (_menuHoldMs == 0) _menuHoldMs = millis();
        if (millis() - _menuHoldMs >= 1000) {
            _menuHoldMs = 0;
            appMgr.returnToMenu();
            return true;
        }
    } else {
        _menuHoldMs = 0;
    }
    return false;
}

// ── setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("[rung3] boot");

    M5StackChan.begin();

    // Boot splash
    auto& d = M5StackChan.Display();
    d.fillScreen(TFT_BLACK);
    d.setTextDatum(middle_center);
    d.setTextSize(2);
    d.setTextColor(TFT_CYAN, TFT_BLACK);
    d.drawString("Ph3b3", d.width() / 2, d.height() / 2 - 20);
    d.setTextSize(1);
    d.setTextColor(TFT_WHITE, TFT_BLACK);
    d.drawString("homing servos...", d.width() / 2, d.height() / 2 + 16);

    safeHome();
    Serial.println("[rung3] homed");

    face.begin();

    // Register in index order — menu MUST be 0.
    appMgr.registerApp(&menuApp);     // 0
    appMgr.registerApp(&talkApp);     // 1
    appMgr.registerApp(&networkApp);  // 2
    appMgr.registerApp(&karaokeApp);  // 3
    appMgr.registerApp(&ghostApp);    // 4

    appMgr.begin(MENU_IDX);
    Serial.println("[rung3] setup done");
}

// ── loop ──────────────────────────────────────────────────────────────────────
void loop() {
    M5StackChan.update();

    // Global gesture must check before app gets the touch event
    if (checkMenuReturn()) {
        delay(16);
        return;
    }

    appMgr.update();
    face.update();
    appMgr.draw();
    applyBodyLanguage(face.getState());

    delay(16);
}
