#pragma once
#include "AppBase.h"
#include <M5Unified.h>

static const int APP_MAX    = 8;
static const int MENU_IDX   = 0;  // menu is always registered at index 0

class AppManager {
public:
    void registerApp(AppBase* app) {
        if (_count < APP_MAX) _apps[_count++] = app;
    }

    void begin(int startIdx = MENU_IDX) {
        _idx = startIdx;
        if (_count > 0) _apps[_idx]->init();
    }

    void switchTo(int idx) {
        if (idx < 0 || idx >= _count) return;
        _apps[_idx]->exit();
        _idx = idx;
        _apps[_idx]->init();
    }

    void returnToMenu() { switchTo(MENU_IDX); }

    bool isOnMenu() const { return _idx == MENU_IDX; }

    void update() { if (_count > 0) _apps[_idx]->update(); }

    // Draw active app overlays, then a dim menu-return hint in non-menu apps.
    void draw() {
        if (_count > 0) _apps[_idx]->draw();
        if (!isOnMenu()) _drawReturnHint();
    }

    int      activeIndex() const { return _idx; }
    int      count()       const { return _count; }
    AppBase* app(int i)    const { return (i >= 0 && i < _count) ? _apps[i] : nullptr; }
    AppBase* active()      const { return _count > 0 ? _apps[_idx] : nullptr; }

private:
    AppBase* _apps[APP_MAX] = {};
    int _count = 0;
    int _idx   = 0;

    // Small top-left hint: tells user how to return to menu.
    void _drawReturnHint() {
        auto& d = M5.Display;
        d.setTextDatum(top_left);
        d.setTextSize(1);
        d.setTextColor(M5.Display.color565(40, 40, 60), TFT_BLACK);
        d.drawString("hold \x1e menu", 4, 4);  // \x1e = up-arrow in most fonts
    }
};
