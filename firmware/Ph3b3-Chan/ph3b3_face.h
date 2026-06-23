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
  enum State { BOOT, CONNECTING, IDLE, LISTENING, THINKING, SPEAKING, ERROR, FOCUSED };

  // w/h = 0 → use full display; pass explicit values for split-screen layouts
  void begin(int w = 0, int h = 0) {
    W = w > 0 ? w : M5.Display.width();
    H = h > 0 ? h : M5.Display.height();
    cx = W / 2;
    // Portrait (H > W): keep original W-based formula — tuned for Iris 135×240.
    // Landscape (W ≥ H): switch to H-based so eyes don't dominate the wider canvas.
    bool portrait = H > W;
    eyeR   = max(8, portrait ? (int)(W * 0.20f) : (int)(H * 0.11f));
    eyeGap = portrait ? (int)(W * 0.27f) : max(eyeR + 10, (int)(W * 0.16f));
    crestY = (int)(H * 0.26f);  // was 0.13 — shifted down for vertical centering
    eyeY   = (int)(H * 0.49f);  // was 0.36 — maintains crest→eye spacing
    mouthY = (int)(H * 0.73f);  // was 0.58/0.60 — maintains eye→mouth spacing
    Serial.printf("[face] W=%d H=%d portrait=%d eyeR=%d gap=%d eyeY=%d mouthY=%d\n",
                  W, H, (int)portrait, eyeR, eyeGap, eyeY, mouthY);
    canvas.deleteSprite();
    canvas.setColorDepth(16);
    canvas.createSprite(W, H);
    uint32_t now = millis();
    nextBlinkMs  = now + 1500;
    nextGlanceMs = now + 1000;
  }

  void  setState(State s) { state = s; }
  State getState()  const { return state; }
  void setStatusLine(const String& s) { statusLine = s; }
  void setStatusVisible(bool v)        { _showStatus = v; }
  void setCrescentTabVisible(bool v)   { _showCrescentTab = v; }
  void setCrescentTabHighlight(bool v) { _crescentTabHighlight = v; }
  void setSpeakingLevel(float level01) {       // call from audio playback
    lastLevel = constrain(level01, 0.f, 1.f);
    lastLevelMs = millis();
  }

  void setGaze(float yaw, float pitch) {
    _gazeYaw    = constrain(yaw,   -1.0f, 1.0f);
    _gazePitch  = constrain(pitch, -1.0f, 1.0f);
    _gazeLocked = true;
  }
  void  releaseGaze()         { _gazeLocked = false; }
  bool  isGazeLocked()  const { return _gazeLocked; }
  float getGazeYaw()    const { return _gazeYaw; }
  float getGazePitch()  const { return _gazePitch; }

  void setBubble(const String& text) {
    _bubbleGrowing    = true;
    _bubbleCollapsing = false;
    _bubbleStartMs    = millis();
    _bscrollLine      = 0;
    _bscrollLastMs    = _bubbleStartMs;
    // Pre-wrap text into fixed char array; stable for entire SPEAKING turn
    _blineCount = 0;
    int i = 0, len = (int)text.length();
    while (i < len && _blineCount < _BMAX) {
      while (i < len && text[i] == ' ') i++;
      if (i >= len) break;
      int end = min(len, i + _BCOLS);
      if (end < len) {
        int brk = end;
        while (brk > i && text[brk] != ' ') brk--;
        if (brk > i) end = brk;
      }
      int n = end - i;
      if (n > _BCOLS) n = _BCOLS;
      if (n > 0) {
        strncpy(_blines[_blineCount], text.c_str() + i, n);
        while (n > 0 && _blines[_blineCount][n-1] == ' ') n--;
        _blines[_blineCount][n] = '\0';
        if (n > 0) _blineCount++;
      }
      i = end;
    }
    // Scatter 15 dim + 3 bright stars; stable layout per reply
    for (int j = 0; j < 15; j++) { _starX[j]=random(100); _starY[j]=random(100); _starBright[j]=false; }
    for (int j = 15; j < 18; j++) { _starX[j]=random(100); _starY[j]=random(100); _starBright[j]=true; }
  }
  void clearBubble() {
    if (_bubbleGrowing || _bubbleProgress > 0.0f) {
      _bubbleGrowing    = false;
      _bubbleCollapsing = true;
      _bubbleCollapseMs = millis();
    }
  }

  void update() {
    uint32_t now = millis();
    float t = now / 1000.0f;

    // --- breath bob ---
    breath = sinf(t * 6.2832f / 3.0f) * 1.6f;

    // --- blink: 90ms close, 70ms dwell, 90ms open → 250ms total ---
    if (blinkStart == 0 && now > nextBlinkMs) blinkStart = now;
    if (blinkStart != 0) {
      float k = (float)(now - blinkStart);
      blink = (k < 90.f)  ? k / 90.f :
              (k < 160.f) ? 1.0f :
              (k < 250.f) ? 1.0f - (k - 160.f) / 90.f : 0.0f;
      if (k >= 250.f) { blinkStart = 0; nextBlinkMs = now + 2200 + random(3000); }
    }

    // --- gaze drift / eye contact ---
    // _gazeLocked overrides all state-driven drift; orthogonal to expression FSM.
    if (_gazeLocked) {
      gTX =  _gazeYaw   * eyeR * 0.40f;
      gTY = -_gazePitch * eyeR * 0.28f;  // screen Y inverts: pitch +1 = up = gTY negative
    } else if (state == LISTENING) {
      gTX = 0.0f;
      gTY = 0.0f;
    } else if (state == THINKING) {
      // Slow upward-right drift — looking up in thought
      if (now > nextGlanceMs) {
        gTX = eyeR * 0.20f;
        gTY = -eyeR * 0.25f;
        nextGlanceMs = now + 2000 + random(1500);
      }
    } else if (now > nextGlanceMs) {
      gTX = ((random(200) / 100.0f) - 1.0f) * eyeR * 0.40f;
      gTY = ((random(200) / 100.0f) - 1.0f) * eyeR * 0.28f;
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

    // Bubble grow/collapse — smoothstepped; runs only when animation is active
    if (_bubbleGrowing) {
      float raw = (float)(now - _bubbleStartMs) / 280.0f;
      float pp  = min(1.0f, raw);
      _bubbleProgress = pp*pp*(3.0f - 2.0f*pp);
      if (raw >= 1.0f) _bubbleGrowing = false;
    } else if (_bubbleCollapsing) {
      float raw = 1.0f - (float)(now - _bubbleCollapseMs) / 200.0f;
      float pp  = max(0.0f, raw);
      _bubbleProgress = pp*pp*(3.0f - 2.0f*pp);
      if (raw <= 0.0f) { _bubbleCollapsing = false; _bubbleProgress = 0.0f; }
    }

    render(t);
  }

 private:
  M5Canvas canvas{&M5.Display};
  int W = 0, H = 0, cx = 0, eyeR = 0, eyeGap = 0, eyeY = 0, mouthY = 0, crestY = 0;
  State state = BOOT;
  float blink = 0, breath = 0, glanceX = 0, glanceY = 0, gTX = 0, gTY = 0, speak = 0;
  bool  _gazeLocked = false;
  float _gazeYaw = 0.0f, _gazePitch = 0.0f;
  // Bubble animation + content state
  static constexpr int _BCOLS = 46;   // chars per wrapped line at textSize 1 (6px each, 280px wide)
  static constexpr int _BMAX  = 60;   // max wrapped lines stored
  float    _bubbleProgress   = 0.0f;
  bool     _bubbleGrowing    = false;
  bool     _bubbleCollapsing = false;
  uint32_t _bubbleStartMs    = 0;
  uint32_t _bubbleCollapseMs = 0;
  uint8_t  _starX[18]        = {};    // relative star x, 0..99
  uint8_t  _starY[18]        = {};    // relative star y, 0..99
  bool     _starBright[18]   = {};    // true → bright circle, false → dim pixel
  char     _blines[60][47]   = {};    // pre-wrapped text lines
  int      _blineCount       = 0;
  int      _bscrollLine      = 0;
  uint32_t _bscrollLastMs    = 0;
  uint32_t blinkStart = 0, nextBlinkMs = 0, nextGlanceMs = 0, lastLevelMs = 0;
  float lastLevel = 0;
  String statusLine;
  bool _showStatus         = true;
  bool _showCrescentTab    = false;
  bool _crescentTabHighlight = false;

  struct Pal { uint8_t cr, cg, cb, hr, hg, hb, mr, mg, mb; float open; const char* label; };

  Pal pal() {
    switch (state) {
      //                 iris──────────  halo──────────  mouth─────────  open   label
      case CONNECTING: return {100, 80,200,  16,12, 50,  80, 70,170, 0.62f, "connecting"};
      case IDLE:       return {155, 60,255,  28, 8, 65, 155, 60,255, 1.00f, "ready"};
      case LISTENING:  return {200,120,255,  40,18, 80, 180,100,245, 1.12f, "listening"};
      case THINKING:   return {255, 80,180,  58,10, 42, 220, 70,160, 0.86f, "thinking"};
      case SPEAKING:   return {255,140,220,  50,18, 60, 240,110,200, 1.00f, "speaking"};
      case ERROR:      return { 60,120,255,  10,18, 65,  80,140,255, 0.52f, "offline"};
      case FOCUSED:    return { 60,210,175,   8,52,42,  50,190,160, 0.78f, "watching"};
      default:         return { 80, 60,140,  10, 8, 30,  80, 60,140, 0.55f, "waking"};
    }
  }

  // BGR swap: StickS3 needs R↔B flip; CoreS3 likely doesn't.
  // If eyes render orange on CoreS3, define SC_FACE_BGR before including this header.
#ifdef SC_FACE_BGR
  uint16_t C(uint8_t r, uint8_t g, uint8_t b) { return M5.Display.color565(b, g, r); }
#else
  uint16_t C(uint8_t r, uint8_t g, uint8_t b) { return M5.Display.color565(r, g, b); }
#endif

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
    float cr = min(W, H) * 0.058f;   // was W — landscape was too large
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

    // status line (suppressed for face-only mode)
    if (_showStatus) {
      canvas.setTextColor(C(120,150,165), TFT_BLACK);
      canvas.setTextDatum(bottom_center);
      canvas.setTextSize(1);
      canvas.drawString(statusLine.length() ? statusLine : String(p.label), cx, H - 6);
    }

    // corner crescent tab — drawn on canvas so it survives every pushSprite.
    // Color by state so it doubles as a recording/thinking indicator.
    if (_showCrescentTab) {
      int tcx = 22, tcy = 22;
      float tr = 14.0f;
      uint8_t br, bg, bb;
      if (_crescentTabHighlight) {
        br = 200; bg = 100; bb = 255;  // menu open: bright purple
      } else if (state == LISTENING) {
        // Pulse red — "I'm recording, talk now"
        float pulse = 0.5f + 0.5f * sinf(t * 7.0f);
        br = (uint8_t)(120 + 100 * pulse);
        bg = (uint8_t)(10);
        bb = (uint8_t)(15);
      } else if (state == THINKING) {
        br = 220; bg = 130; bb = 20;   // amber — "processing"
      } else {
        // Slow breathing pulse — signals "always listening" in idle/awaiting state
        float pulse = 0.5f + 0.5f * sinf(t * 1.5f);
        br = (uint8_t)(50 + 40 * pulse);
        bg = (uint8_t)(28 + 20 * pulse);
        bb = (uint8_t)(120 + 60 * pulse);
      }
      canvas.fillSmoothCircle(tcx, tcy, tr, C(br, bg, bb));
      canvas.fillSmoothCircle(tcx + (int)(tr * 0.55f), tcy - (int)(tr * 0.18f),
                              tr, TFT_BLACK);
    }

    if (_bubbleProgress > 0.0f) _drawBubble();
    canvas.pushSprite(0, 0);
  }

  void _drawBubble() {
    // Bubble occupies the upper face region; tail wedge roots at mouth centre.
    // Full-size geometry for CoreS3 landscape (320×240, mouthY=175):
    //   bubble  x=8..312  y=8..167  (159×304 px)
    //   tail    tip=(160,175)  base=(146,167)..(174,167)
    const int CR      = 12;
    const int TAIL_H  = 8;
    const int tailBY  = mouthY - TAIL_H;   // 167 — bubble bottom / tail base
    const int BH_FULL = tailBY - 8;        // 159
    const int BW_FULL = W - 16;            // 304

    float p = _bubbleProgress;

    // Animated dims: scales from point at mouth anchor, grows upward + outward
    int bh = max(2, (int)(BH_FULL * p));
    int bw = max(2, (int)(BW_FULL * p));
    int bx = cx - bw / 2;
    int by = tailBY - bh;

    // Colors — all via C(r,g,b) matching existing face color helper
    uint16_t fill = C(14,  6, 38);     // deep indigo fill
    uint16_t rim  = C(200, 225, 255);  // luminous moon-white / pale-cyan rim
    uint16_t tc   = C(230, 248, 255);  // near-white text
    uint16_t sdim = C(100, 120, 200);  // dim star (lavender)
    uint16_t sbrt = C(255, 255, 255);  // bright star (pure white)

    // Tail wedge: tip fixed at mouth, base on animated bubble bottom
    int thw = max(2, (int)(14 * min(1.0f, p * 4)));  // full width by p≈0.25
    canvas.fillTriangle(cx, mouthY, cx - thw, tailBY, cx + thw, tailBY, fill);
    canvas.drawLine(cx, mouthY, cx - thw, tailBY, rim);
    canvas.drawLine(cx, mouthY, cx + thw, tailBY, rim);

    // Bubble body: flat deep-indigo fill + 1px luminous rim
    int eff_cr = min(CR, bh / 3);
    canvas.fillRoundRect(bx, by, bw, bh, eff_cr, fill);
    canvas.drawRoundRect(bx, by, bw, bh, eff_cr, rim);

    if (p < 0.45f) return;   // too small for content — shell only

    // Stars: 15 dim specks (drawPixel) + 3 bright circles (fillSmoothCircle r=2)
    for (int i = 0; i < 18; i++) {
      int sx = bx + 4 + (_starX[i] * (bw - 8) / 100);
      int sy = by + 4 + (_starY[i] * (bh - 8) / 100);
      if (sx < bx+2 || sx > bx+bw-3 || sy < by+2 || sy > by+bh-3) continue;
      if (_starBright[i]) canvas.fillSmoothCircle(sx, sy, 2, sbrt);
      else                canvas.drawPixel(sx, sy, sdim);
    }

    if (p < 0.90f) return;   // text fades in near full size only

    // Text: word-wrapped lines, line-step scroll when reply exceeds visible rows
    const int TXT_PAD = 12;
    const int ROWS    = (BH_FULL - TXT_PAD * 2) / 8;   // 16 rows at full size

    uint32_t now2 = millis();
    if (_blineCount > ROWS && (now2 - _bscrollLastMs) >= 1400) {
      if (_bscrollLine + ROWS < _blineCount) { _bscrollLine++; _bscrollLastMs = now2; }
    }

    canvas.setTextSize(1);
    canvas.setTextColor(tc, fill);
    canvas.setTextDatum(top_left);
    for (int r = 0; r < ROWS && (_bscrollLine + r) < _blineCount; r++) {
      canvas.drawString(_blines[_bscrollLine + r], bx + TXT_PAD, by + TXT_PAD + r * 8);
    }
  }
};
