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

const char*    WEATHER_CITY = "Edinburgh";   // city for the weather prompt
const char*    PH3B3_HOST = "ph3b3.tailfb118a.ts.net";
const uint16_t PH3B3_PORT = 443;
const char*    PH3B3_CHAT = "/chat";
const char*    PH3B3_USER = "REDACTED";
const char*    PH3B3_PASS = "REDACTED";   // <- rotate before this goes over Funnel
const char*    DEVICE_HDR = "iris";
String         SESSION_ID = "iris-session";

// ISRG Root X1 (RSA) + Root X2 (ECDSA) — concatenated so either chain validates.
// Let's Encrypt cert renewed 2026-06-19 and switched to YE2 intermediate → Root X2.
// Keeping X1 as well in case of future chain changes.
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

// Reply text overlay — persists across face.update() calls until next BtnA press
String gLastReply  = "";
bool   gShowReply  = false;

void drawReplyOverlay() {
  const int Y0      = 148;
  const int X0      = 4;
  const int charW   = 6;    // textSize 1 on M5GFX
  const int charH   = 8;
  const int cols    = (M5.Display.width() - X0 * 2) / charW;          // ~21
  const int maxRows = (M5.Display.height() - Y0 - 4) / charH;         // ~10

  M5.Display.fillRect(0, Y0, M5.Display.width(), M5.Display.height() - Y0, TFT_BLACK);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setTextSize(1);
  M5.Display.setTextWrap(false);

  // Word-wrap: break at spaces, never mid-word (unless word > cols)
  const String& src = gLastReply;
  int i = 0, row = 0;
  while (i < (int)src.length() && row < maxRows) {
    int end = i + cols;
    if (end >= (int)src.length()) {
      end = src.length();
    } else {
      // scan back for a break point
      int brk = end;
      while (brk > i && src[brk] != ' ' && src[brk] != '\n') brk--;
      if (brk > i) end = brk;
    }
    // honour embedded newlines
    for (int j = i; j < end; j++) {
      if (src[j] == '\n') { end = j; break; }
    }
    String line = src.substring(i, end);
    line.trim();
    if (line.length()) {
      M5.Display.setCursor(X0, Y0 + 4 + row * charH);
      M5.Display.print(line);
      row++;
    }
    bool isBreak = end < (int)src.length() &&
                   (src[end] == ' ' || src[end] == '\n');
    i = isBreak ? end + 1 : end;
  }
}

// Brief expression beat before TTS plays — maps response tone to eye state
void applyMoodReaction(const String& text) {
  String t = text;
  t.toLowerCase();
  Ph3b3Face::State mood = Ph3b3Face::SPEAKING;   // default

  if (t.indexOf("obviously") >= 0 || t.indexOf("clearly") >= 0 ||
      t.indexOf("actually") >= 0  || t.indexOf("typical") >= 0  ||
      t.indexOf("really")   >= 0  || t.indexOf("sarcas")  >= 0) {
    mood = Ph3b3Face::THINKING;   // sly squint before the quip

  } else if (t.indexOf("sorry")       >= 0 || t.indexOf("unfortunately") >= 0 ||
             t.indexOf("can't")       >= 0 || t.indexOf("cannot")        >= 0 ||
             t.indexOf("unable")      >= 0 || t.indexOf("don't know")    >= 0) {
    mood = Ph3b3Face::ERROR;      // blue "I've got bad news" look

  } else if (t.indexOf("fascinating") >= 0 || t.indexOf("interesting") >= 0 ||
             t.indexOf("incredible")  >= 0 || t.indexOf("love")        >= 0  ||
             t.indexOf("brilliant")   >= 0 || t.indexOf("excellent")   >= 0) {
    mood = Ph3b3Face::LISTENING;  // wide-eyed excitement
  }

  if (mood != Ph3b3Face::SPEAKING) {
    face.setState(mood);
    for (int i = 0; i < 5; i++) { face.update(); delay(60); }  // ~300 ms beat
  }
}

bool     wifiWasConnected = false;
uint32_t lastReconnectMs  = 0;
// Each slot gets 12 s — enough for full auth + DHCP before we try the next.
const uint32_t RECONNECT_INTERVAL = 12000;

String cachedScan = "";
String portalMsg  = "";

// BtnB hold detection — manual timing avoids M5Unified API ambiguity
uint32_t btnBPressedAt = 0;
bool     btnBLongFired  = false;

// ----------------------------------------------------------------------------
// NVS helpers
// ----------------------------------------------------------------------------
// Up to 5 networks; slot 0 uses legacy keys "ssid"/"pass" for backward compat
static const int MAX_NETS = 5;
static const char* SSID_KEYS[MAX_NETS] = {"ssid","ssid1","ssid2","ssid3","ssid4"};
static const char* PASS_KEYS[MAX_NETS] = {"pass","pass1","pass2","pass3","pass4"};

int loadAllCreds(String ssids[], String passes[], int maxSlots) {
  int lim = min(maxSlots, MAX_NETS);
  prefs.begin("iris", true);
  for (int i = 0; i < lim; i++) {
    ssids[i]  = prefs.getString(SSID_KEYS[i], "");
    passes[i] = prefs.getString(PASS_KEYS[i], "");
  }
  prefs.end();
  int n = 0;
  for (int i = 0; i < lim; i++) if (ssids[i].length()) n = i + 1;
  return n;
}

bool loadCreds(String& ssid, String& pass) {
  String ss[1], pp[1];
  bool ok = loadAllCreds(ss, pp, 1) > 0;
  ssid = ss[0]; pass = pp[0];
  return ok;
}

void saveAllCreds(const String ssids[], const String passes[], int count) {
  prefs.begin("iris", false);
  for (int i = 0; i < MAX_NETS; i++) {
    if (i < count && ssids[i].length()) {
      prefs.putString(SSID_KEYS[i], ssids[i]);
      prefs.putString(PASS_KEYS[i], passes[i]);
    } else {
      prefs.putString(SSID_KEYS[i], "");
      prefs.putString(PASS_KEYS[i], "");
    }
  }
  prefs.end();
}

void saveCreds(const String& ssid, const String& pass, int slot = 0) {
  if (slot < 0 || slot >= MAX_NETS) return;
  prefs.begin("iris", false);
  prefs.putString(SSID_KEYS[slot], ssid);
  prefs.putString(PASS_KEYS[slot], pass);
  prefs.end();
}

// Format "IP  -68dBm" for the face status line
String wifiStatusStr() {
  return WiFi.localIP().toString() + "  " + String(WiFi.RSSI()) + "dBm";
}

// Pull network list from Ph3b3 and save to NVS. Server is source of truth.
void syncNetworksFromPh3b3() {
  WiFiClientSecure tls;
  tls.setCACert(ISRG_ROOT_X1);
  tls.setTimeout(8000);
  HTTPClient http;
  http.begin(tls, PH3B3_HOST, PH3B3_PORT, "/iris/networks", true);
  http.setAuthorization(PH3B3_USER, PH3B3_PASS);
  http.addHeader("X-Ph3b3-Device", "iris");
  http.setTimeout(8000);
  int code = http.GET();
  if (code != HTTP_CODE_OK) { http.end(); return; }
  String body = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, body) != DeserializationError::Ok) return;
  JsonArray nets = doc["networks"];
  if (!nets) return;

  String ssids[MAX_NETS], passes[MAX_NETS];
  int count = 0;
  for (JsonObject n : nets) {
    if (count >= MAX_NETS) break;
    const char* s = n["ssid"];
    const char* p = n["pass"];
    if (s && *s) { ssids[count] = s; passes[count] = p ? p : ""; count++; }
  }
  if (count > 0) {
    saveAllCreds(ssids, passes, count);
    Serial.printf("[iris] synced %d networks from Ph3b3\n", count);
  }
}

// Scan for known networks; return index of best-signal slot, or -1 if none found.
// ssids[] / passes[] must already be loaded.
int pickBestNetwork(const String ssids[], int netCount) {
  int n = WiFi.scanNetworks();
  int bestSlot = -1, bestRssi = -999;
  for (int i = 0; i < n; i++) {
    for (int s = 0; s < netCount; s++) {
      if (ssids[s].length() && WiFi.SSID(i) == ssids[s]) {
        if (WiFi.RSSI(i) > bestRssi) { bestRssi = WiFi.RSSI(i); bestSlot = s; }
      }
    }
  }
  WiFi.scanDelete();
  return bestSlot;
}

// ----------------------------------------------------------------------------
// WiFi supervisor — non-blocking, called every FACE-mode loop tick
// ----------------------------------------------------------------------------
void supervisorTick() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiWasConnected) {
      wifiWasConnected = true;
      face.setState(Ph3b3Face::IDLE);
      face.setStatusLine(wifiStatusStr());
    }
    // Sync networks once, 10 s after first connect — deferred so boot TLS
    // is long gone and heap is unfragmented before PTT is possible.
    static bool syncDone = false;
    static uint32_t connectedAt = 0;
    if (!syncDone) {
      if (connectedAt == 0) connectedAt = millis();
      if (millis() - connectedAt > 10000) {
        syncDone = true;
        syncNetworksFromPh3b3();
      }
    }
    return;
  }
  static bool syncDone = false;  // reset on disconnect so next connect re-syncs
  syncDone = false;
  if (wifiWasConnected) {
    wifiWasConnected = false;
    face.setState(Ph3b3Face::ERROR);
    face.setStatusLine("offline");
  }
  uint32_t now = millis();
  if (now - lastReconnectMs < RECONNECT_INTERVAL) return;
  lastReconnectMs = now;

  // Alternate between stored networks each attempt — no blocking scan here,
  // that would freeze the main loop and swallow button events.
  String ssids[2], passes[2];
  int count = loadAllCreds(ssids, passes, 2);
  if (count == 0) return;
  static int reconnectSlot = 0;
  reconnectSlot = (reconnectSlot + 1) % count;
  String shortSsid = ssids[reconnectSlot].substring(0, 14);
  face.setStatusLine("trying " + shortSsid + "...");
  WiFi.disconnect();
  delay(200);   // let the radio settle before issuing a new begin()
  WiFi.begin(ssids[reconnectSlot].c_str(), passes[reconnectSlot].c_str());
}

// ----------------------------------------------------------------------------
// POST /chat (unchanged from face-engine rung)
// ----------------------------------------------------------------------------
// ── Audio (base64 WAV → M5.Speaker) ──────────────────────────────────────────
// ESP32-S3 has only BLE — no Bluetooth Classic A2DP.
// Audio plays through the onboard speaker via M5Unified's I2S driver.
// ph3b3Chat() decodes the base64 WAV field from the HTTP response into a
// heap-allocated buffer then hands it to M5.Speaker.playWav().

static int b64val(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '+') return 62;
  if (c == '/') return 63;
  return -1;
}

static const char B64ENC[] =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static void buildWavHeader(uint8_t* h, int samples, int rate) {
  int d = samples * 2, f = 36 + d, br = rate * 2;
  memcpy(h, "RIFF", 4); h[4]=f;h[5]=f>>8;h[6]=f>>16;h[7]=f>>24;
  memcpy(h+8, "WAVE", 4); memcpy(h+12, "fmt ", 4);
  h[16]=16;h[17]=0;h[18]=0;h[19]=0;
  h[20]=1;h[21]=0; h[22]=1;h[23]=0;
  h[24]=rate;h[25]=rate>>8;h[26]=rate>>16;h[27]=rate>>24;
  h[28]=br;h[29]=br>>8;h[30]=br>>16;h[31]=br>>24;
  h[32]=2;h[33]=0; h[34]=16;h[35]=0;
  memcpy(h+36, "data", 4); h[40]=d;h[41]=d>>8;h[42]=d>>16;h[43]=d>>24;
}


// PTT: encode audio → base64 JSON, POST /transcribe, then /chat.
// Takes ownership of *ppAudio and frees it before opening TLS so that
// sPttBuf(96KB) + jbuf(128KB) + TLS(~72KB) never all live at once.
static void doPttTranscribeAndChat(int16_t** ppAudio, int numSamples) {
  int16_t* audio = *ppAudio;
  face.setState(Ph3b3Face::THINKING);
  face.setStatusLine("transcribing...");
  face.update();

  // Build {"audio":"<base64_wav>"} in one malloc so we never double-buffer.
  uint8_t wavHdr[44];
  buildWavHeader(wavHdr, numSamples, 16000);
  int wavBytes = 44 + numSamples * 2;
  int b64Len   = ((wavBytes + 2) / 3) * 4;
  int jLen     = 10 + b64Len + 2;            // {"audio":"..."}
  char* jbuf   = (char*)malloc(jLen + 1);
  if (!jbuf) {
    face.setState(Ph3b3Face::ERROR); face.setStatusLine("OOM-PTT"); face.update(); return;
  }

  memcpy(jbuf, "{\"audio\":\"", 10);
  int pos = 10;

  // Inline base64 encoder: feed WAV header then PCM samples
  uint8_t tri[3]; int triPos = 0;
  auto flushTri = [&](int validBytes) {
    while (triPos < 3) tri[triPos++] = 0;
    jbuf[pos++] = B64ENC[(tri[0]>>2)&0x3F];
    jbuf[pos++] = B64ENC[((tri[0]&3)<<4)|((tri[1]>>4)&0xF)];
    jbuf[pos++] = validBytes < 2 ? '=' : B64ENC[((tri[1]&0xF)<<2)|((tri[2]>>6)&0x3)];
    jbuf[pos++] = validBytes < 3 ? '=' : B64ENC[tri[2]&0x3F];
    triPos = 0;
  };
  auto feedB = [&](uint8_t b) {
    tri[triPos++] = b;
    if (triPos == 3) { flushTri(3); }
  };

  for (int i = 0; i < 44; i++) feedB(wavHdr[i]);
  for (int i = 0; i < numSamples; i++) {
    feedB((uint8_t)(audio[i] & 0xFF));
    feedB((uint8_t)((audio[i] >> 8) & 0xFF));
  }
  if (triPos > 0) flushTri(triPos);

  jbuf[pos++] = '"'; jbuf[pos++] = '}'; jbuf[pos] = '\0';

  // Audio is fully encoded into jbuf — free it now before TLS opens.
  // Without this: sPttBuf(96KB) + jbuf(128KB) + TLS(~72KB) = 296KB > 268KB free → err -1.
  free(*ppAudio); *ppAudio = nullptr;

  // POST to /transcribe — blocking; jbuf(128KB) + TLS(~72KB) = 200KB, fits in 268KB.
  // peak heap is jbuf(~128 KB freed) + TLS(~72 KB) = tolerable on 268 KB free.
  face.setStatusLine("sending...");
  face.update();

  WiFiClientSecure tls2;
  tls2.setCACert(ISRG_ROOT_X1);
  tls2.setTimeout(20000);
  HTTPClient http2;
  http2.begin(tls2, PH3B3_HOST, PH3B3_PORT, "/transcribe", true);
  http2.setAuthorization(PH3B3_USER, PH3B3_PASS);
  http2.addHeader("Content-Type", "application/json");
  http2.addHeader("X-Ph3b3-Device", "iris");
  http2.setTimeout(20000);

  int code = http2.POST((uint8_t*)jbuf, pos);
  free(jbuf); jbuf = nullptr;

  String heard = "";
  if (code == HTTP_CODE_OK) {
    String body = http2.getString();
    JsonDocument doc;
    deserializeJson(doc, body);
    const char* t = doc["text"];
    if (t && *t) heard = String(t);
  }
  http2.end();
  Serial.printf("[ptt] transcribe=%d heard='%s'\n", code, heard.c_str());

  if (heard.length() == 0) {
    face.setState(Ph3b3Face::ERROR);
    String errMsg = (code > 0) ? "http " + String(code) :
                    (code == 0) ? "timeout" : "err " + String(code);
    // Append max-allocatable block so we can see heap fragmentation on device
    errMsg += " " + String(ESP.getMaxAllocHeap() / 1024) + "k";
    face.setStatusLine(errMsg);
    face.update();
    delay(2000);
    face.setState(Ph3b3Face::IDLE);
    face.setStatusLine(wifiStatusStr());
    face.update();
    return;
  }

  // Brief "You: ..." flash so the user knows what was heard
  gLastReply = String("You: ") + heard;
  gShowReply = true;
  face.setState(Ph3b3Face::THINKING);
  face.setStatusLine("sending...");
  face.update();
  drawReplyOverlay();
  delay(700);
  gShowReply = false;

  String reply = ph3b3Chat(heard);
  bool ok = !reply.startsWith("ERR") && !reply.startsWith("HTTP") &&
            !reply.startsWith("JSON") && !reply.startsWith("(no");
  face.setState(ok ? Ph3b3Face::IDLE : Ph3b3Face::ERROR);
  if (!ok) face.setStatusLine(reply.substring(0, 20));
  face.update();
}

// ─────────────────────────────────────────────────────────────────────────────
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

  face.setStatusLine("asking ph3b3...");
  face.update();
  int code = http.POST(payload);
  if (code != HTTP_CODE_OK) { http.end(); return "HTTP " + String(code); }

  face.setStatusLine("reading reply...");
  face.update();

  // ── Phase 1: first 6 KB captures the full "response" text ───────────────
  static const int PEEK_MAX = 6144;
  static char peek[PEEK_MAX + 1];
  WiFiClient* raw = http.getStreamPtr();
  raw->setTimeout(60000);
  int peekLen = raw->readBytes(peek, PEEK_MAX);
  peek[peekLen] = '\0';

  JsonDocument filter; filter["response"] = true;
  JsonDocument doc;
  deserializeJson(doc, peek, peekLen, DeserializationOption::Filter(filter));
  const char* resp = doc["response"];
  String responseText = (resp && *resp) ? String(resp) : "";

  // Show text + switch to SPEAKING now, while audio still decoding
  if (responseText.length() > 0) {
    gLastReply = responseText;
    gShowReply = true;
    applyMoodReaction(responseText);   // brief expression beat before she speaks
    face.setState(Ph3b3Face::SPEAKING);
    face.setStatusLine("ph3b3 says:");
    face.update();
    drawReplyOverlay();
  }

  // ── Phase 2: stream-decode "audio" base64 → PCM chunks → M5.Speaker ─────
  // Streams directly without a large heap buffer: no size cap, any length works.
  // playRaw() stores a pointer (not a copy), so we must finish each chunk before
  // overwriting the buffer. We poll isPlaying() with delay(1) between 46 ms chunks.
  const char* audioTag = "\"audio\":\"";
  char* foundTag = strstr(peek, audioTag);
  int audioStart = foundTag ? (int)(foundTag - peek) + (int)strlen(audioTag) : -1;

  if (audioStart >= 0) {
    // Double-buffered stream decode: buf A plays while buf B is filled, then swap.
    // Eliminates the race where the speaker reads from the same buffer being written.
    // BtnA during playback stops audio immediately.
    static const int CHUNK_SAMPLES = 1024;   // ~46 ms @ 22050 Hz
    static int16_t pcmBuf[2][CHUNK_SAMPLES];
    int   fillIdx       = 0;
    int   chunkPos      = 0;
    int   wavHdrSkipped = 0;
    uint8_t halfLo      = 0;
    bool  halfReady     = false;
    char  b4[4]; int b4pos = 0;
    bool  keepGoing     = true;

    auto flushChunk = [&]() {
      if (chunkPos == 0) return;
      while (M5.Speaker.isPlaying()) delay(1);
      if (!keepGoing) return;                              // interrupted — don't play
      M5.Speaker.playRaw(pcmBuf[fillIdx], chunkPos, 22050, false, 1, 0);
      fillIdx ^= 1;                                       // swap to other buffer
      chunkPos = 0;
    };

    auto pushByte = [&](uint8_t b) {
      if (wavHdrSkipped++ < 44) return;
      if (!halfReady) { halfLo = b; halfReady = true; return; }
      pcmBuf[fillIdx][chunkPos++] = (int16_t)((b << 8) | halfLo);
      halfReady = false;
      if (chunkPos == CHUNK_SAMPLES) flushChunk();
    };

    auto feedCh = [&](char ch) {
      if (!keepGoing) return;
      if (ch == '"') { keepGoing = false; return; }
      int v = b64val(ch);
      if (v < 0) return;
      b4[b4pos++] = ch;
      if (b4pos == 4) {
        int v0=b64val(b4[0]), v1=b64val(b4[1]), v2=b64val(b4[2]), v3=b64val(b4[3]);
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

    for (int i = audioStart; i < peekLen; i++) feedCh(peek[i]);

    if (keepGoing) {
      face.setStatusLine("playing audio...");
      face.update();
      if (gShowReply) drawReplyOverlay();

      uint32_t deadline = millis() + 90000;
      while (keepGoing && millis() < deadline) {
        M5.update();
        if (M5.BtnA.wasPressed()) {
          M5.Speaker.stop();
          keepGoing = false;
          break;
        }
        int c = raw->read();
        if (c < 0) { delay(1); continue; }
        feedCh((char)c);
      }
    }

    flushChunk();
    http.end();

    while (M5.Speaker.isPlaying()) {
      M5.update();
      if (M5.BtnA.wasPressed()) { M5.Speaker.stop(); break; }
      face.update();
      if (gShowReply) drawReplyOverlay();
      delay(50);
    }
  } else {
    http.end();
  }

  return responseText.length() > 0 ? responseText : String("(no response)");
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
  String ssids[2], passes[2];
  loadAllCreds(ssids, passes, 2);
  html = "<!DOCTYPE html><html><head>"
         "<meta charset='utf-8'>"
         "<meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>Iris Setup</title>"
         "<style>"
         "body{background:#000;color:#0ff;font-family:monospace;padding:20px;max-width:400px}"
         "h2,h3{color:#0ff;margin:0 0 8px}"
         "h3{font-size:0.85em;opacity:0.7;margin-top:16px}"
         "select,input{background:#111;color:#0ff;border:1px solid #0ff;"
         "padding:8px;width:100%;margin:6px 0;box-sizing:border-box;font-family:monospace}"
         "button{background:#0ff;color:#000;border:none;padding:12px;"
         "width:100%;margin-top:10px;font-family:monospace;font-weight:bold;cursor:pointer}"
         ".ok{color:#0f0;margin-top:10px}.err{color:#f55;margin-top:10px}"
         "</style></head><body>"
         "<h2>IRIS SETUP</h2>"
         "<form method='POST' action='/connect'>"
         "<h3>PRIMARY NETWORK</h3>";
  html += cachedScan;
  html += "<input type='password' name='pass' placeholder='password' autocomplete='off'>";
  // NOTE: portal creds sent over local AP in cleartext
  html += "<h3>BACKUP NETWORK (optional)</h3>"
          "<input type='text' name='ssid1' placeholder='backup SSID' value='" + ssids[1] + "' autocomplete='off'>"
          "<input type='password' name='pass1' placeholder='backup password' autocomplete='off'>"
          "<button type='submit'>CONNECT</button></form>";
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
    saveCreds(ssid, pass, 0);
    // Save backup network if provided
    String ssid1 = httpServer.hasArg("ssid1") ? httpServer.arg("ssid1") : "";
    String pass1 = httpServer.hasArg("pass1") ? httpServer.arg("pass1") : "";
    ssid1.trim();
    if (ssid1.length()) saveCreds(ssid1, pass1, 1);
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
#ifdef LAB_SSID
  String ssids[2] = {LAB_SSID, ""}, passes[2] = {LAB_PASS, ""};
  int count = 1;
#else
  String ssids[2], passes[2];
  int count = loadAllCreds(ssids, passes, 2);
  if (count == 0) { startPortal(); return; }
#endif

  face.setState(Ph3b3Face::CONNECTING);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);           // supervisor handles all reconnects — no internal racing
  WiFi.setTxPower(WIFI_POWER_19_5dBm);   // max radio power for best field range

  // Scan and pick the known network with the strongest signal
  face.setStatusLine("scanning...");
  face.update();
  int slot = pickBestNetwork(ssids, count);
  if (slot < 0) slot = 0;   // nothing found — try primary anyway

  face.setStatusLine("joining " + ssids[slot] + "...");
  face.update();
  WiFi.begin(ssids[slot].c_str(), passes[slot].c_str());

  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    face.update();
    delay(50);
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiWasConnected = true;
    face.setState(Ph3b3Face::IDLE);
    face.setStatusLine(wifiStatusStr());
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
// BtnB handler — side button is a direct WiFi-setup shortcut
// ----------------------------------------------------------------------------
void handleBtnB() {
  if (M5.BtnB.wasPressed()) {
    btnBPressedAt = millis();
    btnBLongFired  = false;
  }

  // Long hold still navigates the menu (for Forget WiFi / Info / factory reset)
  if (M5.BtnB.isPressed() && !btnBLongFired &&
      millis() - btnBPressedAt > 600) {
    btnBLongFired = true;
    if (uiMode == MENU) activateMenuItem();
    else if (uiMode == FACE) {
      uiMode    = MENU;
      menuSel   = 0;
      menuDirty = true;
    }
  }

  // Short tap from FACE → launch WiFi setup portal directly
  // Short tap from MENU/INFO → cycle / back (existing behaviour)
  if (M5.BtnB.wasReleased() && !btnBLongFired) {
    if (uiMode == FACE) {
      startPortal();   // direct path to WiFi setup
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

  M5.Speaker.begin();
  M5.Speaker.setVolume(200);   // 0–255; default is low, needs explicit set

  // Fresh session each boot prevents corrupted iris-session history from
  // causing the LLM to describe tool calls instead of executing them.
  SESSION_ID = "iris-" + String(esp_random(), HEX);


  face.setState(Ph3b3Face::BOOT);
  face.update();
  delay(400);
  connectWiFi();
}

void loop() {
  M5.update();

  // ── BtnB: menu (all navigation; WIFI_SETUP mode ignores it) ──────────────
  handleBtnB();

  // ── BtnA: tap = rotating /chat prompt │ hold ≥350ms = PTT voice input ──────
  static uint32_t sBtnADownAt  = 0;
  static bool     sPttActive   = false;
  static int16_t* sPttBuf      = nullptr;
  static int      sPttSamples  = 0;
  static const int PTT_RATE    = 16000;
  static const int PTT_MAX     = PTT_RATE * 3;   // 3 s @ 16 kHz = 96 KB

  if (M5.BtnA.wasPressed() && uiMode == FACE) {
    sBtnADownAt = millis();
    sPttActive  = false;
  }

  // After 500 ms hold: start recording (quick taps are ~100-200 ms so this is safe)
  if (M5.BtnA.isPressed() && !sPttActive && uiMode == FACE
      && WiFi.status() == WL_CONNECTED
      && (millis() - sBtnADownAt) >= 500) {
    sPttActive  = true;
    sPttSamples = 0;
    sPttBuf     = (int16_t*)malloc(PTT_MAX * 2);
    if (sPttBuf) {
      if (M5.Speaker.isPlaying()) M5.Speaker.stop();
      // Boost analog-to-digital path: ES8311 PGA is at 0 dB by default;
      // magnification applies software gain so Whisper sees a strong signal.
      auto micCfg = M5.Mic.config();
      micCfg.sample_rate   = PTT_RATE;
      micCfg.magnification = 16;
      M5.Mic.config(micCfg);
      M5.Mic.begin();
      face.setState(Ph3b3Face::LISTENING);
      face.setStatusLine("listening...");
      face.update();
    }
  }

  // Accumulate audio while held — 512-sample chunks reduce loop overhead
  if (sPttActive && sPttBuf && M5.BtnA.isPressed() && sPttSamples < PTT_MAX) {
    int chunk = min(512, PTT_MAX - sPttSamples);
    M5.Mic.record(&sPttBuf[sPttSamples], chunk, PTT_RATE);
    sPttSamples += chunk;
    face.update();
  }

  // Release: dispatch PTT or tap
  if (M5.BtnA.wasReleased() && uiMode == FACE && WiFi.status() == WL_CONNECTED) {
    if (sPttActive) {
      M5.Mic.end();
      // ES8311 is shared: Mic.begin() resets it to ADC mode, Mic.end() powers it down.
      // Re-initialise speaker to restore DAC before any audio playback.
      M5.Speaker.end();
      M5.Speaker.begin();
      M5.Speaker.setVolume(200);
      if (sPttBuf && sPttSamples > 0)
        doPttTranscribeAndChat(&sPttBuf, sPttSamples);  // takes ownership, nulls sPttBuf
      if (sPttBuf) { free(sPttBuf); sPttBuf = nullptr; }  // safety — already null if func ran
      sPttActive = false;
    } else if ((millis() - sBtnADownAt) < 600) {
      // Short tap → rotating prompt
      static char sWeatherQ[64];
      if (sWeatherQ[0] == '\0')
        snprintf(sWeatherQ, sizeof(sWeatherQ), "What's the current weather in %s?", WEATHER_CITY);
      static const char* PROMPTS[] = {
        sWeatherQ,
        "Ph3b3, what's on your mind today?",
        "Tell me something interesting.",
        "Any updates for me?",
      };
      static int promptIdx = -1;
      if (promptIdx < 0) promptIdx = (int)(esp_random() % 4);

      gShowReply = false;
      face.setState(Ph3b3Face::THINKING);
      face.setStatusLine("connecting...");
      face.update();

      String reply = ph3b3Chat(PROMPTS[promptIdx++ % 4]);
      Serial.printf("[btnA] reply: %s\n", reply.c_str());

      bool ok = !reply.startsWith("ERR") && !reply.startsWith("HTTP") &&
                !reply.startsWith("JSON") && !reply.startsWith("(no");
      face.setState(ok ? Ph3b3Face::IDLE : Ph3b3Face::ERROR);
      if (!ok) face.setStatusLine(reply.substring(0, 20));
    }
  }

  // ── Mode dispatch ─────────────────────────────────────────────────────────
  if (uiMode == FACE) {
    supervisorTick();      // non-blocking reconnect + state updates
    face.update();         // face owns the display in this mode
    if (gShowReply) drawReplyOverlay();   // overlay reply text on top of face
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
