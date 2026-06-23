#pragma once
#include "AppBase.h"
#include <M5Unified.h>

static const int APP_MAX = 8;

class AppManager {
public:
    void registerApp(AppBase* app) {
        if (_count < APP_MAX) _apps[_count++] = app;
    }

    void begin(int startIdx = 0) {
        _idx = startIdx;
        if (_count > 0) _apps[_idx]->init();
    }

    void switchTo(int idx) {
        if (idx < 0 || idx >= _count) return;
        _apps[_idx]->exit();
        _idx = idx;
        _apps[_idx]->init();
    }

    void update() { if (_count > 0) _apps[_idx]->update(); }
    void draw()   { if (_count > 0) _apps[_idx]->draw(); }

    int      activeIndex() const { return _idx; }
    int      count()       const { return _count; }
    AppBase* app(int i)    const { return (i >= 0 && i < _count) ? _apps[i] : nullptr; }
    AppBase* active()      const { return _count > 0 ? _apps[_idx] : nullptr; }

private:
    AppBase* _apps[APP_MAX] = {};
    int _count = 0;
    int _idx   = 0;
};
