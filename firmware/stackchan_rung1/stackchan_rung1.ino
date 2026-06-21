/*
 * stackchan_rung1.ino
 * Ph3b3 / Stack-Chan — Rung 1: BSP baseline + safe servo homing
 *
 * Toolchain : arduino-cli, FQBN m5stack:esp32:m5stack_cores3
 * Hardware  : retail M5Stack StackChan (CoreS3, SCS0009-class serial servos)
 *
 * Servo safety rules enforced here:
 *   - Tilt (Y/pitch): stays within BSP angle units 50–850 (= 5°–85°)
 *   - goHome() (Y=0) IS safe: Y=0 is the calibrated neutral-forward position
 *     (raw 620), not the physical servo extreme (raw 0). But we home tilt
 *     to 450 (45°) as a conservative center rather than 0.
 *   - Pan (X/yaw): 360° continuous, no restriction.
 *   - One axis at a time to limit peak current.
 *   - Each axis waits for physical completion (ReadMove feedback) with a 5 s timeout.
 *   - Do NOT hand-rotate servos when unpowered.
 *
 * BSP API (real calls, found in StackChan-BSP sources):
 *   M5StackChan.begin()                       — init BSP, power gate, serial servos
 *   M5StackChan.update()                      — tick (call every loop)
 *   M5StackChan.Motion.moveY(angle, speed)    — pitch; angle units: 10 = 1°; speed 0–1000
 *   M5StackChan.Motion.moveX(angle, speed)    — yaw; same units
 *   M5StackChan.Motion.isYMoving()            — true while pitch servo is moving (bus feedback)
 *   M5StackChan.Motion.isXMoving()            — true while yaw servo is moving
 *   M5StackChan.Display()                     — returns LGFX_Device& (M5GFX)
 */

#include <Arduino.h>
#include <M5StackChan.h>

// Tilt safe window in BSP angle units (10 units = 1°)
static const int TILT_MIN    =  50;   //  5°
static const int TILT_MAX    = 850;   // 85°
static const int TILT_HOME   = 450;   // 45° — conservative safe center
static const int PAN_HOME    =   0;   //  0° — forward

// Slow homing speed to avoid brownout / mechanical shock
static const int HOME_SPEED  = 200;

// Per-axis move timeout
static const uint32_t AXIS_TIMEOUT_MS = 5000;

// ---------------------------------------------------------------------------

static void waitAxisOrTimeout(bool (*axisMoving)()) {
    uint32_t t0 = millis();
    while (axisMoving() && millis() - t0 < AXIS_TIMEOUT_MS) {
        delay(10);
    }
}

static void drawStatus(const char* line1, const char* line2 = nullptr) {
    auto& d = M5StackChan.Display();
    d.fillScreen(TFT_BLACK);
    d.setTextDatum(middle_center);
    d.setTextSize(2);
    d.setTextColor(TFT_CYAN, TFT_BLACK);
    d.drawString(line1, d.width() / 2, d.height() / 2 - (line2 ? 16 : 0));
    if (line2) {
        d.setTextColor(TFT_WHITE, TFT_BLACK);
        d.setTextSize(1);
        d.drawString(line2, d.width() / 2, d.height() / 2 + 20);
    }
}

static void safeHome() {
    // Tilt first — limit current draw, one axis at a time
    drawStatus("Homing tilt...", "Y -> 45 deg");
    M5StackChan.Motion.moveY(TILT_HOME, HOME_SPEED);
    waitAxisOrTimeout([]() { return M5StackChan.Motion.isYMoving(); });
    delay(300);

    // Then pan
    drawStatus("Homing pan...", "X -> 0 deg");
    M5StackChan.Motion.moveX(PAN_HOME, HOME_SPEED);
    waitAxisOrTimeout([]() { return M5StackChan.Motion.isXMoving(); });
    delay(300);
}

void setup() {
    Serial.begin(115200);
    Serial.println("[rung1] init");

    M5StackChan.begin();

    drawStatus("Ph3b3", "Stack-Chan Rung 1");
    delay(1000);

    safeHome();

    // Report final angles
    int xAngle = M5StackChan.Motion.getCurrentXAngle();
    int yAngle = M5StackChan.Motion.getCurrentYAngle();
    Serial.printf("[rung1] homed — X=%d Y=%d (units: 10=1deg)\n", xAngle, yAngle);

    // Confirm: tilt within safe window
    bool tiltSafe = (yAngle >= TILT_MIN && yAngle <= TILT_MAX);
    if (!tiltSafe) {
        Serial.printf("[rung1] WARNING: tilt %d outside safe window %d-%d\n",
                      yAngle, TILT_MIN, TILT_MAX);
    }

    char info[40];
    snprintf(info, sizeof(info), "X=%d Y=%d %s", xAngle / 10, yAngle / 10,
             tiltSafe ? "OK" : "WARN");
    drawStatus("Ready", info);

    Serial.println("[rung1] setup complete");
}

void loop() {
    M5StackChan.update();
    delay(16);
}
