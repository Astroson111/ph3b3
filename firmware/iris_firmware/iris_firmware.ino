// iris_firmware.ino
// Iris — M5StickS3 voice combadge.
// Ph3b3Face integration: replaces the border-color state display with the
// full M5GFX face engine. /chat round-trip preserved intact.
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
#include "ph3b3_face.h"

// ----------------------------------------------------------------------------
// CONFIG — fill these in
// ----------------------------------------------------------------------------
const char* WIFI_SSID = "YOUR_SSID";
const char* WIFI_PASS = "YOUR_PASS";

// Ph3b3 over Tailscale. If Funnel: public host, port 443, real LE cert.
//   e.g. "ph3b3.tailXXXXXX.ts.net"
const char* PH3B3_HOST = "ph3b3.tailXXXXXX.ts.net";
const uint16_t PH3B3_PORT = 443;
const char* PH3B3_CHAT  = "/chat";

// Basic auth — HTTPClient builds the header for us, no manual base64.
const char* PH3B3_USER = "REDACTED";
const char* PH3B3_PASS = "REDACTED";   // <- rotate before this goes over Funnel

const char* DEVICE_HDR = "iris";       // shows up in Ph3b3's device roster
String SESSION_ID = "iris-session";    // make per-session later if you want

// ----------------------------------------------------------------------------
Ph3b3Face face;

// ----------------------------------------------------------------------------
// WiFi
// ----------------------------------------------------------------------------
void connectWiFi() {
  face.setState(Ph3b3Face::CONNECTING);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    face.update();
    delay(50);
  }
  if (WiFi.status() == WL_CONNECTED) {
    face.setState(Ph3b3Face::IDLE);
    face.setStatusLine(WiFi.localIP().toString());
  } else {
    face.setState(Ph3b3Face::ERROR);
    face.setStatusLine("wifi failed");
  }
}

// ----------------------------------------------------------------------------
// POST /chat  ->  returns the response text (audio field ignored this rung)
// ----------------------------------------------------------------------------
String ph3b3Chat(const String& message) {
  WiFiClientSecure tls;
  // SECURITY TODO: pin ISRG Root X1 before this leaves LAN/tailnet
  tls.setInsecure();

  HTTPClient http;
  if (!http.begin(tls, PH3B3_HOST, PH3B3_PORT, PH3B3_CHAT, true)) {
    return String("ERR: begin failed");
  }
  http.setAuthorization(PH3B3_USER, PH3B3_PASS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Ph3b3-Device", DEVICE_HDR);

  JsonDocument body;
  body["message"] = message;
  body["session_id"] = SESSION_ID;
  String payload;
  serializeJson(body, payload);

  int code = http.POST(payload);
  if (code != HTTP_CODE_OK) {
    http.end();
    return "HTTP " + String(code);
  }

  // Filter to "response" only — keeps the base64 "audio" blob off the heap.
  // TODO: add filter["audio"]=true, decode WAV, feed ES8311 over I2S,
  //       then call face.setSpeakingLevel(rms01) from each decoded chunk.
  JsonDocument filter;
  filter["response"] = true;

  JsonDocument doc;
  DeserializationError err = deserializeJson(
      doc, http.getStream(), DeserializationOption::Filter(filter));
  http.end();

  if (err) return String("JSON: ") + err.c_str();
  return String(doc["response"] | "(no response field)");
}

// ----------------------------------------------------------------------------
void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  M5.Display.setRotation(0);   // portrait (135×240) — face engine reads W/H here
  face.begin();
  face.setState(Ph3b3Face::BOOT);
  face.update();
  delay(400);
  connectWiFi();
}

void loop() {
  M5.update();
  face.update();

  // WiFi lost — drop to error state
  if (WiFi.status() != WL_CONNECTED) {
    face.setState(Ph3b3Face::ERROR);
    face.setStatusLine("offline");
  }

  // BtnA: fire a /chat round-trip
  if (M5.BtnA.wasPressed() && WiFi.status() == WL_CONNECTED) {
    face.setState(Ph3b3Face::THINKING);
    String reply = ph3b3Chat("Iris online. Comms check.");
    Serial.println(reply);

    bool ok = !reply.startsWith("ERR") &&
              !reply.startsWith("HTTP") &&
              !reply.startsWith("JSON");

    if (ok) {
      face.setState(Ph3b3Face::SPEAKING);
      // TODO: real duration from audio length once ES8311 is wired
      delay(2000);
      face.setState(Ph3b3Face::IDLE);
    } else {
      face.setState(Ph3b3Face::ERROR);
      face.setStatusLine(reply.substring(0, 20));
    }
  }

  delay(10);
}
