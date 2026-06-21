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
    }

    void update() override {
        face.setState(Ph3b3Face::CONNECTING);
    }

    void exit() override {}
    const char* name() const override { return "Network"; }
};
