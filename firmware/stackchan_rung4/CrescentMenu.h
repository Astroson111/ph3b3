#pragma once
#include <M5Unified.h>
#include <M5StackChan.h>
#include "ph3b3_face.h"
#include "AppManager.h"

extern Ph3b3Face  face;
extern AppManager appMgr;
extern bool       g_overlayOpen;

// Corner crescent tab (top-left, on the face canvas so always visible) +
// mode-switch overlay panel (drawn directly on display after canvas push).
//
// Replaces the old 3-zone MenuApp and hold-corner-exit gesture.
// The crescent TAB is embedded in ph3b3_face.h canvas via setCrescentTabVisible(true).
// The overlay PANEL is drawn here every frame after face.update().
//
// Touch routing:
//   Crescent tab tap → open (or close if already open)
//   Mode tile tap    → switchTo(i) + close
//   Outside tap      → close, no switch
//   g_overlayOpen flag — apps check this to suppress their own touch when panel is up
class CrescentMenu {
public:
    void update() {
        // Animate progress toward open/closed target
        float target = _open ? 1.0f : 0.0f;
        _progress += (target - _progress) * 0.18f;

        g_overlayOpen = _open || _progress > 0.02f;
        face.setCrescentTabHighlight(_open);

        int16_t tx = 0, ty = 0;
        bool touching = M5StackChan.Display().getTouch(&tx, &ty);

        if (touching && !_wasTouch) {
            _wasTouch = true;
            _handleTap(tx, ty);
        } else if (!touching) {
            _wasTouch = false;
        }
    }

    void draw() {
        if (_progress < 0.02f) return;
        _drawPanel();
    }

    bool isOpen() const { return _open || _progress > 0.02f; }

private:
    float _progress = 0.0f;
    bool  _open     = false;
    bool  _wasTouch = false;

    // Tab hit zone: top-left 60×60 corner (rectangular is reliable; circular radius 22
    // from center (22,22) missed corners that are clearly on the crescent visually)
    static const int TAB_ZONE = 60;

    // Overlay panel geometry
    static const int OVL_W   = 152;
    static const int OVL_PAD = 8;
    static const int TILE_H  = 46;

    bool _hitsTab(int x, int y) const {
        return (x >= 0 && x < TAB_ZONE && y >= 0 && y < TAB_ZONE);
    }

    void _handleTap(int tx, int ty) {
        if (!_open) {
            if (_hitsTab(tx, ty)) _open = true;
            return;
        }
        // Panel is open: crescent tap closes without switching
        if (_hitsTab(tx, ty)) { _open = false; return; }

        int n    = appMgr.count();
        int ovlH = OVL_PAD * 2 + n * TILE_H;
        int panY = (int)(-ovlH + ovlH * _progress);

        if (tx >= 0 && tx < OVL_W && ty >= panY && ty < panY + ovlH) {
            for (int i = 0; i < n; i++) {
                int tileY = panY + OVL_PAD + i * TILE_H;
                if (ty >= tileY && ty < tileY + TILE_H) {
                    appMgr.switchTo(i);
                    _open = false;
                    return;
                }
            }
        } else {
            // Outside panel — close, no switch
            _open = false;
        }
    }

    void _drawPanel() {
        auto& d  = M5StackChan.Display();
        int n    = appMgr.count();
        int ovlH = OVL_PAD * 2 + n * TILE_H;
        // Slide down: y=0 when fully open, y=-ovlH when fully closed
        int panY = (int)(-ovlH + ovlH * _progress);

        d.fillRoundRect(0, panY, OVL_W, ovlH, 8, d.color565(10, 7, 25));
        d.drawRoundRect(0, panY, OVL_W, ovlH, 8, d.color565(70, 40, 150));

        for (int i = 0; i < n; i++) {
            int tileY = panY + OVL_PAD + i * TILE_H;
            bool sel  = (i == appMgr.activeIndex());
            if (sel) {
                d.fillRoundRect(OVL_PAD, tileY + 4, OVL_W - OVL_PAD * 2, TILE_H - 8,
                                6, d.color565(22, 10, 55));
                d.drawRoundRect(OVL_PAD, tileY + 4, OVL_W - OVL_PAD * 2, TILE_H - 8,
                                6, d.color565(130, 70, 250));
            }
            d.setTextDatum(middle_center);
            d.setTextSize(sel ? 2 : 1);
            d.setTextColor(sel ? d.color565(210, 170, 255) : d.color565(110, 95, 145),
                           d.color565(10, 7, 25));
            const char* nm = appMgr.app(i) ? appMgr.app(i)->name() : "";
            d.drawString(nm, OVL_W / 2, tileY + TILE_H / 2);
        }
    }
};
