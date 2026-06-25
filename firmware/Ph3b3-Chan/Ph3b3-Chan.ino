/*
 * stackchan_rung4.ino
 * Ph3b3 / Stack-Chan — Rung 4: Talk / Ph3b3 voice round-trip
 *
 * FQBN: m5stack:esp32:m5stack_cores3
 *
 * NEW in Rung 4 vs Rung 3:
 *   - WiFi connection managed in main sketch (supervisor tick in loop)
 *   - TalkApp (index 1) fully implemented: mic → /transcribe → /chat → speaker
 *   - ISRG Root X1 + X2 cert bundle for Let's Encrypt TLS
 *   - Credentials synced from /iris/networks after first connect (saved to NVS "sc")
 *
 * First-boot WiFi setup:
 *   Fill in SC_WIFI_SSID / SC_WIFI_PASS below, flash once, connect.
 *   After connecting, Ph3b3's /iris/networks is pulled and saved to NVS —
 *   subsequent boots load from NVS so you can blank these defines again.
 *
 * Mode switching: tap the crescent tab (top-left corner) to open the mode overlay.
 *
 * SD card layout (microSD, CS=GPIO4):
 *   /karaoke/track.wav  /karaoke/track.lrc  /ghost/ev_*.log
 */

// ── First-boot WiFi (blank after NVS is seeded) ───────────────────────────────
#define SC_WIFI_SSID  ""
#define SC_WIFI_PASS  ""

// ── Ph3b3 auth — credentials live in gitignored secrets.h ────────────────────
#include "secrets.h"

#define SC_FACE_BGR   // CoreS3 ILI9342 is BGR; swap R↔B so violet renders violet, not cyan

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>

#include "ph3b3_face.h"
#include "AppBase.h"
#include "AppManager.h"
#include "CrescentMenu.h"
#include "TalkApp.h"
#include "NetworkApp.h"
#include "KaraokeApp.h"
#include "GhostApp.h"

// ── TLS cert bundle ───────────────────────────────────────────────────────────
// ISRG Root X1 (RSA) + Root X2 (ECDSA) concatenated.
// Let's Encrypt switched to YE2 → Root X2 chain on 2026-06-19; keep both.
const char ISRG_ROOT_X1[] = R"EOF(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIICGzCCAaGgAwIBAgIQQdKd0XLq7qeAwSxs6S+HUjAKBggqhkjOPQQDAzBPMQsw
CQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJuZXQgU2VjdXJpdHkgUmVzZWFyY2gg
R3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBYMjAeFw0yMDA5MDQwMDAwMDBaFw00
MDA5MTcxNjAwMDBaME8xCzAJBgNVBAYTAlVTMSkwJwYDVQQKEyBJbnRlcm5ldCBT
ZWN1cml0eSBSZXNlYXJjaCBHcm91cDEVMBMGA1UEAxMMSVNSRyBSb290IFgyMHYw
EAYHKoZIzj0CAQYFK4EEACIDYgAEzZvVn4CDCuwJSvMWSj5cz3es3mcFDR0HttwW
+1qLFNvicWDEukWVEYmO6gbf9yoWHKS5xcUy4APgHoIYOIvXRdgKam7mAHf7AlF9
ItgKbppbd9/w+kHsOdx1ymgHDB/qo0IwQDAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0T
AQH/BAUwAwEB/zAdBgNVHQ4EFgQUfEKWrt5LSDv6kviejM9ti6lyN5UwCgYIKoZI
zj0EAwMDaAAwZQIwe3lORlCEwkSHRhtFcP9Ymd70/aTSVaYgLXTWNLxBo1BfASdW
tL4ndQavEi51mI38AjEAi/V3bNTIZargCyzuFJ0nN6T5U6VR5CmD1/iQMVtCnwr1
/q4AaOeMSQ+2b1tbFfLn
-----END CERTIFICATE-----
)EOF";

// ── WiFi / NVS ────────────────────────────────────────────────────────────────
static Preferences sPrefs;
static const char  NVS_NS[]      = "sc";
static const char* SSID_KEYS[]   = {"ssid0","ssid1","ssid2"};
static const char* PASS_KEYS[]   = {"pass0","pass1","pass2"};
static const int   SC_MAX_NETS   = 3;

static bool     sWifiConnected = false;
static uint32_t sLastReconnect = 0;
static bool     sSyncDone      = false;
static uint32_t sConnectedAt   = 0;

static int _loadCreds(String ssids[], String passes[]) {
    sPrefs.begin(NVS_NS, true);
    bool hasAny = false;
    for (int i = 0; i < SC_MAX_NETS; i++) {
        ssids[i]  = sPrefs.getString(SSID_KEYS[i], "");
        passes[i] = sPrefs.getString(PASS_KEYS[i], "");
        if (ssids[i].length()) hasAny = true;
    }
    sPrefs.end();

    if (!hasAny && strlen(SC_WIFI_SSID) > 0) {
        ssids[0]  = SC_WIFI_SSID;
        passes[0] = SC_WIFI_PASS;
        return 1;
    }
    int n = 0;
    for (int i = 0; i < SC_MAX_NETS; i++) if (ssids[i].length()) n = i + 1;
    return n;
}

static void _syncNetworks() {
    WiFiClientSecure tls;
    tls.setCACert(ISRG_ROOT_X1);
    tls.setTimeout(8000);
    HTTPClient http;
    http.begin(tls, "ph3b3.<tailnet>.ts.net", 443, "/stackchan/networks", true);
    http.setAuthorization(SC_PH3B3_USER, SC_PH3B3_PASS);
    http.addHeader("X-Ph3b3-Device", "stackchan");
    http.setTimeout(8000);
    if (http.GET() != HTTP_CODE_OK) { http.end(); return; }
    String body = http.getString();
    http.end();

    JsonDocument doc;
    if (deserializeJson(doc, body)) return;
    JsonArray nets = doc["networks"];
    if (!nets) return;

    sPrefs.begin(NVS_NS, false);
    int count = 0;
    for (JsonObject n : nets) {
        if (count >= SC_MAX_NETS) break;
        const char* s = n["ssid"]; const char* p = n["pass"];
        if (s && *s) {
            sPrefs.putString(SSID_KEYS[count], s);
            sPrefs.putString(PASS_KEYS[count], p ? p : "");
            count++;
        }
    }
    for (int i = count; i < SC_MAX_NETS; i++) {
        sPrefs.putString(SSID_KEYS[i], "");
        sPrefs.putString(PASS_KEYS[i], "");
    }
    sPrefs.end();
    Serial.printf("[wifi] synced %d network(s) from Ph3b3\n", count);
}

static void _tryNextNetwork() {
    String ssids[SC_MAX_NETS], passes[SC_MAX_NETS];
    int n = _loadCreds(ssids, passes);
    if (n == 0) {
        Serial.println("[wifi] no creds — set SC_WIFI_SSID or sync from Ph3b3");
        return;
    }
    static int slot = 0;
    slot = (slot + 1) % n;
    Serial.printf("[wifi] trying slot %d: %s\n", slot, ssids[slot].c_str());
    WiFi.disconnect(false);
    WiFi.begin(ssids[slot].c_str(), passes[slot].c_str());
}

static void wifiSupervisorTick() {
    if (WiFi.status() == WL_CONNECTED) {
        if (!sWifiConnected) {
            sWifiConnected = true;
            sConnectedAt   = millis();
            Serial.printf("[wifi] connected: %s\n", WiFi.localIP().toString().c_str());
        }
        if (!sSyncDone && millis() - sConnectedAt > 10000) {
            sSyncDone = true;
            _syncNetworks();
        }
        return;
    }
    if (sWifiConnected) {
        sWifiConnected = false;
        sSyncDone      = false;
        sConnectedAt   = 0;
        Serial.println("[wifi] disconnected — will retry");
    }
    uint32_t now = millis();
    if (now - sLastReconnect < 15000) return;
    sLastReconnect = now;
    _tryNextNetwork();
}

// ── Globals ───────────────────────────────────────────────────────────────────
Ph3b3Face    face;
AppManager   appMgr;
bool         g_overlayOpen = false;  // set by CrescentMenu; suppresses app touch handling

static CrescentMenu crescentMenu;
static TalkApp      talkApp;
static NetworkApp   networkApp;
static KaraokeApp   karaokeApp;
static GhostApp     ghostApp;

// ── Servo constants ───────────────────────────────────────────────────────────
static const int TILT_HOME    = 450;   // 45.0° — physical center for pitch
static const int TILT_MIN     =  50;   // 5.0°  — rated floor (BSP allows 0, but 5° is spec)
static const int TILT_MAX     = 850;   // 85.0° — rated ceiling (BSP allows 900 = 90°)
// YAW_SAFE_MAX: BSP allows ±1280 (±128°). Physical build may be tighter due to cable routing.
// 700 (70°) is a conservative safe default; tune up after verifying mechanical stop on your unit.
static const int YAW_SAFE_MAX = 700;

// ── Rung 0 — lookAtNormalized safe wrapper ────────────────────────────────────
// BSP maps [-1,+1] linearly to its own angle limits: pitch 0–900 (0°–90°), yaw ±1280 (±128°).
// That overshoots rated pitch by 5° at both ends. This wrapper pre-scales inputs so
// ±1.0 arrives at exactly the rated limits (TILT_MIN–TILT_MAX for pitch, ±YAW_SAFE_MAX for yaw).
//
// Verified endpoints (TILT_MIN=50, TILT_MAX=850, BSP pitch range=900):
//   y=+1.0 → pre-scaled y=+0.889 → BSP pitch = 850 (85.0°) ✓
//   y=-1.0 → pre-scaled y=-0.889 → BSP pitch =  50 (5.0°)  ✓
//   y= 0.0 → pre-scaled y= 0.0   → BSP pitch = 450 (45.0°) ✓  (centers align)
//   x=+1.0 → pre-scaled x=+0.547 → BSP yaw   = 700 (70.0°) ✓
//   x=-1.0 → pre-scaled x=-0.547 → BSP yaw   =-700 (-70.0°) ✓
static void lookAtNormalizedSafe(float x, float y, int speed = 500) {
    constexpr float pitchScale = (float)(TILT_MAX - TILT_MIN) / 900.0f;   // 800/900 ≈ 0.889
    constexpr float yawScale   = (float)YAW_SAFE_MAX / 1280.0f;            // 700/1280 ≈ 0.547
    M5StackChan.Motion.lookAtNormalized(x * yawScale, y * pitchScale, speed);
}

// ── Rung 2 — listening orient target (settable; Beast 2 / camera swaps source) ─
// Units: decidegrees. Call setListenTarget() from vision/camera code when available.
static int _listenYaw   = 0;          // 0 = front-center
static int _listenPitch = TILT_HOME;  // 45° = level gaze

void setListenTarget(int yawDec, int pitchDec) {
    _listenYaw   = constrain(yawDec,   -YAW_SAFE_MAX, YAW_SAFE_MAX);
    _listenPitch = constrain(pitchDec, TILT_MIN,       TILT_MAX);
}

// ── Body language state ───────────────────────────────────────────────────────
static Ph3b3Face::State _lastBLState = Ph3b3Face::BOOT;
static uint32_t _scanNextMs  = 0;   // Rung 1: next idle waypoint time
static uint32_t _thinkNextMs = 0;   // Rung 3: next thinking drift time
static uint32_t _speakNextMs = 0;   // Rung 4: next speaking emphasis time

// applyBodyLanguage — fires once on state transition; sets initial pose + scan timers.
static void applyBodyLanguage(Ph3b3Face::State s) {
    if (face.isGazeLocked()) return;
    if (s == _lastBLState) return;
    _lastBLState = s;
    uint32_t now = millis();
    switch (s) {
        case Ph3b3Face::LISTENING:
            // Rung 2: stop scan, orient to speaker target (default = front-center).
            M5StackChan.Motion.moveX(_listenYaw,   350);
            M5StackChan.Motion.moveY(_listenPitch, 350);
            break;
        case Ph3b3Face::THINKING:
            // Rung 3: initial contemplative pose — slight up-right gaze, then drift.
            M5StackChan.Motion.moveX(160, 200);    // 16° off-axis
            M5StackChan.Motion.moveY(390, 180);    // 39° — soft upward look
            _thinkNextMs = now + 1800;             // let pose settle before first drift
            break;
        case Ph3b3Face::SPEAKING:
            // Rung 4: near-home for speaking; subtle life via updateBodyLanguageScan.
            M5StackChan.Motion.moveX(0, 280);
            M5StackChan.Motion.moveY(TILT_HOME, 280);
            _speakNextMs = now + 800;              // first emphasis after 800ms
            break;
        default:  // IDLE, CONNECTING, ERROR, BOOT
            // Rung 1: home on entry, then scan begins after brief grace.
            M5StackChan.Motion.moveX(0, 220);
            M5StackChan.Motion.moveY(TILT_HOME, 200);
            _scanNextMs = now + 1800;              // let home move complete before scanning
            break;
    }
}

// updateBodyLanguageScan — called every loop(); drives continuous per-state motion.
// State-machine approach: each state has its own timer and waypoint picker.
static void updateBodyLanguageScan(Ph3b3Face::State s) {
    if (face.isGazeLocked()) return;
    uint32_t now = millis();

    if (s == Ph3b3Face::IDLE || s == Ph3b3Face::CONNECTING) {
        // Rung 1 — mellow curious scan: slow pan with varied dwell + occasional tilt.
        // Range: ±35° yaw (350 dec), 42°–49° pitch (420–490 dec). Calm, unhurried.
        if (now < _scanNextMs) return;
        int yTgt = random(-350, 351);
        int pTgt = random(420, 491);
        M5StackChan.Motion.moveX(yTgt, 160);    // slow pan
        M5StackChan.Motion.moveY(pTgt, 130);    // very slow tilt
        _scanNextMs = now + 2500 + random(3000); // 2.5–5.5s dwell (not metronome)

    } else if (s == Ph3b3Face::THINKING) {
        // Rung 3 — contemplative drift: small slow movements after initial pose.
        if (now < _thinkNextMs) return;
        int yTgt = 160 + random(-100, 101);     // ±10° around the off-axis position
        int pTgt = 390 + random(-25, 36);       // 36.5°–42.5° gentle wander
        M5StackChan.Motion.moveX(yTgt, 130);
        M5StackChan.Motion.moveY(pTgt, 110);
        _thinkNextMs = now + 1200 + random(1000); // 1.2–2.2s

    } else if (s == Ph3b3Face::SPEAKING) {
        // Rung 4 — speaking emphasis: gentle pan life on phrase boundaries.
        // NOT syllable-synced — just enough motion to read as alive, not a statue.
        if (now < _speakNextMs) return;
        int yTgt = random(-200, 201);           // ±20° gentle sweep
        int pTgt = TILT_HOME + random(-25, 26); // ±2.5° subtle nod
        M5StackChan.Motion.moveX(yTgt, 210);
        M5StackChan.Motion.moveY(pTgt, 190);
        _speakNextMs = now + 900 + random(800);  // 0.9–1.7s between emphasis beats
    }
}

// ── Safe homing ───────────────────────────────────────────────────────────────
static void waitAxis(bool (*fn)()) {
    uint32_t t0 = millis();
    while (fn() && millis() - t0 < 5000) delay(10);
}

// safeHome — used on power-off path (side-button). Speed 200 is acceptable there.
static void safeHome() {
    M5StackChan.Motion.moveY(TILT_HOME, 200);
    waitAxis([]() { return M5StackChan.Motion.isYMoving(); });
    delay(200);
    M5StackChan.Motion.moveX(0, 200);
    waitAxis([]() { return M5StackChan.Motion.isXMoving(); });
}

// gentleHome — boot-only homing sequence. Servo::init() leaves torque disabled;
// this re-enables it explicitly and eases to neutral over ~1.5s so the first
// visible motion is a glide, not a snap.
// speed=50 → spring stiffness≈11.6 (critically damped) → 98% settle ≈ 1.5s.
// Tilt first (heavier axis, gravity bias), then pan.
static void gentleHome() {
    M5StackChan.Motion.setAutoAngleSyncEnabled(true);  // spring starts from physical pos
    M5StackChan.Motion.setTorqueEnabled(true);         // re-engage motor output
    M5StackChan.Motion.moveY(TILT_HOME, 50);
    waitAxis([]() { return M5StackChan.Motion.isYMoving(); });
    delay(100);
    M5StackChan.Motion.moveX(0, 50);
    waitAxis([]() { return M5StackChan.Motion.isXMoving(); });
}

// ── setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("[rung4] boot");

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

    gentleHome();
    randomSeed(micros());   // vary scan waypoints across boots
    Serial.println("[rung4] homed");

    // WiFi — blocking connect up to 12 s on first boot cred
    WiFi.mode(WIFI_STA);
    String ssids[SC_MAX_NETS], passes[SC_MAX_NETS];
    int n = _loadCreds(ssids, passes);
    if (n > 0) {
        d.drawString("connecting wifi...", d.width() / 2, d.height() / 2 + 32);
        WiFi.begin(ssids[0].c_str(), passes[0].c_str());
        for (int i = 0; i < 120 && WiFi.status() != WL_CONNECTED; i++) delay(100);
        if (WiFi.status() == WL_CONNECTED) {
            sWifiConnected = true;
            sConnectedAt   = millis();
            Serial.printf("[wifi] connected: %s\n", WiFi.localIP().toString().c_str());
        } else {
            Serial.println("[wifi] not connected at boot — will retry in loop");
        }
    } else {
        Serial.println("[wifi] no creds — define SC_WIFI_SSID");
    }

    face.begin();
    face.setStatusVisible(false);   // face-only mode: state via expression, no text
    face.setCrescentTabVisible(true);  // corner crescent is the only control affordance

    appMgr.registerApp(&talkApp);     // 0
    appMgr.registerApp(&networkApp);  // 1
    appMgr.registerApp(&karaokeApp);  // 2
    appMgr.registerApp(&ghostApp);    // 3

    appMgr.begin(0);  // boot into Talk
    Serial.println("[rung4] setup done");
}

// ── loop ──────────────────────────────────────────────────────────────────────
void loop() {
    M5StackChan.update();

    // Side-button deliberate hold → safe-home servos then PMIC power-off.
    // Power = 1000ms deliberate hold (AXP2101 hardware floor, register 0x27 bits[3:2]=0b00).
    // Intentional: prevents accidental power-off on the demo body. Tap does not trigger power.
    // AXP2101 mapping: wasHold() = long press (>=1s fired while held); wasClicked() = short tap (<1s, on release).
    if (M5.BtnPWR.wasHold()) {
        safeHome();
        M5.Power.powerOff();
    }

    wifiSupervisorTick();

    crescentMenu.update();  // updates g_overlayOpen + handles mode-switch taps
    appMgr.update();        // app logic (checks g_overlayOpen before processing touches)
    face.update();          // renders face + crescent tab onto canvas, pushes to display
    appMgr.draw();          // app overlays (e.g. karaoke lyrics)
    crescentMenu.draw();    // mode panel slides over everything when open

    applyBodyLanguage(face.getState());
    updateBodyLanguageScan(face.getState());

    // Servo gaze consumer — fires one command on lock/unlock edge; same target as pupils.
    // Uses safe wrapper so ±1.0 stays within rated servo travel.
    {
        static bool sPrevGazeLocked = false;
        bool gazeLocked = face.isGazeLocked();
        if (gazeLocked && !sPrevGazeLocked)
            lookAtNormalizedSafe(face.getGazeYaw(), face.getGazePitch(), 300);
        else if (!gazeLocked && sPrevGazeLocked)
            M5StackChan.Motion.goHome(300);
        sPrevGazeLocked = gazeLocked;
    }

    delay(16);
}
