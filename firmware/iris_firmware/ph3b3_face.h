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
  void setSpeakingLevel(float level01) {       // call from audio playback
    lastLevel = constrain(level01, 0.f, 1.f);
    lastLevelMs = millis();
  }

  void setBubble(const String& text) {
    _bubbleGrowing    = true;
    _bubbleCollapsing = false;
    _bubbleStartMs    = millis();
    _bscrollLine      = 0;
    _bscrollLastMs    = _bubbleStartMs;
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
    for (int j = 0; j < 8;  j++) { _starX[j]=random(100); _starY[j]=random(100); _starBright[j]=false; }
    for (int j = 8; j < 10; j++) { _starX[j]=random(100); _starY[j]=random(100); _starBright[j]=true;  }
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
    // LISTENING: lock pupils to center (eye contact) and ease smoothly toward it.
    // All other states: normal randomised drift.
    if (state == LISTENING) {
      gTX = 0.0f;
      gTY = 0.0f;
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
  static constexpr int _BCOLS = 19;    // chars/line: (127-10)/6 at textSize 1, below-mouth bubble
  static constexpr int _BMAX  = 60;
  float    _bubbleProgress   = 0.0f;
  bool     _bubbleGrowing    = false;
  bool     _bubbleCollapsing = false;
  uint32_t _bubbleStartMs    = 0;
  uint32_t _bubbleCollapseMs = 0;
  uint8_t  _starX[10]        = {};
  uint8_t  _starY[10]        = {};
  bool     _starBright[10]   = {};
  char     _blines[60][20]   = {};    // 19 chars + null per line
  int      _blineCount = 0, _bscrollLine = 0;
  uint32_t _bscrollLastMs = 0;
  uint32_t blinkStart = 0, nextBlinkMs = 0, nextGlanceMs = 0, lastLevelMs = 0;
  float lastLevel = 0;
  String statusLine;

  struct Pal { uint8_t cr, cg, cb, hr, hg, hb, mr, mg, mb; float open; const char* label; };

  Pal pal() {
    switch (state) {
      //                 iris──────────  halo──────────  mouth─────────  open   label
      case CONNECTING: return {100, 80,200,  16,12, 50,  80, 70,170, 0.62f, "connecting"};
      case IDLE:       return {255, 60,155,  65, 8, 28, 255, 60,155, 1.00f, "ready"};
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

    // lunar crest — per-state color + motion; crescent is the only status indicator
    float k, cr_r, cr_g, cr_b;
    switch (state) {
      case CONNECTING:
        k = 0.22f + fabsf(sinf(t * 3.14f)) * 0.28f;   // ~0.5 Hz pulse
        cr_r=100; cr_g=80;  cr_b=200; break;            // cool violet: searching
      case IDLE:
        k = 0.50f;
        cr_r=155; cr_g=60;  cr_b=255; break;            // iris violet: ready
      case LISTENING:
        k = 0.58f + fabsf(sinf(t * 6.28f)) * 0.42f;   // 1 Hz pulse — most active ★
        cr_r=210; cr_g=140; cr_b=255; break;            // bright lavender: recording
      case THINKING:
        k = 0.60f + fabsf(sinf(t * 1.8f)) * 0.20f;    // slow throb + spinning carve below
        cr_r=255; cr_g=80;  cr_b=180; break;            // magenta: working
      case SPEAKING:
        k = 0.50f + speak * 0.50f;                      // amplitude-synced
        cr_r=255; cr_g=140; cr_b=220; break;            // warm pink: talking
      case ERROR:
        k = 0.60f + fabsf(sinf(t * 2.5f)) * 0.40f;    // fast alarming pulse
        cr_r=255; cr_g=55;  cr_b=20;  break;            // red-amber: offline/fault
      default:
        k = 0.30f;
        cr_r=80;  cr_g=60;  cr_b=140; break;
    }
    float cr = min(W, H) * 0.058f;
    canvas.fillSmoothCircle(cx, crestY, cr,
        C((uint8_t)(cr_r*k), (uint8_t)(cr_g*k), (uint8_t)(cr_b*k)));
    // THINKING: carve orbits the circle (spinning crescent = "working")
    // All other states: static carve in the standard position
    if (state == THINKING) {
        float cOff = cr * 0.58f, ang = t * 1.2f;
        canvas.fillSmoothCircle(cx + cOff*cosf(ang), crestY + cOff*sinf(ang), cr, TFT_BLACK);
    } else {
        canvas.fillSmoothCircle(cx + cr*0.55f, crestY - cr*0.18f, cr, TFT_BLACK);
    }

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

    if (_bubbleProgress > 0.0f) _drawBubble();
    canvas.pushSprite(0, 0);
  }

  void _drawBubble() {
    // Bubble sits BELOW the mouth; tail tip points up at mouthY.
    // Iris 135×240 portrait: mouthY=175, H=240.
    // Full-size: bw=127, by=183→236 (53px), tail tip=(cx,175), base=(cx±thw,183).
    const int TAIL_H  = 8;
    const int tailTY  = mouthY + TAIL_H;   // bubble top / tail base Y  (183)
    const int BH_FULL = H - tailTY - 4;    // grows to near bottom       (53)
    const int BW_FULL = W - 8;             // 127
    const int CR      = 6;

    float p = _bubbleProgress;

    int bh = max(2, (int)(BH_FULL * p));
    int bw = max(2, (int)(BW_FULL * p));
    int bx = cx - bw / 2;
    int by = tailTY;                        // top edge fixed; bubble grows downward

    uint16_t fill = C(14,  6, 38);
    uint16_t rim  = C(200, 225, 255);
    uint16_t tc   = C(230, 248, 255);
    uint16_t sdim = C(100, 120, 200);
    uint16_t sbrt = C(255, 255, 255);

    // Tail: tip at mouth, base at bubble top
    int thw = max(2, (int)(10 * min(1.0f, p * 4)));
    canvas.fillTriangle(cx, mouthY, cx - thw, tailTY, cx + thw, tailTY, fill);
    canvas.drawLine(cx, mouthY, cx - thw, tailTY, rim);
    canvas.drawLine(cx, mouthY, cx + thw, tailTY, rim);

    // Bubble body: grows downward from tailTY
    int eff_cr = min(CR, bh / 3);
    canvas.fillRoundRect(bx, by, bw, bh, eff_cr, fill);
    canvas.drawRoundRect(bx, by, bw, bh, eff_cr, rim);

    if (p < 0.45f) return;

    for (int i = 0; i < 10; i++) {
      int sx = bx + 3 + (_starX[i] * (bw - 6) / 100);
      int sy = by + 3 + (_starY[i] * (bh - 6) / 100);
      if (sx < bx+2 || sx > bx+bw-3 || sy < by+2 || sy > by+bh-3) continue;
      if (_starBright[i]) canvas.fillSmoothCircle(sx, sy, 1, sbrt);
      else                canvas.drawPixel(sx, sy, sdim);
    }

    if (p < 0.90f) return;

    // 5 visible rows at textSize 1 (8px/line, 5px pad top+bottom)
    const int TXT_PAD = 5;
    const int ROWS    = (BH_FULL - TXT_PAD * 2) / 8;

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
