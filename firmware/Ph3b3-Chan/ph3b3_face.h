// ph3b3_face.h
// Iris face ported to Stack-Chan / CoreS3 320×240 landscape.
// Same violet aesthetic as ~/Arduino/Iris/face.cpp:
//   deep-indigo disc · bright rim ring · sparkle eyes · magenta arc smile ·
//   blush dots · speech bubble below face.
//
// Geometry vs Iris (135×240 portrait):
//   scale s = FCR/57 ≈ 1.26×  (FCR = H×0.30 = 72px)
//   face disc upper-centre (160,82) → bubble below, grows to y=236
//   bubble overlaps disc bottom by ~34px — deep-indigo fill blends seamlessly.
//
// API is unchanged: all callers (TalkApp, NetworkApp, CrescentMenu) need no edits.
// Color swap: define SC_FACE_BGR before including if eyes render orange.

#pragma once
#include <M5Unified.h>

class Ph3b3Face {
 public:
  enum State { BOOT, CONNECTING, IDLE, LISTENING, THINKING, SPEAKING, ERROR, FOCUSED };

  // w/h = 0 → use full display dimensions.
  void begin(int w = 0, int h = 0) {
    W = w > 0 ? w : M5.Display.width();
    H = h > 0 ? h : M5.Display.height();

    // ── Geometry (all derived from FCR so one number re-centres everything) ──
    FCX   = W / 2 + 4;                         // 164 — nudge right to balance crescent tab
    FCR   = max(30, (int)(H * 0.30f));         // 72 @ 240
    FCY   = (int)(H * 0.42f);                  // 101 — lower for visual vertical centering
    GLOWR = FCR + 8;                        // 80

    float s = (float)FCR / 57.0f;          // scale vs Iris reference (FCR=57)
    LEX   = FCX - (int)(21 * s + 0.5f);   // 134
    REX   = FCX + (int)(21 * s + 0.5f);   // 186
    EYY   = FCY - (int)(4  * s + 0.5f);   // 77
    ESX   = max(8,  (int)(16 * s + 0.5f)); // 20  sclera half-width
    ESY   = max(9,  (int)(17 * s + 0.5f)); // 21  sclera half-height
    EIR   = max(6,  (int)(13 * s + 0.5f)); // 16  iris radius
    MTHY  = FCY + (int)(22 * s + 0.5f);   // 110 mouth baseline

    // Eyelid: face-colour ellipse across top of sclera
    ELID_OFF = max(2, (int)(4 * s + 0.5f));   // 5   Y-offset from sclera top edge
    ELID_RY  = max(4, (int)(7 * s + 0.5f));   // 9   eyelid half-height

    // Blush
    BLSH_OFF = (int)(22 * s + 0.5f);           // 28  X offset from FCX
    BLSH_R   = max(3, (int)(5 * s + 0.5f));    // 6   blush dot radius

    // Mouth arc
    MRAW  = (int)(11 * s + 0.5f);              // 14  flat-mouth half-width
    MRARC = (int)(14 * s + 0.5f);              // 18  arc rx

    // Mouth amplitude — keeps height/width ratio equal to Iris (0.5)
    MBASE = (float)MRARC * 0.50f;              // 9.0  base smile ry
    MSPK  = (float)MRARC * 0.64f;              // 11.5 extra ry at full speak level

    // Mouth line thickness (scaled from Iris's 3/4)
    MLIP   = max(3, (int)(3 * s + 0.5f));      // 4
    MTEETH = max(4, (int)(4 * s + 0.5f));      // 5

    // Sparkle geometry
    SPKL_OX = (int)(3 * s + 0.5f);            // sparkle centre offset X from eye centre
    SPKL_OY = (int)(4 * s + 0.5f);            // sparkle centre offset Y above eye centre
    SPKL_BL = (int)(5 * s + 0.5f);            // bar half-length
    SPKL_SX = (int)(6 * s + 0.5f);            // secondary dot offset X
    SPKL_SY = (int)(4 * s + 0.5f);            // secondary dot offset Y

    // ── Colors — violet palette tuned for CoreS3 ILI9342 with SC_FACE_BGR ──
    // With SC_FACE_BGR, C(r,g,b) → color565(b,g,r) → display shows (R=b, G=g, B=r).
    // To display target (Rd,Gd,Bd): call C(Bd, Gd, Rd).
    C_FACE  = C(0x60, 0x10, 0x30);  // display: R=48,  G=16, B=96  → deep violet
    C_GLOW  = C(0x50, 0x0A, 0x20);  // display: R=32,  G=10, B=80  → dark violet glow
    C_RIM   = C(0xE0, 0x40, 0x90);  // display: R=144, G=64, B=224 → bright violet
    C_EYE   = C(0x32, 0x08, 0x12);  // display: R=18,  G=8,  B=50  → very dark iris
    C_MOUTH = C(0x90, 0x40, 0xE0);  // display: R=224, G=64, B=144 → magenta
    C_BLUSH = C(0x90, 0x60, 0xD0);  // display: R=208, G=96, B=144 → pink blush

    canvas.deleteSprite();
    canvas.setColorDepth(16);
    canvas.createSprite(W, H);
    uint32_t now = millis();
    nextBlinkMs  = now + 1500;
    nextGlanceMs = now + 1000;
  }

  // ── Public API (unchanged from prior version) ────────────────────────────
  void  setState(State s) { state = s; }
  State getState()  const { return state; }
  void  setStatusLine(const String& s) { statusLine = s; }
  void  setStatusVisible(bool v)        { _showStatus = v; }
  void  setCrescentTabVisible(bool v)   { _showCrescentTab = v; }
  void  setCrescentTabHighlight(bool v) { _crescentTabHighlight = v; }

  void setSpeakingLevel(float level01) {
    lastLevel   = constrain(level01, 0.f, 1.f);
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
    _wrapBubble(text);
    for (int j = 0; j < 15; j++) { _starX[j]=random(100); _starY[j]=random(100); _starBright[j]=false; }
    for (int j = 15; j < 18; j++) { _starX[j]=random(100); _starY[j]=random(100); _starBright[j]=true; }
  }

  // Swap the bubble's text WITHOUT re-popping the grow animation. Used to track
  // chunked-TTS audio: each chunk's text is shown while that chunk's audio plays,
  // so the words follow her voice instead of scrolling on a blind fixed timer.
  void setBubbleText(const String& text) {
    if (!_bubbleGrowing && _bubbleProgress <= 0.0f) { setBubble(text); return; }
    _bubbleCollapsing = false;
    _bscrollLine      = 0;
    _bscrollLastMs    = millis();
    _wrapBubble(text);
  }

  void clearBubble() {
    if (_bubbleGrowing || _bubbleProgress > 0.0f) {
      _bubbleGrowing    = false;
      _bubbleCollapsing = true;
      _bubbleCollapseMs = millis();
    }
  }

  // Instant clear — no collapse animation. Use when the caller is about to block
  // rendering (e.g. the tight mic-capture loop), where the animated collapse can't
  // run and would otherwise freeze the stale bubble on-screen through LISTENING.
  void clearBubbleNow() {
    _bubbleGrowing    = false;
    _bubbleCollapsing = false;
    _bubbleProgress   = 0.0f;
  }

  void update() {
    uint32_t now = millis();
    float    t   = now / 1000.0f;

    // ── Breath bob ───────────────────────────────────────────────────────────
    breath = sinf(t * 6.2832f / 3.0f) * 1.6f;

    // ── Blink: 90ms close · 70ms dwell · 90ms open ──────────────────────────
    if (blinkStart == 0 && now > nextBlinkMs) blinkStart = now;
    if (blinkStart != 0) {
      float k = (float)(now - blinkStart);
      blink = (k < 90.f)  ? k / 90.f :
              (k < 160.f) ? 1.0f :
              (k < 250.f) ? 1.0f - (k - 160.f) / 90.f : 0.0f;
      if (k >= 250.f) { blinkStart = 0; nextBlinkMs = now + 2200 + random(3000); }
    }
    if (state == BOOT)      blink = 0.7f;   // heavy-lidded while booting
    if (state == LISTENING) blink = 0.0f;   // eyes wide while recording

    // ── Gaze drift ───────────────────────────────────────────────────────────
    if (_gazeLocked) {
      gTX =  _gazeYaw   * (float)EIR * 0.40f;
      gTY = -_gazePitch * (float)EIR * 0.28f;
    } else if (state == LISTENING) {
      gTX = 0.0f; gTY = 0.0f;               // straight ahead while recording
    } else if (state == THINKING) {
      if (now > nextGlanceMs) {
        gTX = (float)EIR * 0.20f;           // upward-right drift — looking up in thought
        gTY = -(float)EIR * 0.25f;
        nextGlanceMs = now + 2000 + random(1500);
      }
    } else if (now > nextGlanceMs) {
      gTX = ((random(200) / 100.0f) - 1.0f) * (float)EIR * 0.40f;
      gTY = ((random(200) / 100.0f) - 1.0f) * (float)EIR * 0.28f;
      nextGlanceMs = now + 1500 + random(2700);
    }
    glanceX += (gTX - glanceX) * 0.07f;
    glanceY += (gTY - glanceY) * 0.07f;

    // ── Mouth speak level ────────────────────────────────────────────────────
    float target = 0.0f;
    if (now - lastLevelMs < 300) target = lastLevel;
    else if (state == SPEAKING)  target = fabsf(sinf(t * 9.0f)) * 0.9f + 0.05f;
    else if (state == LISTENING) target = 0.12f + fabsf(sinf(t * 3.0f)) * 0.10f;
    speak += (target - speak) * 0.25f;

    // ── Bubble animation ─────────────────────────────────────────────────────
    if (_bubbleGrowing) {
      float raw = (float)(now - _bubbleStartMs) / 280.0f;
      float pp  = min(1.0f, raw);
      _bubbleProgress = pp * pp * (3.0f - 2.0f * pp);
      if (raw >= 1.0f) _bubbleGrowing = false;
    } else if (_bubbleCollapsing) {
      float raw = 1.0f - (float)(now - _bubbleCollapseMs) / 200.0f;
      float pp  = max(0.0f, raw);
      _bubbleProgress = pp * pp * (3.0f - 2.0f * pp);
      if (raw <= 0.0f) { _bubbleCollapsing = false; _bubbleProgress = 0.0f; }
    }

    render(t);
  }

 private:
  M5Canvas canvas{&M5.Display};

  // Word-wrap `text` into _blines[] (shared by setBubble / setBubbleText).
  void _wrapBubble(const String& text) {
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
  }

  // Geometry (computed in begin())
  int W = 0, H = 0;
  int FCX = 0, FCY = 0, FCR = 0, GLOWR = 0;
  int LEX = 0, REX = 0, EYY = 0;
  int ESX = 0, ESY = 0, EIR = 0;
  int MTHY = 0;
  int ELID_OFF = 0, ELID_RY  = 0;
  int BLSH_OFF = 0, BLSH_R   = 0;
  int MRAW = 0, MRARC = 0, MLIP = 0, MTEETH = 0;
  int SPKL_OX = 0, SPKL_OY = 0, SPKL_BL = 0, SPKL_SX = 0, SPKL_SY = 0;
  float MBASE = 0.0f, MSPK = 0.0f;

  // Colors (computed in begin())
  uint16_t C_FACE = 0, C_GLOW = 0, C_RIM = 0, C_EYE = 0, C_MOUTH = 0, C_BLUSH = 0;

  // Animation state
  State state   = BOOT;
  float blink   = 0, breath  = 0;
  float glanceX = 0, glanceY = 0, gTX = 0, gTY = 0;
  float speak   = 0;
  bool  _gazeLocked = false;
  float _gazeYaw = 0.0f, _gazePitch = 0.0f;

  // Bubble content / animation
  static constexpr int _BCOLS = 46;
  static constexpr int _BMAX  = 60;
  float    _bubbleProgress   = 0.0f;
  bool     _bubbleGrowing    = false;
  bool     _bubbleCollapsing = false;
  uint32_t _bubbleStartMs    = 0;
  uint32_t _bubbleCollapseMs = 0;
  uint8_t  _starX[18]      = {};
  uint8_t  _starY[18]      = {};
  bool     _starBright[18] = {};
  char     _blines[60][47] = {};
  int      _blineCount     = 0;
  int      _bscrollLine    = 0;
  uint32_t _bscrollLastMs  = 0;

  uint32_t blinkStart = 0, nextBlinkMs = 0, nextGlanceMs = 0, lastLevelMs = 0;
  float    lastLevel  = 0;
  String   statusLine;
  bool _showStatus           = true;
  bool _showCrescentTab      = false;
  bool _crescentTabHighlight = false;

  // CoreS3 doesn't need BGR swap; define SC_FACE_BGR before include if eyes come up orange.
#ifdef SC_FACE_BGR
  uint16_t C(uint8_t r, uint8_t g, uint8_t b) { return M5.Display.color565(b, g, r); }
#else
  uint16_t C(uint8_t r, uint8_t g, uint8_t b) { return M5.Display.color565(r, g, b); }
#endif

  uint16_t dimC(uint16_t col, float k) {
    if (k >= 1.0f) return col;
    if (k <= 0.0f) return 0;
    uint8_t r = (uint8_t)(((col >> 11) & 0x1F) * k);
    uint8_t g = (uint8_t)(((col >> 5)  & 0x3F) * k);
    uint8_t b = (uint8_t)((col         & 0x1F) * k);
    return (r << 11) | (g << 5) | b;
  }

  // Smile/frown arc: smooth dot sweep along an ellipse.
  void drawMouthArc(int cx, int my, float rx, float ry, uint16_t col, int thick) {
    for (int s = 0; s <= 12; s++) {
      float a  = M_PI * s / 12.0f;
      int   px = cx + (int)(rx * cosf(a));
      int   py = my + (int)(ry * sinf(a));
      canvas.fillSmoothCircle(px, py, thick, col);
    }
  }

  const char* _stateLabel() const {
    switch (state) {
      case BOOT:       return "waking";
      case CONNECTING: return "connecting";
      case IDLE:       return "ready";
      case LISTENING:  return "listening";
      case THINKING:   return "thinking";
      case SPEAKING:   return "speaking";
      case ERROR:      return "offline";
      case FOCUSED:    return "watching";
      default:         return "";
    }
  }

  void render(float t) {
    int oy = (int)breath;  // whole face bobs together

    // ── Per-state expression params ──────────────────────────────────────────
    float faceBright = 1.0f;
    float mouthRY    = MBASE;
    bool  flatMouth  = false;
    bool  frown      = false;

    switch (state) {
      case BOOT:       faceBright = 0.6f;  flatMouth = true;                       break;
      case CONNECTING: faceBright = 0.75f; flatMouth = true;                       break;
      case IDLE:       mouthRY = MBASE + speak * MSPK;                             break;
      case LISTENING:  mouthRY = MBASE * 0.55f + speak * MSPK * 0.4f;             break;
      case THINKING:   faceBright = 0.9f;  flatMouth = true;                       break;
      case SPEAKING:   mouthRY = MBASE + speak * MSPK;                             break;
      case ERROR:      faceBright = 0.5f;  mouthRY = MBASE * 0.55f; frown = true; break;
      case FOCUSED:    faceBright = 0.9f;  mouthRY = MBASE * 0.55f;               break;
    }

    canvas.fillScreen(0x0000);

    // 1 — outer glow
    canvas.fillSmoothCircle(FCX, FCY + oy, GLOWR, dimC(C_GLOW, faceBright * 0.7f));

    // 2 — bright rim ring (visible strip between glow and face disc)
    canvas.fillSmoothCircle(FCX, FCY + oy, FCR + 2, dimC(C_RIM, faceBright));

    // 3 — face disc
    uint16_t cFace = dimC(C_FACE, faceBright);
    canvas.fillSmoothCircle(FCX, FCY + oy, FCR, cFace);

    // 4 — eyes: white sclera → dark iris (gaze-shifted) → face-colour eyelid
    int      ey   = EYY + oy;
    uint16_t cW   = dimC(0xFFFF, faceBright);
    uint16_t cEye = dimC(C_EYE,  faceBright);

    canvas.fillEllipse(LEX, ey, ESX, ESY, cW);
    canvas.fillEllipse(REX, ey, ESX, ESY, cW);

    int gx = (int)glanceX, gy = (int)glanceY;
    canvas.fillSmoothCircle(LEX + gx, ey + 1 + gy, EIR, cEye);
    canvas.fillSmoothCircle(REX + gx, ey + 1 + gy, EIR, cEye);

    // Thick dark anime eyelid across top of sclera
    int elidY = ey - ESY + ELID_OFF;
    canvas.fillEllipse(LEX, elidY, ESX + 2, ELID_RY, cFace);
    canvas.fillEllipse(REX, elidY, ESX + 2, ELID_RY, cFace);

    // 5 — blink: face-colour rect drops from eye top
    if (blink > 0.01f) {
      int bh = max(1, (int)(blink * (ESY * 2 + 4)));
      canvas.fillRect(LEX - ESX - 1, ey - ESY, ESX * 2 + 2, bh, cFace);
      canvas.fillRect(REX - ESX - 1, ey - ESY, ESX * 2 + 2, bh, cFace);
    }

    // 6 — 4-point star sparkle on each iris (hidden during blink)
    if (blink < 0.65f) {
      for (int side = 0; side < 2; side++) {
        int ex2 = (side == 0) ? LEX : REX;
        int sx  = ex2 - SPKL_OX;
        int sy  = ey  - SPKL_OY;
        canvas.fillSmoothCircle(sx, sy, max(1, EIR / 7), cW);
        canvas.fillRect(sx - SPKL_BL, sy - 1, SPKL_BL * 2 + 1, 3, cW);   // horizontal
        canvas.fillRect(sx - 1, sy - SPKL_BL, 3, SPKL_BL * 2 + 1, cW);   // vertical
        canvas.fillSmoothCircle(sx + SPKL_SX, sy + SPKL_SY, max(1, EIR / 14), cW);
      }
    }

    // 7 — blush dots on cheeks
    if (!frown && !flatMouth) {
      uint16_t cBl  = dimC(C_BLUSH, faceBright * 0.55f);
      int      blY  = MTHY - (int)(8 * (float)FCR / 57.0f) + oy;
      canvas.fillSmoothCircle(FCX - BLSH_OFF, blY, BLSH_R, cBl);
      canvas.fillSmoothCircle(FCX + BLSH_OFF, blY, BLSH_R, cBl);
    }

    // 8 — mouth
    uint16_t cMo = dimC(C_MOUTH, faceBright);
    int my = MTHY + oy;
    if (flatMouth) {
      canvas.fillSmoothRoundRect(FCX - MRAW, my, MRAW * 2, 3, 1, cMo);
    } else {
      float ry = frown ? -mouthRY : mouthRY;
      if (frown) {
        drawMouthArc(FCX, my, (float)MRARC, ry, cMo, MLIP);
      } else {
        drawMouthArc(FCX, my - 2, (float)MRARC * 0.78f, ry * 0.45f, cW,  MTEETH); // teeth
        drawMouthArc(FCX, my,     (float)MRARC,          ry,          cMo, MLIP);   // lip
      }
    }

    // 9 — crescent corner tab (top-left UI indicator, state-coloured)
    // Moon phase encodes status: shape varies cutXf offset (0=new, tr*2.8=full).
    if (_showCrescentTab) {
      int   tcx = 22, tcy = 22;
      float tr  = 14.0f;
      uint8_t br, bg, bb;
      float   cutXf = tr * 0.55f;  // default crescent phase
      if (_crescentTabHighlight) {
        br = 200; bg = 100; bb = 255;  // bright purple (panel open)
      } else if (state == CONNECTING) {
        br = 20; bg = 80; bb = 220;   // blue — WiFi searching
        cutXf = fmodf(t * 3.5f, tr * 2.8f);  // cycle new→full as connecting
      } else if (state == LISTENING) {
        br = 220; bg = 200; bb = 20;  // yellow — recording
        // cutXf stays at crescent (default): stage 2 of 3
      } else if (state == THINKING) {
        br = 220; bg = 200; bb = 20;  // yellow — processing
        cutXf = tr * 1.3f;  // half-moon: stage 3 of 3
      } else if (state == SPEAKING) {
        br = 220; bg = 200; bb = 20;  // yellow — responding
        cutXf = tr * 2.2f;  // near-full: stage 3 of 3
      } else {
        float pulse = 0.5f + 0.5f * sinf(t * 1.5f);
        br = (uint8_t)(50 + 40 * pulse);
        bg = (uint8_t)(28 + 20 * pulse);
        bb = (uint8_t)(120 + 60 * pulse);  // slow purple pulse (idle/rest)
      }
      canvas.fillSmoothCircle(tcx, tcy, tr, C(br, bg, bb));
      canvas.fillSmoothCircle(tcx + (int)cutXf, tcy - (int)(tr * 0.18f), tr, TFT_BLACK);
    }

    // 10 — speech bubble (below face, grows downward — mirrors Iris layout)
    if (_bubbleProgress > 0.0f) _drawBubble();

    // 11 — status text just below face disc; blends with bubble fill when active
    if (_showStatus) {
      uint16_t bg = (_bubbleProgress > 0.05f) ? C(14, 6, 38) : (uint16_t)0x0000;
      canvas.setTextColor(C(120, 150, 165), bg);
      canvas.setTextDatum(top_center);
      canvas.setTextSize(1);
      const char* lbl = statusLine.length() ? statusLine.c_str() : _stateLabel();
      canvas.drawString(lbl, FCX, FCY + FCR + 8);  // fixed Y — does not bob
    }

    canvas.pushSprite(0, 0);
  }

  void _drawBubble() {
    const int TAIL_H  = 10;
    const int tailTY  = MTHY + TAIL_H;           // 120 — bubble top / tail base
    const int BH_FULL = H - tailTY - 4;          // 116
    const int BW_FULL = W - 8;                    // 312
    const int CR      = 12;
    const int PAD     = 12;

    float p  = _bubbleProgress;
    int   bh = max(2, (int)(BH_FULL * p));
    int   bw = max(2, (int)(BW_FULL * p));
    int   bx = FCX - bw / 2;
    int   by = tailTY;

    uint16_t fill = C(14,  6,  38);    // deep indigo — matches face disc
    uint16_t rim  = C(200, 225, 255);  // luminous pale-cyan rim
    uint16_t tc   = C(230, 248, 255);  // near-white text
    uint16_t sdim = C(100, 120, 200);  // dim lavender star

    // Tail wedge: tip fixed at mouth, base on bubble top
    int thw = max(2, (int)(14 * min(1.0f, p * 4.0f)));
    canvas.fillTriangle(FCX, MTHY,  FCX - thw, tailTY,  FCX + thw, tailTY,  fill);
    canvas.drawLine(FCX, MTHY, FCX - thw, tailTY, rim);
    canvas.drawLine(FCX, MTHY, FCX + thw, tailTY, rim);

    // Bubble body
    int eff_cr = min(CR, bh / 3);
    canvas.fillRoundRect(bx, by, bw, bh, eff_cr, fill);
    canvas.drawRoundRect(bx, by, bw, bh, eff_cr, rim);

    if (p < 0.45f) return;

    // Stars: 15 dim specks + 3 bright circles
    for (int i = 0; i < 18; i++) {
      int sx = bx + 4 + (_starX[i] * (bw - 8) / 100);
      int sy = by + 4 + (_starY[i] * (bh - 8) / 100);
      if (sx < bx+2 || sx > bx+bw-3 || sy < by+2 || sy > by+bh-3) continue;
      if (_starBright[i]) canvas.fillSmoothCircle(sx, sy, 2, C(255, 255, 255));
      else                canvas.drawPixel(sx, sy, sdim);
    }

    if (p < 0.90f) return;

    // Word-wrapped text with line-step scroll
    const int ROWS = (BH_FULL - PAD * 2) / 8;
    uint32_t  now2 = millis();
    if (_blineCount > ROWS && (now2 - _bscrollLastMs) >= 1400) {
      if (_bscrollLine + ROWS < _blineCount) { _bscrollLine++; _bscrollLastMs = now2; }
    }
    canvas.setTextSize(1);
    canvas.setTextColor(tc, fill);
    canvas.setTextDatum(top_left);
    for (int r = 0; r < ROWS && (_bscrollLine + r) < _blineCount; r++)
      canvas.drawString(_blines[_bscrollLine + r], bx + PAD, by + PAD + r * 8);
  }
};
