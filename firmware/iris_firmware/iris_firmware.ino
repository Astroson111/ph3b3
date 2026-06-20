// iris_firmware.ino — Rung A+: factory reset + repeatable onboarding
// Iris — M5StickS3 voice combadge.
// Adds over the connectivity rung: boot BtnB hold → factory reset countdown,
// menu "Forget WiFi" (timed confirm → NVS wipe), portal /rescan route.
// Core /chat round-trip and Ph3b3Face engine unchanged.
//
// Build:
//   arduino-cli compile --fqbn m5stack:esp32:m5stack_sticks3 iris_firmware/
//   arduino-cli upload  --fqbn m5stack:esp32:m5stack_sticks3 -p /dev/ttyACM0 iris_firmware/
//   arduino-cli monitor -p /dev/ttyACM0 -c baudrate=115200

#include <M5Unified.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <DNSServer.h>
#include <WebServer.h>
#include "ph3b3_face.h"

// ----------------------------------------------------------------------------
// CONFIG
// Dev bench fallback — uncomment when NVS is empty and you need a quick test:
// #define LAB_SSID "YOUR_SSID"
// #define LAB_PASS "YOUR_PASS"

const char*    PH3B3_HOST = "ph3b3.<tailnet>.ts.net";
const uint16_t PH3B3_PORT = 443;
const char*    PH3B3_CHAT = "/chat";
const char* PH3B3_USER = "ph3b3-user";
const char* PH3B3_PASS = "ph3b3-pass";
const char*    DEVICE_HDR = "iris";
String         SESSION_ID = "iris-session";

// ISRG Root X1 — Let's Encrypt root CA; Tailscale Funnel certs chain to this.
// SHA-256: 96:bc:ec:06:26:49:76:f3:74:60:77:9a:cf:28:c5:a7:cf:e8:a3:c0:aa:e1:1a:8f:fc:ee:05:c0:bd:df:08:c6
// Valid until 2035-06-04. Source: certifi 2025.x (extracted and fingerprint-verified).
static const char ISRG_ROOT_X1[] = R"EOF(
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
)EOF";

// ----------------------------------------------------------------------------
// Globals
Ph3b3Face  face;
Preferences prefs;
DNSServer  dns;
WebServer  httpServer(80);

enum UiMode { FACE, MENU, WIFI_SETUP, INFO };
UiMode uiMode   = FACE;
int    menuSel  = 0;
bool   menuDirty     = true;
bool   wifiSetupDirty = true;

const char* MENU_ITEMS[] = { "WiFi Setup", "Reconnect", "Forget WiFi", "Info", "Back" };
const int   MENU_COUNT   = 5;

bool     wifiWasConnected = false;
uint32_t lastReconnectMs  = 0;
const uint32_t RECONNECT_INTERVAL = 5000;

String cachedScan = "";
String portalMsg  = "";

// BtnB hold detection — manual timing avoids M5Unified API ambiguity
uint32_t btnBPressedAt = 0;
bool     btnBLongFired  = false;

// ----------------------------------------------------------------------------
// NVS helpers
// ----------------------------------------------------------------------------
bool loadCreds(String& ssid, String& pass) {
  prefs.begin("iris", true);
  ssid = prefs.getString("ssid", "");
  pass = prefs.getString("pass", "");
  prefs.end();
  return ssid.length() > 0;
}

void saveCreds(const String& ssid, const String& pass) {
  prefs.begin("iris", false);
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.end();
}

// ----------------------------------------------------------------------------
// WiFi supervisor — non-blocking, called every FACE-mode loop tick
// ----------------------------------------------------------------------------
void supervisorTick() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiWasConnected) {
      wifiWasConnected = true;
      face.setState(Ph3b3Face::IDLE);
      face.setStatusLine(WiFi.localIP().toString());
    }
    return;
  }
  if (wifiWasConnected) {
    wifiWasConnected = false;
    face.setState(Ph3b3Face::ERROR);
    face.setStatusLine("offline");
  }
  uint32_t now = millis();
  if (now - lastReconnectMs < RECONNECT_INTERVAL) return;
  lastReconnectMs = now;
  String ssid, pass;
  if (!loadCreds(ssid, pass)) return;
  WiFi.disconnect();
  WiFi.begin(ssid.c_str(), pass.c_str());
}

// ----------------------------------------------------------------------------
// POST /chat (unchanged from face-engine rung)
// ----------------------------------------------------------------------------
String ph3b3Chat(const String& message) {
  WiFiClientSecure tls;
  tls.setCACert(ISRG_ROOT_X1);   // pinned: Funnel certs chain to ISRG Root X1

  HTTPClient http;
  if (!http.begin(tls, PH3B3_HOST, PH3B3_PORT, PH3B3_CHAT, true))
    return String("ERR: begin failed");

  // http.setTimeout() only sets the HTTPClient's own elapsed-time check; it does NOT
  // update NetworkClientSecure::_timeout, which controls SO_RCVTIMEO on the socket.
  // SO_RCVTIMEO is set from the _connectTimeout passed to connect() and defaults to
  // 5 s — exactly the Ph3b3 LLM+TTS round-trip time, causing intermittent timeouts.
  // setConnectTimeout() updates _connectTimeout so connect() sets _timeout = 30 s,
  // making SO_RCVTIMEO 30 s; available() then blocks long enough for the response.
  http.setConnectTimeout(30000);  // SO_RCVTIMEO = 30 s (Ph3b3 responds in ~5-6 s)
  http.setTimeout(60000);         // HTTPClient idle-data guard = 60 s
  http.setAuthorization(PH3B3_USER, PH3B3_PASS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Ph3b3-Device", DEVICE_HDR);

  JsonDocument body;
  body["message"]    = message;
  body["session_id"] = SESSION_ID;
  String payload;
  serializeJson(body, payload);

  int code = http.POST(payload);
  if (code != HTTP_CODE_OK) {
    http.end();
    return "HTTP " + String(code);
  }

  // Read the first 6 KB of the body via readBytes() — blocking I/O with
  // Stream::_timeout and SO_RCVTIMEO both set above. "response" always
  // precedes the 171 KB base64 "audio" field so 6 KB captures it fully.
  static const int PEEK_MAX = 6144;
  static char peek[PEEK_MAX + 1];
  WiFiClient* raw = http.getStreamPtr();
  int peekLen = raw->readBytes(peek, PEEK_MAX);
  peek[peekLen] = '\0';
  http.end();

  JsonDocument filter;
  filter["response"] = true;
  JsonDocument doc;
  deserializeJson(doc, peek, peekLen, DeserializationOption::Filter(filter));

  const char* resp = doc["response"];
  if (resp && *resp) return String(resp);
  return "(no response)";
}

// ----------------------------------------------------------------------------
// Captive portal
// ----------------------------------------------------------------------------
void doScan() {
  // WIFI_AP_STA mode is active at this point; STA radio can scan
  int n = WiFi.scanNetworks();
  cachedScan = "<select name='ssid'>";
  if (n <= 0) {
    cachedScan += "<option>No networks found</option>";
  } else {
    for (int i = 0; i < n; i++) {
      String s = WiFi.SSID(i);
      cachedScan += "<option value='" + s + "'>" +
                    s + " (" + String(WiFi.RSSI(i)) + " dBm)</option>";
    }
  }
  cachedScan += "</select>";
  WiFi.scanDelete();
}

String buildPortalPage() {
  String html;
  html.reserve(1400);
  html = "<!DOCTYPE html><html><head>"
         "<meta charset='utf-8'>"
         "<meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>Iris Setup</title>"
         "<style>"
         "body{background:#000;color:#0ff;font-family:monospace;padding:20px;max-width:400px}"
         "h2{color:#0ff;margin:0 0 12px}"
         "select,input{background:#111;color:#0ff;border:1px solid #0ff;"
         "padding:8px;width:100%;margin:6px 0;box-sizing:border-box;font-family:monospace}"
         "button{background:#0ff;color:#000;border:none;padding:12px;"
         "width:100%;margin-top:10px;font-family:monospace;font-weight:bold;cursor:pointer}"
         ".ok{color:#0f0;margin-top:10px}.err{color:#f55;margin-top:10px}"
         "</style></head><body>"
         "<h2>IRIS SETUP</h2>"
         "<form method='POST' action='/connect'>";
  html += cachedScan;
  html += "<input type='password' name='pass' placeholder='password' autocomplete='off'>";
  // NOTE: portal creds sent over local AP in cleartext
  html += "<button type='submit'>CONNECT</button></form>";
  html += "<a href='/rescan' style='color:#0ff;font-family:monospace;"
          "display:block;margin-top:14px;text-align:center'>&#8635; Rescan networks</a>";
  html += portalMsg;
  html += "</body></html>";
  return html;
}

void handlePortalRoot() {
  httpServer.send(200, "text/html", buildPortalPage());
}

void handlePortalConnect() {
  if (!httpServer.hasArg("ssid") || !httpServer.hasArg("pass")) {
    httpServer.send(400, "text/plain", "missing args");
    return;
  }
  String ssid = httpServer.arg("ssid");
  String pass = httpServer.arg("pass");

  // Attempt STA join while AP stays up
  WiFi.begin(ssid.c_str(), pass.c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    dns.processNextRequest();
    httpServer.handleClient();
    delay(100);
  }

  if (WiFi.status() == WL_CONNECTED) {
    saveCreds(ssid, pass);
    portalMsg = "<p class='ok'>Connected! Iris is online.</p>";
    httpServer.send(200, "text/html", buildPortalPage());
    delay(1500);
    httpServer.stop();
    dns.stop();
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    wifiWasConnected = true;
    face.setState(Ph3b3Face::IDLE);
    face.setStatusLine(WiFi.localIP().toString());
    uiMode = FACE;
  } else {
    // Stay in AP, show error on portal and on device
    WiFi.disconnect();
    portalMsg = "<p class='err'>Failed to connect to " + ssid + ". Check password.</p>";
    httpServer.send(200, "text/html", buildPortalPage());
    wifiSetupDirty = true;   // re-draw device screen with hint
  }
}

void startPortal() {
  uiMode = WIFI_SETUP;
  wifiSetupDirty = true;
  WiFi.mode(WIFI_AP_STA);          // AP_STA so STA radio can scan while AP runs
  WiFi.softAP("Iris-Setup");
  IPAddress apIP(192, 168, 4, 1);
  dns.start(53, "*", apIP);        // wildcard DNS → captive portal
  doScan();
  portalMsg = "";
  httpServer.on("/",        HTTP_GET,  handlePortalRoot);
  httpServer.on("/connect", HTTP_POST, handlePortalConnect);
  httpServer.on("/rescan",  HTTP_GET,  []() {
    doScan();
    httpServer.sendHeader("Location", "/");
    httpServer.send(302, "text/plain", "");
  });
  httpServer.onNotFound([]() {
    httpServer.sendHeader("Location", "http://192.168.4.1/");
    httpServer.send(302, "text/plain", "");
  });
  httpServer.begin();
}

// ----------------------------------------------------------------------------
// Boot-time WiFi connect (blocking — setup() only)
// ----------------------------------------------------------------------------
void connectWiFi() {
  String ssid, pass;

#ifdef LAB_SSID
  ssid = LAB_SSID;
  pass = LAB_PASS;
#else
  if (!loadCreds(ssid, pass)) {
    startPortal();
    return;
  }
#endif

  face.setState(Ph3b3Face::CONNECTING);
  face.setStatusLine("joining...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid.c_str(), pass.c_str());

  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    face.update();
    delay(50);
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiWasConnected = true;
    face.setState(Ph3b3Face::IDLE);
    face.setStatusLine(WiFi.localIP().toString());
  } else {
    face.setState(Ph3b3Face::ERROR);
    face.setStatusLine("wifi failed");
    delay(800);
    startPortal();
  }
}

// ----------------------------------------------------------------------------
// Display renderers (face paused in all non-FACE modes)
// ----------------------------------------------------------------------------
void drawMenu() {
  if (!menuDirty) return;
  menuDirty = false;
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(4, 4);
  M5.Display.println("-- MENU --");
  // 5 items, spacing 22px (textSize 2 = 16px tall, 6px gap)
  for (int i = 0; i < MENU_COUNT; i++) {
    M5.Display.setCursor(0, 26 + i * 22);
    if (i == menuSel) {
      M5.Display.setTextColor(TFT_BLACK, TFT_CYAN);
    } else {
      M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
    }
    M5.Display.print(" ");
    M5.Display.print(MENU_ITEMS[i]);
    M5.Display.println("     ");   // trailing spaces clear highlight tail
  }
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_DARKGREY, TFT_BLACK);
  M5.Display.setCursor(4, 148);
  M5.Display.println("B:next  hold B:pick");
}

void drawWifiSetup() {
  if (!wifiSetupDirty) return;
  wifiSetupDirty = false;
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(4, 10);
  M5.Display.println("IRIS SETUP");
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setCursor(4, 46);
  M5.Display.println("1. Join this wifi:");
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(4, 62);
  M5.Display.println("Iris-Setup");
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setCursor(4, 90);
  M5.Display.println("2. Open browser:");
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(4, 106);
  M5.Display.println("192.168.4.1");
}

void drawInfo() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(4, 6);
  M5.Display.println("-- INFO --");
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setCursor(4, 38);
  M5.Display.print("IP:   ");
  M5.Display.println(WiFi.status() == WL_CONNECTED
                     ? WiFi.localIP().toString() : "offline");
  M5.Display.setCursor(4, 54);
  M5.Display.print("WiFi: ");
  M5.Display.println(WiFi.status() == WL_CONNECTED ? "connected" : "offline");
  M5.Display.setCursor(4, 70);
  M5.Display.print("Host: ");
  M5.Display.println(PH3B3_HOST);
  M5.Display.setTextColor(TFT_DARKGREY, TFT_BLACK);
  M5.Display.setCursor(4, 100);
  M5.Display.println("B: back to menu");
}

// ----------------------------------------------------------------------------
// Menu activation
// ----------------------------------------------------------------------------
void activateMenuItem() {
  switch (menuSel) {
    case 0:  // WiFi Setup
      startPortal();
      break;

    case 1:  // Reconnect
      {
        String ssid, pass;
        if (loadCreds(ssid, pass)) {
          WiFi.disconnect();
          WiFi.mode(WIFI_STA);
          WiFi.begin(ssid.c_str(), pass.c_str());
          wifiWasConnected = false;
          lastReconnectMs = millis();
          face.setState(Ph3b3Face::CONNECTING);
        } else {
          startPortal();
          break;
        }
        uiMode = FACE;
      }
      break;

    case 2:  // Forget WiFi — must stay held for 1.5s to confirm
      {
        M5.Display.fillScreen(TFT_BLACK);
        M5.Display.setTextSize(2);
        M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
        M5.Display.setCursor(4, 14);
        M5.Display.println("FORGET");
        M5.Display.println("WiFi?");
        M5.Display.setTextSize(1);
        M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
        M5.Display.setCursor(4, 66);
        M5.Display.println("Keep holding BtnB");
        M5.Display.setCursor(4, 82);
        M5.Display.println("to wipe and restart.");
        M5.Display.setCursor(4, 98);
        M5.Display.setTextColor(TFT_DARKGREY, TFT_BLACK);
        M5.Display.println("Release = cancel.");
        uint32_t t0 = millis();
        bool confirmed = true;
        while (millis() - t0 < 1500) {
          M5.update();
          if (!M5.BtnB.isPressed()) { confirmed = false; break; }
          delay(30);
        }
        if (confirmed) factoryReset();   // never returns — wipes + restarts
        // Released before timeout: return to menu, creds intact
      }
      break;

    case 3:  // Info
      drawInfo();
      uiMode = INFO;
      break;

    case 4:  // Back
      uiMode = FACE;
      break;
  }
  menuSel   = 0;
  menuDirty = true;
}

// ----------------------------------------------------------------------------
// BtnB handler — all menu navigation lives here
// ----------------------------------------------------------------------------
void handleBtnB() {
  if (M5.BtnB.wasPressed()) {
    btnBPressedAt = millis();
    btnBLongFired  = false;
  }

  // Long press threshold: 600 ms — activate selected item
  if (M5.BtnB.isPressed() && !btnBLongFired &&
      millis() - btnBPressedAt > 600) {
    btnBLongFired = true;
    if (uiMode == MENU) activateMenuItem();
  }

  // Short release (not a long press) — navigate
  if (M5.BtnB.wasReleased() && !btnBLongFired) {
    if (uiMode == FACE) {
      uiMode    = MENU;
      menuSel   = 0;
      menuDirty = true;
    } else if (uiMode == MENU) {
      menuSel   = (menuSel + 1) % MENU_COUNT;
      menuDirty = true;
    } else if (uiMode == INFO) {
      uiMode    = MENU;
      menuSel   = 0;
      menuDirty = true;
    }
  }
}

// ----------------------------------------------------------------------------
// Factory reset helpers (shared by boot gesture and Forget WiFi menu path)
// ----------------------------------------------------------------------------
void drawResetScreen(int secsLeft) {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(4, 14);
  M5.Display.println("HOLD BtnB");
  M5.Display.println("to reset");
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setCursor(4, 62);
  M5.Display.println("release = cancel");
  M5.Display.setTextSize(3);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(54, 90);
  M5.Display.println(String(secsLeft));
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_DARKGREY, TFT_BLACK);
  M5.Display.setCursor(4, 138);
  M5.Display.println("seconds remaining");
}

void factoryReset() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(4, 80);
  M5.Display.println("FACTORY");
  M5.Display.setCursor(4, 106);
  M5.Display.println("  RESET");
  prefs.begin("iris", false);
  prefs.clear();
  prefs.end();
  delay(1200);
  ESP.restart();
}

// ----------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  auto cfg = M5.config();
  M5.begin(cfg);

  // Fix ST7789 color order: M5GFX defaults rgb_order=false (BGR); StickS3 panel needs RGB.
  // Get the live panel pointer, flip the flag, then let setRotation() re-flush MADCTL.
  // This corrects all colors in one place — face engine, menu, and setup screens.
  {
    auto* p = M5.Display.panel();
    auto pcfg = p->config();
    pcfg.rgb_order = true;
    p->config(pcfg);
  }
  M5.Display.setRotation(0);   // portrait (135×240) + re-sends MADCTL with MAD_RGB
  face.begin();

  // ── Boot factory-reset gesture ──────────────────────────────────────────
  // One-time window at power-on only; does not interfere with runtime BtnB.
  // Hold BtnB through the 3s countdown → wipe NVS + restart into portal.
  // Release at any point during countdown → cancel, continue normal boot.
  M5.update();
  if (M5.BtnB.isPressed()) {
    uint32_t t0 = millis();
    int lastSec = -1;
    bool held = true;
    while (millis() - t0 < 3000) {
      M5.update();
      if (!M5.BtnB.isPressed()) { held = false; break; }
      int secsLeft = 3 - (int)((millis() - t0) / 1000);
      if (secsLeft != lastSec) {
        lastSec = secsLeft;
        drawResetScreen(secsLeft);
      }
      delay(30);
    }
    if (held) factoryReset();   // never returns — wipes NVS, restarts
    M5.Display.fillScreen(TFT_BLACK);   // clear countdown on cancel
  }
  // ───────────────────────────────────────────────────────────────────────

  face.setState(Ph3b3Face::BOOT);
  face.update();
  delay(400);
  connectWiFi();
}

void loop() {
  M5.update();

  // ── BtnB: menu (all navigation; WIFI_SETUP mode ignores it) ──────────────
  handleBtnB();

  // ── BtnA: single-click = /chat ping | hold = PTT reserved ────────────────
  // PTT: hold BtnA reserved
  if (M5.BtnA.wasPressed() && uiMode == FACE && WiFi.status() == WL_CONNECTED) {
    face.setState(Ph3b3Face::THINKING);
    face.update();   // draw immediately — ph3b3Chat() blocks and update won't run until it returns
    String reply = ph3b3Chat("Iris online. Comms check.");
    Serial.printf("[btnA] reply: %s\n", reply.c_str());

    bool ok = !reply.startsWith("ERR") &&
              !reply.startsWith("HTTP") &&
              !reply.startsWith("JSON") &&
              !reply.startsWith("(no");
    if (ok) {
      face.setState(Ph3b3Face::SPEAKING);
      face.update();
      delay(2000);   // TODO: replace with real audio duration once ES8311 is wired
      face.setState(Ph3b3Face::IDLE);
    } else {
      face.setState(Ph3b3Face::ERROR);
      face.setStatusLine(reply.substring(0, 20));
    }
  }

  // ── Mode dispatch ─────────────────────────────────────────────────────────
  if (uiMode == FACE) {
    supervisorTick();      // non-blocking reconnect + state updates
    face.update();         // face owns the display in this mode
  } else if (uiMode == MENU) {
    drawMenu();            // dirty-flagged; redraws only on change
  } else if (uiMode == WIFI_SETUP) {
    dns.processNextRequest();
    httpServer.handleClient();
    drawWifiSetup();       // dirty-flagged; draws once on entry
  }
  // INFO: static screen drawn on entry; BtnB handled above

  delay(10);
}
