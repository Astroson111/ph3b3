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
#include <DNSServer.h>
#include <WebServer.h>

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

// ── Server target — ATOMIC NVS record (host+port+user+pass as ONE unit) ───────
// Compile-time SC_PH3B3_* are the first-boot SEED only; runtime always reads NVS.
// Host and port are never stored or edited separately (Iris split-config lesson).
String gSrvHost; int gSrvPort = 0; String gSrvUser; String gSrvPass;
static const char SRV_HOST_KEY[] = "srv_host";
static const char SRV_PORT_KEY[] = "srv_port";
static const char SRV_USER_KEY[] = "srv_user";
static const char SRV_PASS_KEY[] = "srv_pass";

static void _saveServer(const String& h, int p, const String& u, const String& pw) {
    // One transaction — all four fields together, never a partial record.
    sPrefs.begin(NVS_NS, false);
    sPrefs.putString(SRV_HOST_KEY, h);
    sPrefs.putInt   (SRV_PORT_KEY, p);
    sPrefs.putString(SRV_USER_KEY, u);
    sPrefs.putString(SRV_PASS_KEY, pw);
    sPrefs.end();
    gSrvHost = h; gSrvPort = p; gSrvUser = u; gSrvPass = pw;
}

static void _loadServer() {
    sPrefs.begin(NVS_NS, true);
    bool seeded = sPrefs.isKey(SRV_HOST_KEY);
    gSrvHost = sPrefs.getString(SRV_HOST_KEY, SC_PH3B3_HOST);
    gSrvPort = sPrefs.getInt   (SRV_PORT_KEY, SC_PH3B3_PORT);
    gSrvUser = sPrefs.getString(SRV_USER_KEY, SC_PH3B3_USER);
    gSrvPass = sPrefs.getString(SRV_PASS_KEY, SC_PH3B3_PASS);
    sPrefs.end();
    if (!seeded) _saveServer(SC_PH3B3_HOST, SC_PH3B3_PORT, SC_PH3B3_USER, SC_PH3B3_PASS);
    Serial.printf("[srv] target %s:%d\n", gSrvHost.c_str(), gSrvPort);
}

// GET /health against the runtime record. Returns the HTTP code, or a negative
// value on a connection-level failure (no route / TLS / timeout). 2xx = online.
static int _healthCheck() {
    WiFiClientSecure tls;
    tls.setInsecure();               // LAN mkcert self-signed cert
    tls.setTimeout(8000);
    HTTPClient http;
    if (!http.begin(tls, gSrvHost.c_str(), gSrvPort, "/health", true)) return -1000;
    http.setAuthorization(gSrvUser.c_str(), gSrvPass.c_str());
    http.addHeader("X-Ph3b3-Device", "stackchan");
    http.setTimeout(8000);
    int code = http.GET();
    http.end();
    return code;                     // 2xx online; 401/403 denied; <0 no route
}

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
    tls.setInsecure();               // LAN mkcert self-signed cert (Iris lesson)
    tls.setTimeout(8000);
    HTTPClient http;
    http.begin(tls, gSrvHost.c_str(), gSrvPort, "/stackchan/networks", true);
    http.setAuthorization(gSrvUser.c_str(), gSrvPass.c_str());
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

// Captive portal: raised when no creds exist or join keeps failing.
// Starts softAP "Dio-Setup", serves a one-shot SSID/pass form, writes slot0 in
// NVS "sc" on /save, then reboots.  After reboot _loadCreds() finds slot0 and
// joins normally; _syncNetworks() pulls the rest from Ph3b3.
// This function never returns — portal runs until ESP.restart().
static void _runPortal() {
    Serial.println("[wifi] portal — Dio-Setup 192.168.4.1");
    face.setState(Ph3b3Face::CONNECTING);

    WiFi.mode(WIFI_OFF);
    delay(200);
    WiFi.mode(WIFI_AP);
    WiFi.softAP("Dio-Setup");
    delay(200);

    DNSServer dns;
    dns.start(53, "*", IPAddress(192, 168, 4, 1));

    WebServer server(80);

    server.on("/", HTTP_GET, [&]() {
        server.send(200, "text/html",
            "<!DOCTYPE html><html><head>"
            "<meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Dio Setup</title>"
            "<style>"
            "body{font-family:sans-serif;background:#0a0318;color:#e0d4ff;"
                 "max-width:480px;margin:0 auto;padding:1rem}"
            "h1{color:#a855f7}"
            "p{color:#a09ab8;font-size:.85rem}"
            "label{font-size:.8rem;color:#a09ab8;display:block;margin-top:.8rem}"
            "input{width:100%;box-sizing:border-box;background:#0d0525;"
                  "border:1px solid #4b2c8a;border-radius:4px;color:#e0d4ff;"
                  "padding:.4rem .5rem;font-size:.95rem;margin-top:2px}"
            "button{width:100%;margin-top:1.2rem;padding:.75rem;background:#7e22ce;"
                   "border:none;border-radius:8px;color:#fff;font-size:1rem;"
                   "font-weight:700;cursor:pointer}"
            "button:hover{background:#9333ea}"
            "</style></head><body>"
            "<h1>Dio Setup</h1>"
            "<p>Enter your WiFi credentials. "
            "Additional networks sync from Ph3b3 after first connect.</p>"
            "<form method='POST' action='/save'>"
            "<label>SSID</label>"
            "<input name='ssid' autocomplete='off' autofocus>"
            "<label>Password</label>"
            "<input name='pass' type='password'>"
            "<label>Ph3b3 host</label>"
            "<input name='host' value='" + gSrvHost + "'>"
            "<label>Ph3b3 port</label>"
            "<input name='port' value='" + String(gSrvPort) + "'>"
            "<button type='submit'>Save &amp; Reboot</button>"
            "</form>"
            "<div style='position:fixed;bottom:12px;right:12px;width:110px;opacity:0.75'>"
            "<svg width='100%' viewBox='0 0 680 460' role='img' xmlns='http://www.w3.org/2000/svg'>"
            "<title>Peach, a golden retriever, sleeping in a little bed</title>"
            "<desc>A line-art golden retriever curled up asleep in a small cushioned bed, "
            "with a crescent moon and small stars above, drawn in a soft monochrome style "
            "to match the Ph3b3 crescent art.</desc>"
            "<style>"
            ".ink{fill:none;stroke:#2b2b2b;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}"
            ".ink-soft{fill:none;stroke:#6b6b6b;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}"
            ".fur{fill:#e8a85c;opacity:0.22}"
            ".bed{fill:#6b6b6b;opacity:0.10}"
            ".cap{fill:#6b6b6b;font-family:Georgia,serif;font-size:15px;font-style:italic}"
            "</style>"
            "<circle cx='500' cy='95' r='34' fill='none' stroke='#6b6b6b' stroke-width='1.5'/>"
            "<circle cx='512' cy='88' r='34' fill='#ffffff' stroke='none'/>"
            "<circle cx='512' cy='88' r='34' fill='#6b6b6b' opacity='0.10'/>"
            "<path d='M180 150 l3 7 l7 1 l-5 5 l1 7 l-6 -3 l-6 3 l1 -7 l-5 -5 l7 -1 z' fill='#9b9b9b'/>"
            "<path d='M250 110 l2 5 l5 1 l-4 3 l1 5 l-4 -2 l-4 2 l1 -5 l-4 -3 l5 -1 z' fill='#9b9b9b'/>"
            "<path d='M560 175 l2 5 l5 1 l-4 3 l1 5 l-4 -2 l-4 2 l1 -5 l-4 -3 l5 -1 z' fill='#9b9b9b'/>"
            "<ellipse cx='340' cy='370' rx='210' ry='50' class='bed'/>"
            "<path class='ink-soft' d='M140 360 q-8 -34 30 -42 q170 -22 340 0 q38 8 30 42 q-6 30 -50 36 q-150 18 -300 0 q-44 -6 -50 -36 z'/>"
            "<path class='ink-soft' d='M150 358 q180 24 380 0'/>"
            "<path class='fur' d='M250 290 q-70 10 -78 56 q-6 40 60 50 q120 16 230 -4 q70 -14 56 -64 q-14 -44 -90 -48 q-24 24 -64 22 q-46 -2 -54 -28 q-8 6 -16 8 z'/>"
            "<path class='ink' d='M250 292 q-66 12 -74 54 q-6 38 58 48 q116 16 224 -4 q66 -14 54 -60 q-14 -42 -86 -46'/>"
            "<path class='ink' d='M250 292 q12 -22 44 -22 q34 0 42 26'/>"
            "<path class='ink' d='M336 296 q12 18 52 16 q44 -2 56 -24'/>"
            "<path class='ink' d='M444 288 q42 -36 72 -20 q22 12 6 40 q-12 22 -42 28'/>"
            "<path class='ink-soft' d='M470 282 q24 -14 40 -4'/>"
            "<path class='ink' d='M250 292 q-30 -16 -34 -44 q-2 -20 16 -26 q20 -6 30 14'/>"
            "<path class='ink' d='M232 222 q-14 -4 -20 8 q-6 14 8 24'/>"
            "<circle cx='244' cy='258' r='2.5' fill='#2b2b2b'/>"
            "<path class='ink-soft' d='M236 256 q8 -5 16 0'/>"
            "<path class='ink' d='M258 272 q8 6 18 2'/>"
            "<path class='ink' d='M266 268 q2 6 -2 10'/>"
            "<circle cx='270' cy='276' r='3' fill='#2b2b2b'/>"
            "<path class='ink-soft' d='M300 330 q40 10 90 4'/>"
            "<path class='ink-soft' d='M330 360 q30 6 70 0'/>"
            "<path class='ink-soft' d='M540 250 q10 -10 0 -20 q-10 -10 0 -20' opacity='0.7'/>"
            "<path class='ink-soft' d='M556 236 q8 -8 0 -16 q-8 -8 0 -16' opacity='0.5'/>"
            "<text x='340' y='432' text-anchor='middle' class='cap'>Peach &mdash; rest easy, good girl</text>"
            "</svg></div>"
            "</body></html>"
        );
    });

    server.onNotFound([&]() {
        server.sendHeader("Location", "http://192.168.4.1/", true);
        server.send(302, "text/plain", "");
    });

    server.on("/save", HTTP_POST, [&]() {
        String ssid = server.arg("ssid"); ssid.trim();
        String pass = server.arg("pass"); pass.trim();
        String host = server.arg("host"); host.trim();
        int    port = server.arg("port").toInt();
        if (ssid.length() > 0) {
            sPrefs.begin(NVS_NS, false);
            sPrefs.putString(SSID_KEYS[0], ssid);
            sPrefs.putString(PASS_KEYS[0], pass);
            sPrefs.end();
            // Server target stays ATOMIC: only overwrite when BOTH host and port
            // are present. Auth is never entered on the open setup AP.
            if (host.length() > 0 && port > 0) _saveServer(host, port, gSrvUser, gSrvPass);
            server.send(200, "text/html",
                "<html><body style='font-family:sans-serif;background:#0a0318;"
                "color:#e0d4ff;text-align:center;padding:2rem'>"
                "<h2 style='color:#a855f7'>Saved!</h2>"
                "<p>Rebooting Dio...</p>"
                "</body></html>"
            );
            delay(1000);
            ESP.restart();
        } else {
            server.send(400, "text/plain", "SSID required");
        }
    });

    server.begin();

    while (true) {
        M5StackChan.update();
        dns.processNextRequest();
        server.handleClient();
        face.update();
        delay(5);
    }
}

static void wifiSupervisorTick() {
    static int sFailCount = 0;

    if (WiFi.status() == WL_CONNECTED) {
        if (!sWifiConnected) {
            sWifiConnected = true;
            sConnectedAt   = millis();
            sFailCount     = 0;
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
    // After 16 consecutive ticks (~4 min) without connecting, raise portal.
    // Resets to 0 on any successful connect.
    if (++sFailCount >= 16) { sFailCount = 0; _runPortal(); }
}

// ── Globals ───────────────────────────────────────────────────────────────────
Ph3b3Face    face;
AppManager   appMgr;
bool         g_overlayOpen   = false;  // set by CrescentMenu; suppresses app touch handling
bool         g_crescentTapped = false;  // set by CrescentMenu on crescent tap; consumed by active app

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

    // Init face before WiFi so _runPortal() can animate while waiting for creds.
    face.begin();
    face.setStatusVisible(false);   // face-only mode: state via expression, no text
    face.setCrescentTabVisible(true);  // corner crescent is the only control affordance

    // WiFi — blocking connect up to 12 s on first boot cred
    WiFi.mode(WIFI_STA);
    String ssids[SC_MAX_NETS], passes[SC_MAX_NETS];
    // One-time NVS wipe: clears stale creds written before the captive portal existed.
    // Flag "wiped_v1" in the same namespace prevents this from ever running again.
    {
        sPrefs.begin(NVS_NS, false);
        if (!sPrefs.getBool("wiped_v1", false)) {
            sPrefs.clear();
            sPrefs.putBool("wiped_v1", true);
            Serial.println("[wifi] one-time NVS wipe done");
        }
        sPrefs.end();
    }

    _loadServer();   // atomic server record — seeds NVS on first boot, else reads it
    face.setStatusVisible(true);
    face.setStatusLine(gSrvHost + ":" + String(gSrvPort));   // TARGET LINE — no blind config

    int n = _loadCreds(ssids, passes);
    Serial.printf("[wifi] _loadCreds → n=%d\n", n);
    if (n > 0) {
        d.drawString("connecting wifi...", d.width() / 2, d.height() / 2 + 32);
        WiFi.begin(ssids[0].c_str(), passes[0].c_str());
        for (int i = 0; i < 120 && WiFi.status() != WL_CONNECTED; i++) delay(100);
        if (WiFi.status() == WL_CONNECTED) {
            sWifiConnected = true;
            sConnectedAt   = millis();
            Serial.printf("[wifi] connected: %s\n", WiFi.localIP().toString().c_str());
            // Boot health probe → cause-differentiated status + target (Iris lesson)
            int hc = _healthCheck();
            String tgt = gSrvHost + ":" + String(gSrvPort);
            String st = (hc >= 200 && hc < 300) ? ("online "   + tgt)
                      : (hc == 401 || hc == 403) ? ("denied "   + tgt)
                      : (hc < 0)                  ? ("no route " + tgt)
                      :                             ("away "     + tgt);
            face.setStatusLine(st);
            Serial.printf("[srv] health=%d -> %s\n", hc, st.c_str());
        } else {
            Serial.println("[wifi] not connected at boot — will retry in loop");
        }
    } else {
        _runPortal();  // blocks until /save → ESP.restart()
    }

    appMgr.registerApp(&talkApp);     // 0
    appMgr.registerApp(&networkApp);  // 1
    appMgr.registerApp(&karaokeApp);  // 2
    // appMgr.registerApp(&ghostApp);    // 3 — UNREGISTERED: a stray top-left crescent-tap trapped her in Ghost (FOCUSED/frown) with no voice; Ghost is a Rung-3 stub, so drop it from the menu

    appMgr.begin(0);  // boot into Talk
    Serial.println("[rung4] setup done");
}

// LISTENING attention cue — the 12 base LEDs breathe PURPLE while she records,
// so you can tell at 2 m when to talk. LED-only: reads face.getState() (never
// touches servo/VAD/mic/PTT/state-machine). Reserved color contract: LISTENING =
// purple; Si12T head-pat = PINK — the two must never read as the same colour.
static void _listenLeds() {
    static bool     wasListening = false;
    static uint32_t lastMs       = 0;
    bool listening = (face.getState() == Ph3b3Face::LISTENING);
    if (listening) {
        if (millis() - lastMs >= 40) {            // ~25 fps breathe
            lastMs = millis();
            float b = 0.6f + 0.4f * (0.5f + 0.5f * sinf(millis() / 300.0f));
            uint8_t r = (uint8_t)(140 * b), g = (uint8_t)(20 * b), bl = (uint8_t)(255 * b);
            for (int i = 0; i < 12; i++) M5StackChan.setRgbColor(i, r, g, bl);
            M5StackChan.refreshRgb();
        }
    } else if (wasListening) {                     // edge: clear once on exit
        for (int i = 0; i < 12; i++) M5StackChan.setRgbColor(i, 0, 0, 0);
        M5StackChan.refreshRgb();
    }
    wasListening = listening;
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
    _listenLeds();          // purple attention LEDs while LISTENING (LED-only, no servo)
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
