#pragma once
#include "AppBase.h"
#include "AppManager.h"
#include <M5StackChan.h>

extern AppManager appMgr;

// Swipe-style touch menu: tap top half = scroll up, bottom half = scroll down, center = launch.
class MenuApp : public AppBase {
public:
    void init() override {
        face.setState(Ph3b3Face::CONNECTING);  // "menu" state — violet eyes
        face.setStatusLine("touch to select");
        _sel = 0;
        _drawMenu();
    }

    void update() override {
        face.setState(Ph3b3Face::CONNECTING);

        int16_t tx = 0, ty = 0;
        bool touching = M5StackChan.Display().getTouch(&tx, &ty);

        if (touching && !_wasTouch) {
            _wasTouch = true;
            int h = M5StackChan.Display().height();
            int w = M5StackChan.Display().width();

            if (ty < h / 3) {
                // Top zone → scroll up
                _sel = (_sel - 1 + appMgr.count()) % appMgr.count();
                _drawMenu();
            } else if (ty > 2 * h / 3) {
                // Bottom zone → scroll down
                _sel = (_sel + 1) % appMgr.count();
                _drawMenu();
            } else if (tx > w / 4 && tx < 3 * w / 4) {
                // Centre zone → launch
                if (_sel != _menuSelfIdx()) {
                    appMgr.switchTo(_sel);
                    return;
                }
            }
        } else if (!touching) {
            _wasTouch = false;
        }

        face.setStatusLine(appMgr.app(_sel) ? appMgr.app(_sel)->name() : "");
    }

    void draw() override {}   // menu drawn directly in _drawMenu()

    void exit() override {}

    const char* name() const override { return "Menu"; }

private:
    int  _sel       = 0;
    bool _wasTouch  = false;

    // Returns the index of this MenuApp inside appMgr, so we can skip self-select
    int _menuSelfIdx() const {
        for (int i = 0; i < appMgr.count(); i++)
            if (appMgr.app(i) == this) return i;
        return -1;
    }

    void _drawMenu() {
        auto& d = M5StackChan.Display();
        int W = d.width(), H = d.height();
        int n = appMgr.count();
        if (n == 0) return;

        d.startWrite();
        d.fillScreen(TFT_BLACK);

        d.setTextDatum(middle_center);
        d.setTextSize(1);
        d.setTextColor(0x4444, TFT_BLACK);
        d.drawString("^ scroll ^", W / 2, 12);
        d.drawString("v scroll v", W / 2, H - 12);

        int rowH = (H - 48) / min(n, 5);
        int startY = 24;
        for (int i = 0; i < n && i < 5; i++) {
            int di = (_sel - 2 + i + n) % n;
            bool selected = (di == _sel);
            int y = startY + i * rowH + rowH / 2;
            d.setTextColor(selected ? TFT_CYAN : TFT_DARKGREY, TFT_BLACK);
            d.setTextSize(selected ? 2 : 1);
            const char* nm = appMgr.app(di) ? appMgr.app(di)->name() : "";
            d.drawString(nm, W / 2, y);
        }

        d.setTextDatum(bottom_center);
        d.setTextColor(TFT_WHITE, TFT_BLACK);
        d.setTextSize(1);
        d.drawString("tap centre to launch", W / 2, H - 24);
        d.endWrite();
    }
};
