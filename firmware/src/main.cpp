#include <M5Unified.h>
#include <Avatar.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>

// ── Credentials & endpoints ──────────────────────────────────────────────────
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define PH3B3_HOST    "192.168.0.23"
#define PH3B3_PORT    7331
#define PH3B3_PATH    "/ws/stackchan"

// ── Servo pins & travel ──────────────────────────────────────────────────────
#define PAN_PIN     13
#define TILT_PIN    14
#define PAN_CENTER  90
#define PAN_LEFT    45
#define PAN_RIGHT  135
#define TILT_CENTER 90
#define TILT_UP     60
#define TILT_DOWN  115

using namespace m5avatar;

// ── State machine ────────────────────────────────────────────────────────────
enum AppState { STATE_BOOT, STATE_SELECT, STATE_ACTIVE };
AppState appState = STATE_BOOT;

// ── Modes ────────────────────────────────────────────────────────────────────
enum Mode { MODE_NONE = -1, MODE_CHAT = 0, MODE_GHOST, MODE_TRANSLATE, MODE_SECURITY, MODE_MEDIA };
Mode activeMode = MODE_NONE;

struct ModeInfo {
    const char* id;        // display name
    uint32_t    color;     // accent (RGB888)
    uint32_t    darkBg;    // tile/screen background
    const char* context;   // message sent to Ph3b3 on mode entry
    const char* btnC;      // BtnC shortcut message
};

// 5 modes — colors match spec (purple / green / blue / red / orange)
static const ModeInfo MODES[] = {
    { "CHAT",
      0xA855F7, 0x130A26,
      "Mode switch: CHAT — general conversation mode active.",
      "Ph3b3, how are you doing?" },

    { "GHOST",
      0x22C55E, 0x071810,
      "Mode switch: GHOST — paranormal investigation active. Ready to log EVP events and anomalies.",
      "Ph3b3, log an EVP event now." },

    { "TRANSLATE",
      0x3B82F6, 0x071528,
      "Mode switch: TRANSLATE — real-time translation mode. Translate what I say.",
      "Ph3b3, what languages do you support?" },

    { "SECURITY",
      0xEF4444, 0x1A0808,
      "Mode switch: SECURITY — network and system monitoring active.",
      "Ph3b3, run a network scan." },

    { "MEDIA",
      0xF97316, 0x1A0E04,
      "Mode switch: MEDIA — Spotify, weather, and timers ready.",
      "Ph3b3, what's currently playing?" },
};

// ── Tile layout: 320×240, header 40 px ──────────────────────────────────────
// Row 1 (y=40, h=70): CHAT | GHOST
// Row 2 (y=110, h=70): TRANSLATE | SECURITY
// Row 3 (y=180, h=60): MEDIA  (full width)
struct Tile { int16_t x, y, w, h; Mode mode; };
static const Tile TILES[] = {
    {   0,  40, 160, 70, MODE_CHAT      },
    { 160,  40, 160, 70, MODE_GHOST     },
    {   0, 110, 160, 70, MODE_TRANSLATE },
    { 160, 110, 160, 70, MODE_SECURITY  },
    {   0, 180, 320, 60, MODE_MEDIA     },
};
static const int TILE_COUNT = sizeof(TILES) / sizeof(TILES[0]);

// ── Hardware objects ─────────────────────────────────────────────────────────
Avatar           avatar;
WebSocketsClient webSocket;
Servo            panServo;
Servo            tiltServo;

bool wsConnected   = false;
bool avatarInited  = false;

// ═══════════════════════════════════════════════════════════════════════════════
// Servo
// ═══════════════════════════════════════════════════════════════════════════════

void nodYes() {
    for (int i = 0; i < 2; i++) {
        tiltServo.write(TILT_UP);   delay(280);
        tiltServo.write(TILT_DOWN); delay(280);
    }
    tiltServo.write(TILT_CENTER); delay(180);
}

void shakeNo() {
    for (int i = 0; i < 2; i++) {
        panServo.write(PAN_LEFT);  delay(280);
        panServo.write(PAN_RIGHT); delay(280);
    }
    panServo.write(PAN_CENTER); delay(180);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Avatar lifecycle
// ═══════════════════════════════════════════════════════════════════════════════

void startAvatar() {
    if (!avatarInited) {
        avatar.init();
        avatarInited = true;
    } else {
        avatar.start();
    }
}

void stopAvatar() {
    if (avatarInited) avatar.stop();
}

// ═══════════════════════════════════════════════════════════════════════════════
// Display helpers
// ═══════════════════════════════════════════════════════════════════════════════

static void centeredText(const char* text, int16_t x, int16_t y, int16_t w,
                         uint32_t color, uint8_t size = 1) {
    M5.Display.setTextColor(color);
    M5.Display.setTextDatum(middle_center);
    M5.Display.setTextSize(size);
    M5.Display.drawString(text, x + w / 2, y);
}

// ── Boot screen ──────────────────────────────────────────────────────────────
void showBoot() {
    M5.Display.fillScreen(0x0A0A14);

    M5.Display.setTextDatum(middle_center);

    // Logo
    M5.Display.setTextColor(0xA855F7);
    M5.Display.setTextSize(3);
    M5.Display.drawString("PH3B3", 160, 85);

    // Subtitle
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(0x5B5280);
    M5.Display.drawString("STACK-CHAN  v2.0", 160, 125);

    // Status line (overwritten after WiFi attempt)
    M5.Display.setTextColor(0x7C3AED);
    M5.Display.drawString("connecting to nyx...", 160, 168);
}

void updateBootStatus(bool wifiOk) {
    // Clear status line
    M5.Display.fillRect(0, 155, 320, 30, 0x0A0A14);
    M5.Display.setTextDatum(middle_center);
    M5.Display.setTextSize(1);
    if (wifiOk) {
        M5.Display.setTextColor(0x22C55E);
        M5.Display.drawString("wifi ok — touch to select mode", 160, 168);
    } else {
        M5.Display.setTextColor(0xEF4444);
        M5.Display.drawString("wifi failed — check credentials", 160, 168);
    }
    delay(700);
}

// ── Mode selector ─────────────────────────────────────────────────────────────
static void drawStatusDot() {
    uint32_t c = wsConnected ? 0x22C55E : 0x3D3660;
    M5.Display.fillCircle(8, 235, 4, c);
    M5.Display.setTextColor(wsConnected ? 0x22C55E : 0x3D3660);
    M5.Display.setTextDatum(middle_left);
    M5.Display.setTextSize(1);
    M5.Display.drawString(wsConnected ? "nyx online" : "connecting...", 16, 235);
}

static void drawTile(const Tile& t, bool pressed = false) {
    const ModeInfo& m = MODES[t.mode];
    uint32_t bg = pressed ? m.color   : m.darkBg;
    uint32_t fg = pressed ? 0x000000  : m.color;
    M5.Display.fillRect(t.x + 1, t.y + 1, t.w - 2, t.h - 2, bg);
    M5.Display.drawRect(t.x, t.y, t.w, t.h, m.color);
    centeredText(m.id, t.x, t.y + t.h / 2, t.w, fg, 1);
}

void showModeSelector() {
    stopAvatar();
    M5.Display.fillScreen(0x0A0A14);

    // Header bar
    M5.Display.fillRect(0, 0, 320, 40, 0x0C0C1E);
    M5.Display.drawFastHLine(0, 40, 320, 0x7C3AED);
    centeredText("SELECT MODE", 0, 20, 320, 0xA855F7, 1);

    // Mode tiles
    for (int i = 0; i < TILE_COUNT; i++) drawTile(TILES[i]);

    // Connection status dot
    drawStatusDot();
}

// ═══════════════════════════════════════════════════════════════════════════════
// WebSocket
// ═══════════════════════════════════════════════════════════════════════════════

void sendMessage(const char* msg) {
    if (!wsConnected) return;
    StaticJsonDocument<512> doc;
    doc["message"] = msg;
    String json;
    serializeJson(doc, json);
    webSocket.sendTXT(json);
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {

        case WStype_DISCONNECTED:
            wsConnected = false;
            M5.Power.setLed(0);
            if (avatarInited) {
                avatar.setExpression(Expression::Sad);
                avatar.setSpeechText("Lost Nyx...");
            }
            shakeNo();
            if (appState == STATE_SELECT) drawStatusDot();
            Serial.println("[WS] Disconnected");
            break;

        case WStype_CONNECTED:
            wsConnected = true;
            M5.Power.setLed(activeMode != MODE_NONE ? 200 : 0);
            if (avatarInited) {
                avatar.setExpression(Expression::Happy);
                avatar.setSpeechText("Nyx online!");
            }
            nodYes();
            if (appState == STATE_SELECT) drawStatusDot();
            // Re-announce mode context on reconnect
            if (activeMode != MODE_NONE) sendMessage(MODES[activeMode].context);
            Serial.println("[WS] Connected");
            break;

        case WStype_TEXT: {
            String raw = String((char*)payload);
            StaticJsonDocument<2048> doc;
            if (deserializeJson(doc, raw)) break;

            if (doc["status"] == "thinking") {
                avatar.setExpression(Expression::Doubt);
                avatar.setSpeechText("Thinking...");
            }

            if (doc.containsKey("servo")) {
                String cmd = doc["servo"].as<String>();
                if (cmd == "nod")   nodYes();
                if (cmd == "shake") shakeNo();
            }

            if (doc.containsKey("response")) {
                String response = doc["response"].as<String>();
                String emotion  = doc["emotion"] | "neutral";

                Expression expr = Expression::Neutral;
                if      (emotion == "happy")    expr = Expression::Happy;
                else if (emotion == "thinking") expr = Expression::Doubt;
                else if (emotion == "sad")      expr = Expression::Sad;
                else if (emotion == "angry")    expr = Expression::Angry;

                avatar.setExpression(expr);
                String display = response.length() > 32
                    ? response.substring(0, 32) + "..."
                    : response;
                avatar.setSpeechText(display.c_str());
                Serial.println("[Ph3b3] " + response);
            }
            break;
        }

        default: break;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Mode transitions
// ═══════════════════════════════════════════════════════════════════════════════

void enterMode(Mode m) {
    activeMode = m;
    appState   = STATE_ACTIVE;

    startAvatar();
    avatar.setExpression(Expression::Happy);
    avatar.setSpeechText(MODES[m].id);

    sendMessage(MODES[m].context);
    M5.Power.setLed(wsConnected ? 200 : 50);

    Serial.printf("[Mode] -> %s\n", MODES[m].id);
}

void exitToSelect() {
    activeMode = MODE_NONE;
    appState   = STATE_SELECT;
    M5.Power.setLed(0);
    showModeSelector();
    Serial.println("[Mode] -> SELECT");
}

// ═══════════════════════════════════════════════════════════════════════════════
// WiFi
// ═══════════════════════════════════════════════════════════════════════════════

bool connectWiFi() {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    int tries = 0;
    while (WiFi.status() != WL_CONNECTED && tries++ < 40) {
        delay(500);
        Serial.print(".");
    }
    bool ok = WiFi.status() == WL_CONNECTED;
    if (ok) Serial.println("\n[WiFi] " + WiFi.localIP().toString());
    else    Serial.println("\n[WiFi] failed");
    return ok;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Setup
// ═══════════════════════════════════════════════════════════════════════════════

void setup() {
    auto cfg = M5.config();
    M5.begin(cfg);

    // M5.begin() initialises the AXP2101 PMIC and the display controller, but
    // on CoreS3 the backlight LDO (DLDO1) can glitch if setBrightness() is
    // called before the light object has completed its own init sequence inside
    // M5GFX. Calling Display.begin() explicitly forces the full controller +
    // backlight init path to run to completion, giving us a clean, stable state
    // before we draw anything. Without this the screen flashes briefly on reset
    // then goes dark because the DLDO1 enable bit gets toggled off mid-init.
    M5.Display.begin();
    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setBrightness(200);

    // Serial already started by M5.begin() via cfg.serial_baudrate = 115200.
    Serial.println("[Ph3b3] Boot");

    // Servos
    panServo.attach(PAN_PIN);
    tiltServo.attach(TILT_PIN);
    panServo.write(PAN_CENTER);
    tiltServo.write(TILT_CENTER);

    // Boot screen shown before avatar inits so we own the display
    showBoot();
    bool wifiOk = connectWiFi();
    updateBootStatus(wifiOk);

    // WebSocket (begins trying immediately; events handled async)
    webSocket.begin(PH3B3_HOST, PH3B3_PORT, PH3B3_PATH);
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(3000);
    webSocket.enableHeartbeat(15000, 3000, 2);

    // Transition to mode selector
    appState = STATE_SELECT;
    showModeSelector();
}

// ═══════════════════════════════════════════════════════════════════════════════
// Loop
// ═══════════════════════════════════════════════════════════════════════════════

void loop() {
    M5.update();
    webSocket.loop();

    // ── Touch ────────────────────────────────────────────────────────────────
    auto touch = M5.Touch.getDetail();
    if (touch.wasPressed()) {
        int16_t tx = touch.x, ty = touch.y;

        if (appState == STATE_SELECT) {
            for (int i = 0; i < TILE_COUNT; i++) {
                const Tile& t = TILES[i];
                if (tx >= t.x && tx < t.x + t.w && ty >= t.y && ty < t.y + t.h) {
                    drawTile(t, true);   // press flash
                    delay(120);
                    enterMode(t.mode);
                    break;
                }
            }
        }
    }

    // ── Hardware buttons ──────────────────────────────────────────────────────
    // BtnA — generic prompt
    if (M5.BtnA.wasPressed() && appState == STATE_ACTIVE) {
        sendMessage("Ph3b3, say something.");
    }

    // BtnB — back to mode select (works from any active state)
    if (M5.BtnB.wasPressed() && appState == STATE_ACTIVE) {
        exitToSelect();
    }

    // BtnC — mode-specific shortcut
    if (M5.BtnC.wasPressed() && appState == STATE_ACTIVE && activeMode != MODE_NONE) {
        sendMessage(MODES[activeMode].btnC);
    }

    delay(10);
}
