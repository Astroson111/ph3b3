#pragma once
#include "AppBase.h"
#include "AppManager.h"
#include <M5StackChan.h>

extern AppManager appMgr;

// Three-zone touch menu:
//   Top third    → scroll up (lower index)
//   Bottom third → scroll down (higher index)
//   Centre       → launch selected mode
//
// Menu is always index 0 in AppManager — it shows indices 1..n-1 only.
class MenuApp : public AppBase {
public:
    void init() override {
        face.setState(Ph3b3Face::CONNECTING);
        face.setStatusLine("select a mode");
        _sel = 1;  // first real mode (index 0 = us, skip it)
        _wasTouch = false;
        _drawTiles();
    }

    void update() override {
        face.setState(Ph3b3Face::CONNECTING);

        int16_t tx = 0, ty = 0;
        bool touching = M5StackChan.Display().getTouch(&tx, &ty);

        if (touching && !_wasTouch) {
            _wasTouch = true;
            int zones = M5StackChan.Display().height();
            int last  = appMgr.count() - 1;  // max selectable index

            if (ty < zones / 3) {
                // Top → scroll up (wrap 1..last)
                _sel = (_sel > 1) ? _sel - 1 : last;
                _drawTiles();
            } else if (ty > 2 * zones / 3) {
                // Bottom → scroll down (wrap 1..last)
                _sel = (_sel < last) ? _sel + 1 : 1;
                _drawTiles();
            } else {
                // Centre → launch
                appMgr.switchTo(_sel);
                return;
            }
        } else if (!touching) {
            _wasTouch = false;
        }

        if (appMgr.app(_sel))
            face.setStatusLine(String(appMgr.app(_sel)->name()));
    }

    void draw() override {}  // tiles drawn in _drawTiles()
    void exit() override {}
    const char* name() const override { return "Menu"; }

private:
    int  _sel      = 1;
    bool _wasTouch = false;

    void _drawTiles() {
        auto& d  = M5StackChan.Display();
        int W    = d.width();
        int H    = d.height();
        int n    = appMgr.count() - 1;  // number of real modes (exclude us at 0)
        if (n <= 0) return;

        d.startWrite();
        d.fillScreen(TFT_BLACK);

        // Header
        d.setTextDatum(top_center);
        d.setTextSize(1);
        d.setTextColor(M5.Display.color565(60, 60, 100), TFT_BLACK);
        d.drawString("Ph3b3 / Stack-Chan", W / 2, 6);

        // Scroll arrows
        d.setTextColor(M5.Display.color565(80, 80, 120), TFT_BLACK);
        d.drawString("^ scroll ^", W / 2, 22);
        d.setTextDatum(bottom_center);
        d.drawString("v scroll v", W / 2, H - 6);

        // Tile list — show up to 4 centred around _sel (visual indices 1..n)
        int visN   = min(n, 4);
        int tileH  = (H - 60) / visN;
        int startY = 36;

        for (int vi = 0; vi < visN; vi++) {
            // Map visual position to app index, centred on _sel
            int offset  = vi - visN / 2;
            int appIdx  = _sel + offset;
            // Wrap within 1..n
            appIdx = ((appIdx - 1 + n) % n) + 1;

            bool selected = (appIdx == _sel);
            int y = startY + vi * tileH + tileH / 2;

            if (selected) {
                // Highlight bar
                d.fillRoundRect(8, startY + vi * tileH + 4, W - 16, tileH - 8,
                                6, M5.Display.color565(20, 10, 50));
                d.drawRoundRect(8, startY + vi * tileH + 4, W - 16, tileH - 8,
                                6, M5.Display.color565(100, 60, 200));
            }

            d.setTextDatum(middle_center);
            d.setTextSize(selected ? 2 : 1);
            d.setTextColor(selected ? TFT_CYAN : M5.Display.color565(120, 120, 160),
                           TFT_BLACK);
            const char* nm = appMgr.app(appIdx) ? appMgr.app(appIdx)->name() : "";
            d.drawString(nm, W / 2, y);
        }

        d.setTextDatum(bottom_center);
        d.setTextSize(1);
        d.setTextColor(M5.Display.color565(80, 100, 80), TFT_BLACK);
        d.drawString("tap centre to enter", W / 2, H - 20);
        d.endWrite();
    }
};
