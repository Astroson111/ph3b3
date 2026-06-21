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
 * Return to menu: hold top-left 60×60 px corner for 1 s from any mode.
 *
 * SD card layout (microSD, CS=GPIO4):
 *   /karaoke/track.wav  /karaoke/track.lrc  /ghost/ev_*.log
 */

// ── First-boot WiFi (blank after NVS is seeded) ───────────────────────────────
#define SC_WIFI_SSID  ""
#define SC_WIFI_PASS  ""

// #define SC_FACE_BGR   // uncomment if eyes come up orange

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>

#include "ph3b3_face.h"
#include "AppBase.h"
#include "AppManager.h"
#include "MenuApp.h"
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
    http.setAuthorization("REDACTED", "REDACTED");
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
Ph3b3Face  face;
AppManager appMgr;

static MenuApp    menuApp;
static TalkApp    talkApp;
static NetworkApp networkApp;
static KaraokeApp karaokeApp;
static GhostApp   ghostApp;

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
            M5StackChan.Motion.moveY(TILT_HOME, 200);
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

    safeHome();
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

    appMgr.registerApp(&menuApp);     // 0
    appMgr.registerApp(&talkApp);     // 1
    appMgr.registerApp(&networkApp);  // 2
    appMgr.registerApp(&karaokeApp);  // 3
    appMgr.registerApp(&ghostApp);    // 4

    appMgr.begin(1);  // boot into Talk — menu accessible via hold-gesture
    Serial.println("[rung4] setup done");
}

// ── loop ──────────────────────────────────────────────────────────────────────
void loop() {
    M5StackChan.update();
    wifiSupervisorTick();

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
