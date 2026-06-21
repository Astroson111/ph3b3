#pragma once
#include "AppBase.h"
#include <M5StackChan.h>

// NOT an on-device scanner. nmap lives on the host machine, not the ESP32.
// This mode routes a scan INTENT through Ph3b3 (/chat) and reads back the result.
// Next rung: wire to Talk so "Ph3b3, run a network scan" triggers it server-side.
class NetworkApp : public AppBase {
public:
    void init() override {
        face.setState(Ph3b3Face::CONNECTING);
        face.setStatusLine("Network via Ph3b3");
        _drawInfo();
    }

    void update() override {
        face.setState(Ph3b3Face::CONNECTING);
        face.setStatusLine("Network via Ph3b3");
    }

    void exit() override {}
    const char* name() const override { return "Network"; }

private:
    void _drawInfo() {
        auto& d = M5StackChan.Display();
        int W = d.width(), H = d.height();
        d.fillRect(0, H - 96, W, 96, TFT_BLACK);
        d.setTextDatum(middle_center);
        d.setTextSize(1);
        d.setTextColor(TFT_WHITE, TFT_BLACK);
        d.drawString("Scan runs on the host", W / 2, H - 76);
        d.setTextColor(M5.Display.color565(100, 100, 140), TFT_BLACK);
        d.drawString("Ask Ph3b3 via Talk:", W / 2, H - 58);
        d.drawString("\"run a network scan\"", W / 2, H - 42);
        d.drawString("Ph3b3 calls nmap, reads back", W / 2, H - 26);
        d.setTextColor(M5.Display.color565(60, 80, 60), TFT_BLACK);
        d.drawString("(next rung, wired through Talk)", W / 2, H - 10);
    }
};
