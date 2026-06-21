#pragma once
#include "AppBase.h"
#include <M5StackChan.h>

// Next rung: wire /chat + /transcribe to Ph3b3, X-Ph3b3-Device: stackchan header,
// servo body language on LISTENING/THINKING/SPEAKING states.
class TalkApp : public AppBase {
public:
    void init() override {
        face.setState(Ph3b3Face::IDLE);
        face.setStatusLine("Talk  coming soon");
        _drawInfo();
    }

    void update() override {
        face.setState(Ph3b3Face::IDLE);
        face.setStatusLine("Talk  coming soon");
    }

    void exit() override {}
    const char* name() const override { return "Talk / Ph3b3"; }

private:
    void _drawInfo() {
        auto& d = M5StackChan.Display();
        int W = d.width(), H = d.height();
        d.fillRect(0, H - 80, W, 80, TFT_BLACK);
        d.setTextDatum(middle_center);
        d.setTextSize(1);
        d.setTextColor(TFT_WHITE, TFT_BLACK);
        d.drawString("Voice round-trip", W / 2, H - 60);
        d.setTextColor(M5.Display.color565(100, 100, 140), TFT_BLACK);
        d.drawString("/chat  /transcribe", W / 2, H - 44);
        d.drawString("X-Ph3b3-Device: stackchan", W / 2, H - 28);
        d.setTextColor(M5.Display.color565(60, 80, 60), TFT_BLACK);
        d.drawString("(next rung)", W / 2, H - 12);
    }
};
