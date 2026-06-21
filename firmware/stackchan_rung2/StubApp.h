#pragma once
#include "AppBase.h"

// Placeholder for the Ph3b3 chat rung — not wired yet
class StubApp : public AppBase {
public:
    void init() override {
        face.setState(Ph3b3Face::IDLE);
        face.setStatusLine("Ph3b3 — coming soon");
    }
    void update() override {}
    const char* name() const override { return "Ph3b3 Chat"; }
};
