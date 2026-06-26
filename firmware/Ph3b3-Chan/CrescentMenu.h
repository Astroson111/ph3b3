#pragma once
#include <M5Unified.h>
#include <M5StackChan.h>
#include "ph3b3_face.h"
#include "AppManager.h"

extern Ph3b3Face  face;
extern AppManager appMgr;
extern bool       g_overlayOpen;
extern bool       g_crescentTapped;

// Left-side drawer triggered by right-swipe originating on the crescent-moon tab.
//
// Gesture: touch down in 60×60 top-left zone (crescent), swipe RIGHT ≥ SWIPE_FULL_PX
//          → panel slides in from left tracking the finger, snaps open on release.
//          Swipe starting OUTSIDE the zone is ignored — face taps don't open the menu.
// Tap fallback: tap on crescent (no lateral movement) also opens/closes.
// Dismiss: swipe LEFT on crescent when open, or tap anywhere outside the panel.
// Tile tap: switches to that app and closes.
//
// g_overlayOpen is true while the panel is at all visible (apps suppress their own touch).
class CrescentMenu {
public:
    void update() {
        g_crescentTapped = false;  // clear previous frame; TalkApp consumed it or it expired

        int16_t tx = 0, ty = 0;
        bool touching = M5StackChan.Display().getTouch(&tx, &ty);

        if (touching && !_wasTouch) {
            // Touch DOWN
            _downX    = tx;
            _downY    = ty;
            _onTab    = _hitsTab(tx, ty);
            _dragging = false;
            _wasTouch = true;
            Serial.printf("[CM] DOWN tx=%d ty=%d onTab=%d open=%d\n", tx, ty, (int)_onTab, (int)_open);
        } else if (touching && _wasTouch) {
            // Touch MOVE — only track if originated on tab
            if (_onTab) {
                int dx = tx - _downX;
                if (!_dragging && abs(dx) > SWIPE_DEAD_PX) {
                    _dragging = true;
                    Serial.printf("[CM] DRAG armed dx=%d\n", dx);
                }
                if (_dragging) {
                    // Closed: drag right opens; open: drag left closes
                    float base = _open ? 1.0f : 0.0f;
                    _progress  = constrain(base + (float)dx / SWIPE_FULL_PX, 0.0f, 1.0f);
                }
            }
        } else if (!touching && _wasTouch) {
            // Touch UP
            Serial.printf("[CM] UP   onTab=%d dragging=%d open=%d\n", (int)_onTab, (int)_dragging, (int)_open);
            if (_onTab) {
                if (!_dragging) {
                    if (_open) {
                        _open = false;
                        Serial.println("[CM] → closed menu");
                    } else {
                        g_crescentTapped = true;
                        Serial.println("[CM] → g_crescentTapped=true");
                    }
                } else {
                    _open = (_progress >= SWIPE_THRESH);
                    Serial.printf("[CM] → swipe commit open=%d\n", (int)_open);
                }
            } else if (_open) {
                _handlePanelTap(_downX, _downY);
            }
            _dragging = false;
            _wasTouch = false;
        } else {
            _wasTouch = false;
        }

        // Snap to target when not dragging — lerp was causing choppy redraws during settling
        if (!_dragging) {
            _progress = _open ? 1.0f : 0.0f;
        }

        g_overlayOpen = _open || _progress > 0.02f;
        // Highlight (bright purple) whenever the panel is at all visible
        face.setCrescentTabHighlight(_progress > 0.02f);
    }

    void draw() {
        if (_progress < 0.02f) return;
        _drawPanel();
        _redrawTab();  // crescent stays visible on top of the panel
    }

    bool isOpen() const { return _open || _progress > 0.02f; }

private:
    float _progress  = 0.0f;
    bool  _open      = false;
    bool  _wasTouch  = false;
    bool  _onTab     = false;
    bool  _dragging  = false;
    int   _downX     = 0;
    int   _downY     = 0;

    // BGR-correct color565 — mirrors SC_FACE_BGR swap used by Ph3b3Face::C().
    // Named _col, not _C: picolibc ctype.h defines _C as a macro (040), which
    // would silently expand _C(...) to 040(...) causing "not a function" errors.
    static uint16_t _col(uint8_t r, uint8_t g, uint8_t b) {
#ifdef SC_FACE_BGR
        return M5StackChan.Display().color565(b, g, r);
#else
        return M5StackChan.Display().color565(r, g, b);
#endif
    }

    // Panel: left-side drawer; x slides from -OVL_W to 0 as _progress goes 0→1
    static const int OVL_W      = 152;
    static const int OVL_PAD    = 8;
    static const int TILE_H     = 46;

    // 8px dead-zone before swipe is committed; 120px swipe = full open; 35% to latch
    static const int   SWIPE_DEAD_PX = 8;
    static const int   SWIPE_FULL_PX = 120;
    static constexpr float SWIPE_THRESH = 0.35f;

    // Crescent tab hit zone: top-left 60×60 corner
    static const int TAB_ZONE = 60;

    bool _hitsTab(int x, int y) const {
        return (x >= 0 && x < TAB_ZONE && y >= 0 && y < TAB_ZONE);
    }

    // Left edge of panel in display coords
    int _panX() const { return (int)(-OVL_W + OVL_W * _progress); }

    void _handlePanelTap(int tx, int ty) {
        int n    = appMgr.count();
        int ovlH = OVL_PAD * 2 + n * TILE_H;
        int px   = _panX();  // ≈0 when panel is fully open

        if (tx >= px && tx < px + OVL_W && ty >= 0 && ty < ovlH) {
            for (int i = 0; i < n; i++) {
                int tileY = OVL_PAD + i * TILE_H;
                if (ty >= tileY && ty < tileY + TILE_H) {
                    appMgr.switchTo(i);
                    _open = false;
                    return;
                }
            }
        } else {
            _open = false;  // tap outside panel → dismiss
        }
    }

    void _drawPanel() {
        auto& d  = M5StackChan.Display();
        int n    = appMgr.count();
        int ovlH = OVL_PAD * 2 + n * TILE_H;
        int px   = _panX();

        d.fillRoundRect(px, 0, OVL_W, ovlH, 8, _col(10, 7, 25));
        d.drawRoundRect(px, 0, OVL_W, ovlH, 8, _col(70, 40, 150));

        for (int i = 0; i < n; i++) {
            int tileY = OVL_PAD + i * TILE_H;
            bool sel  = (i == appMgr.activeIndex());
            if (sel) {
                d.fillRoundRect(px + OVL_PAD, tileY + 4, OVL_W - OVL_PAD * 2, TILE_H - 8,
                                6, _col(22, 10, 55));
                d.drawRoundRect(px + OVL_PAD, tileY + 4, OVL_W - OVL_PAD * 2, TILE_H - 8,
                                6, _col(130, 70, 250));
            }
            d.setTextDatum(middle_center);
            d.setTextSize(sel ? 2 : 1);
            d.setTextColor(sel ? _col(210, 170, 255) : _col(110, 95, 145), _col(10, 7, 25));
            const char* nm = appMgr.app(i) ? appMgr.app(i)->name() : "";
            d.drawString(nm, px + OVL_W / 2, tileY + TILE_H / 2);
        }
    }

    // Draw crescent tab directly on the display so it stays visible even when
    // the panel has slid over the top-left canvas region.
    void _redrawTab() {
        auto& d  = M5StackChan.Display();
        int   tcx = 22, tcy = 22;
        float tr  = 14.0f;
        d.fillSmoothCircle(tcx, tcy, (int)tr, _col(200, 100, 255));
        d.fillSmoothCircle(tcx + (int)(tr * 0.55f), tcy - (int)(tr * 0.18f),
                           (int)tr, TFT_BLACK);
    }
};
