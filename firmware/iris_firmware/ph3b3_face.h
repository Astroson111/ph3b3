// ph3b3_face.h
// Iris face — built from the ground up on M5GFX. No m5stack-avatar.
// Mood lives in openness, color, and gaze; never an angled brow, so she
// never scowls by accident. Renders to an off-screen canvas (flicker-free)
// and is resolution-agnostic (reads M5.Display dimensions at begin()).
//
// Usage:
//   #include "ph3b3_face.h"
//   Ph3b3Face face;
//   void setup(){ auto c=M5.config(); M5.begin(c); M5.Display.setRotation(0); face.begin(); }
//   void loop(){
//     M5.update();
//     // drive her from connection + voice state:
//     //   joining wifi      -> face.setState(Ph3b3Face::CONNECTING)
//     //   connected, idle   -> face.setState(Ph3b3Face::IDLE)
//     //   mic capturing     -> face.setState(Ph3b3Face::LISTENING)
//     //   POST in flight    -> face.setState(Ph3b3Face::THINKING)
//     //   playing TTS reply -> face.setState(Ph3b3Face::SPEAKING)
//     //   fault / offline   -> face.setState(Ph3b3Face::ERROR)
//     face.setStatusLine(WiFi.localIP().toString());
//     face.update();                       // call every loop
//   }
// When you wire ES8311 playback, feed real amplitude so she lip-syncs her
// own voice:  face.setSpeakingLevel(rms01);  // 0.0 .. 1.0 each audio chunk

#pragma once
#include <M5Unified.h>

class Ph3b3Face {
 public:
  enum State { BOOT, CONNECTING, IDLE, LISTENING, THINKING, SPEAKING, ERROR };

  void begin() {
    W = M5.Display.width();
    H = M5.Display.height();
    cx = W / 2;
    eyeR   = max(8, (int)(W * 0.20f));
    eyeGap = (int)(W * 0.27f);
    eyeY   = (int)(H * 0.34f);
    mouthY = (int)(H * 0.56f);
    crestY = (int)(H * 0.13f);
    canvas.setColorDepth(16);
    canvas.createSprite(W, H);
    uint32_t now = millis();
    nextBlinkMs  = now + 1500;
    nextGlanceMs = now + 1000;
  }

  void setState(State s) { state = s; }
  void setStatusLine(const String& s) { statusLine = s; }
  void setSpeakingLevel(float level01) {       // call from audio playback
    lastLevel = constrain(level01, 0.f, 1.f);
    lastLevelMs = millis();
  }

  void update() {
    uint32_t now = millis();
    float t = now / 1000.0f;

    // --- breath bob ---
    breath = sinf(t * 6.2832f / 3.0f) * 1.6f;

    // --- blink (quick close/open, then schedule the next) ---
    if (blinkStart == 0 && now > nextBlinkMs) blinkStart = now;
    if (blinkStart != 0) {
      float k = (now - blinkStart) / 140.0f;
      blink = k < 1.0f ? sinf(k * 3.1416f) : 0.0f;
      if (k >= 1.0f) { blinkStart = 0; nextBlinkMs = now + 2200 + random(3000); }
    }

    // --- gaze drift (the "alive" tell) ---
    if (now > nextGlanceMs) {
      gTX = ((random(200) / 100.0f) - 1.0f) * eyeR * 0.28f;
      gTY = ((random(200) / 100.0f) - 1.0f) * eyeR * 0.20f;
      nextGlanceMs = now + 1500 + random(2700);
    }
    glanceX += (gTX - glanceX) * 0.07f;
    glanceY += (gTY - glanceY) * 0.07f;

    // --- mouth target ---
    float target = 0.0f;
    if (now - lastLevelMs < 300) target = lastLevel;          // real audio
    else if (state == SPEAKING) target = fabsf(sinf(t * 9.0f)) * 0.9f + 0.05f;
    else if (state == LISTENING) target = 0.12f + fabsf(sinf(t * 3.0f)) * 0.10f;
    speak += (target - speak) * 0.25f;

    render(t);
  }

 private:
  M5Canvas canvas{&M5.Display};
  int W = 0, H = 0, cx = 0, eyeR = 0, eyeGap = 0, eyeY = 0, mouthY = 0, crestY = 0;
  State state = BOOT;
  float blink = 0, breath = 0, glanceX = 0, glanceY = 0, gTX = 0, gTY = 0, speak = 0;
  uint32_t blinkStart = 0, nextBlinkMs = 0, nextGlanceMs = 0, lastLevelMs = 0;
  float lastLevel = 0;
  String statusLine;

  struct Pal { uint8_t cr, cg, cb, hr, hg, hb, mr, mg, mb; float open; const char* label; };

  Pal pal() {
    switch (state) {
      case CONNECTING: return {180,210,225, 24,40,52, 120,160,180, 0.62f, "connecting"};
      case IDLE:       return {120,228,255, 14,58,82, 120,228,255, 1.00f, "ready"};
      case LISTENING:  return {170,245,255, 24,96,128,150,235,255, 1.12f, "listening"};
      case THINKING:   return {182,150,255, 48,30,92, 150,130,210, 0.86f, "thinking"};
      case SPEAKING:   return {140,236,255, 18,72,98, 150,238,255, 1.00f, "speaking"};
      case ERROR:      return {255,128,72,  58,20,12, 210,110,70,  0.52f, "offline"};
      default:         return {110,150,170, 12,28,40, 110,150,170, 0.55f, "waking"};
    }
  }

  uint16_t C(uint8_t r, uint8_t g, uint8_t b) { return M5.Display.color565(r, g, b); }

  void drawEye(int ex, int ey, const Pal& p, float open) {
    float rx = eyeR, ry = eyeR * 1.18f * open;
    if (ry < 2.5f) {                                   // closed: glowing dash
      canvas.fillSmoothRoundRect(ex - rx * 0.85f, ey - 1, rx * 1.7f, 3, 1, C(p.cr,p.cg,p.cb));
      return;
    }
    canvas.fillEllipse(ex, ey, rx + 5, ry + 5, C(p.hr,p.hg,p.hb));        // halo
    canvas.fillEllipse(ex, ey, rx, ry, C(p.cr*0.32, p.cg*0.32, p.cb*0.32)); // dim body
    int px = ex + glanceX, py = ey + glanceY;                            // pupil core
    float pr = rx * 0.60f, pry = min(ry * 0.78f, rx * 0.68f);
    canvas.fillEllipse(px, py, pr, pry, C(p.cr, p.cg, p.cb));
    canvas.fillEllipse(px, py, pr * 0.6f, pry * 0.6f,
                       C(min(255,p.cr+60), min(255,p.cg+30), min(255,p.cb+10)));
    canvas.fillSmoothCircle(px - rx * 0.22f, py - ry * 0.22f, max(1.0f, rx * 0.13f),
                            C(255,255,255));           // hot highlight
  }

  void render(float t) {
    Pal p = pal();
    canvas.fillScreen(TFT_BLACK);

    // lunar crest signature — brightens while listening
    float k = (state == LISTENING) ? 1.0f : 0.42f;
    float cr = W * 0.058f;
    canvas.fillSmoothCircle(cx, crestY, cr, C(p.cr*k, p.cg*k, p.cb*k));
    canvas.fillSmoothCircle(cx + cr*0.55f, crestY - cr*0.18f, cr, TFT_BLACK); // carve crescent

    float open = max(0.0f, p.open * (1.0f - blink));
    int oy = (int)breath;
    drawEye(cx - eyeGap, eyeY + oy, p, open);
    drawEye(cx + eyeGap, eyeY + oy, p, open);

    // mouth — restrained rounded bar, opens with speech
    float mw = W * 0.20f, mh = 3 + speak * 15;
    canvas.fillSmoothRoundRect(cx - mw/2 - 2, mouthY - mh/2 - 2 + oy, mw + 4, mh + 4,
                               (mh + 4) / 2, C(p.mr*0.30, p.mg*0.30, p.mb*0.30));
    canvas.fillSmoothRoundRect(cx - mw/2, mouthY - mh/2 + oy, mw, mh,
                               mh / 2, C(p.mr, p.mg, p.mb));

    // status line
    canvas.setTextColor(C(120,150,165), TFT_BLACK);
    canvas.setTextDatum(bottom_center);
    canvas.setTextSize(1);
    canvas.drawString(statusLine.length() ? statusLine : String(p.label), cx, H - 6);

    canvas.pushSprite(0, 0);
  }
};
