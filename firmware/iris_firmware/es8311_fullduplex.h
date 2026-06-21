// es8311_fullduplex.h — ES8311 full-duplex driver for M5StickS3
//
// Uses I2S_NUM_0 in master full-duplex mode (TX speaker + RX mic simultaneously).
// Bypasses M5Unified's mutually-exclusive ADC/DAC callbacks; writes ES8311 reg
// 0x01 = 0xBF (both clock domains) via M5.In_I2C, same bus M5Unified uses.
//
// Lifecycle:
//   fdInit()      — Speaker.end() → ES8311 full-duplex → I2S pair
//   fdDeinit()    — tear down I2S pair → Speaker.begin() (tap-to-talk restored)
//   fdPlayChunk() — write PCM to TX DMA (call from main loop)
//   fdReadChunk() — read PCM from RX DMA, returns sample count
//
// Test helper:
//   fdRunTest()   — 3-second sine+mic test; returns captured RMS (call once).

#pragma once
#include <driver/i2s_std.h>
#include <driver/i2s_common.h>
#include <M5Unified.h>
#include <math.h>

// ── Hardware constants (M5StickS3, source: M5Unified.cpp:2037-2240) ──────────
static constexpr gpio_num_t FD_MCK  = GPIO_NUM_18;
static constexpr gpio_num_t FD_BCK  = GPIO_NUM_17;
static constexpr gpio_num_t FD_WS   = GPIO_NUM_15;
static constexpr gpio_num_t FD_DOUT = GPIO_NUM_14;  // speaker data out
static constexpr gpio_num_t FD_DIN  = GPIO_NUM_16;  // mic data in

static constexpr uint8_t  ES8311_ADDR   = 0x18;
static constexpr uint8_t  PM1_ADDR      = 0x6E;
static constexpr uint8_t  PM1_REG_11    = 0x11;
static constexpr uint8_t  PM1_ES8311_BIT = 0b00001000;

static constexpr int FD_RATE = 16000;  // Hz — matches Iris PTT sample rate

// ── I2S handles ───────────────────────────────────────────────────────────────
static i2s_chan_handle_t _fd_tx = nullptr;
static i2s_chan_handle_t _fd_rx = nullptr;

// ── ES8311 I2C write via M5Unified's internal I2C bus ────────────────────────
static void _es8311_wr(uint8_t reg, uint8_t val) {
    M5.In_I2C.writeRegister(ES8311_ADDR, reg, &val, 1, 100000);
}

static void _es8311_init_fullduplex() {
    // PM1 power on (same bit as speaker enable callback)
    M5.In_I2C.bitOn(PM1_ADDR, PM1_REG_11, PM1_ES8311_BIT, 100000);
    delay(5);

    _es8311_wr(0x00, 0x80);  // RESET — CSM power on
    delay(10);
    // 0x01: 0xB5(DAC) | 0xBA(ADC) = 0xBF — both clock domains enabled
    _es8311_wr(0x01, 0xBF);  // CLK_MANAGER: DAC + ADC clocks
    _es8311_wr(0x02, 0x18);  // MULT_PRE = 3
    _es8311_wr(0x0D, 0x01);  // power up analog circuitry
    _es8311_wr(0x0E, 0x02);  // enable analog PGA + ADC modulator
    _es8311_wr(0x12, 0x00);  // power-up DAC
    _es8311_wr(0x13, 0x10);  // enable output to HP drive
    _es8311_wr(0x14, 0x10);  // ADC: Mic1p-Mic1n, minimum PGA gain
    _es8311_wr(0x17, 0xFF);  // ADC volume (max gain)
    _es8311_wr(0x1C, 0x6A);  // ADC equalizer bypass, DC offset cancel
    _es8311_wr(0x32, 0xBF);  // DAC volume ±0 dB
    _es8311_wr(0x37, 0x08);  // bypass DAC equalizer
    delay(20);
}

// ── fdInit ────────────────────────────────────────────────────────────────────
// Returns ESP_OK on success. On failure, M5.Speaker is restored so tap-to-talk
// still works.
static esp_err_t fdInit() {
    // Release M5Unified's I2S_NUM_0 (speaker) so we can claim it.
    // Speaker.end() also turns off PM1 bit — we re-enable it in the ES8311 init.
    M5.Speaker.stop();
    M5.Speaker.end();
    delay(30);

    // Init ES8311 for simultaneous DAC + ADC
    _es8311_init_fullduplex();

    // Allocate full-duplex channel pair on I2S_NUM_0 (master)
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true;
    esp_err_t err = i2s_new_channel(&chan_cfg, &_fd_tx, &_fd_rx);
    if (err != ESP_OK) {
        Serial.printf("[fd] i2s_new_channel err %d\n", err);
        M5.Speaker.begin(); M5.Speaker.setVolume(200);
        return err;
    }

    // TX config (speaker): master drives MCK/BCK/WS, outputs on GPIO_14
    i2s_std_config_t tx_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(FD_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                        I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = FD_MCK,
            .bclk = FD_BCK,
            .ws   = FD_WS,
            .dout = FD_DOUT,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = { .mclk_inv = 0, .bclk_inv = 0, .ws_inv = 0 },
        },
    };
    err = i2s_channel_init_std_mode(_fd_tx, &tx_cfg);
    if (err != ESP_OK) {
        Serial.printf("[fd] init_std TX err %d\n", err);
        i2s_del_channel(_fd_tx); i2s_del_channel(_fd_rx);
        _fd_tx = _fd_rx = nullptr;
        M5.Speaker.begin(); M5.Speaker.setVolume(200);
        return err;
    }

    // RX config (mic): slave-like on same BCK/WS, receives on GPIO_16
    // MCK is UNUSED because I2S_NUM_0's TX already drives it.
    i2s_std_config_t rx_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(FD_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                        I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = FD_BCK,
            .ws   = FD_WS,
            .dout = I2S_GPIO_UNUSED,
            .din  = FD_DIN,
            .invert_flags = { .mclk_inv = 0, .bclk_inv = 0, .ws_inv = 0 },
        },
    };
    err = i2s_channel_init_std_mode(_fd_rx, &rx_cfg);
    if (err != ESP_OK) {
        Serial.printf("[fd] init_std RX err %d\n", err);
        i2s_del_channel(_fd_tx); i2s_del_channel(_fd_rx);
        _fd_tx = _fd_rx = nullptr;
        M5.Speaker.begin(); M5.Speaker.setVolume(200);
        return err;
    }

    i2s_channel_enable(_fd_tx);
    i2s_channel_enable(_fd_rx);
    Serial.println("[fd] init ok — full-duplex active");
    return ESP_OK;
}

// ── fdDeinit ──────────────────────────────────────────────────────────────────
// Tears down I2S pair, powers ES8311 down, restores normal M5Unified speaker.
static void fdDeinit() {
    if (_fd_tx) { i2s_channel_disable(_fd_tx); i2s_del_channel(_fd_tx); _fd_tx = nullptr; }
    if (_fd_rx) { i2s_channel_disable(_fd_rx); i2s_del_channel(_fd_rx); _fd_rx = nullptr; }

    // Power down ES8311 analog
    _es8311_wr(0x0D, 0xFC);
    _es8311_wr(0x00, 0x00);
    M5.In_I2C.bitOff(PM1_ADDR, PM1_REG_11, PM1_ES8311_BIT, 100000);

    // Restore M5Unified speaker path for tap-to-talk
    delay(30);
    M5.Speaker.begin();
    M5.Speaker.setVolume(200);
    Serial.println("[fd] deinit ok — speaker restored");
}

// ── fdPlayChunk ───────────────────────────────────────────────────────────────
// Write stereo PCM to TX DMA. buf[] is interleaved L,R int16.
// Returns true if any bytes were accepted.
static bool fdPlayChunk(const int16_t* buf, int stereoSamples, TickType_t waitTicks = 0) {
    if (!_fd_tx) return false;
    size_t written = 0;
    i2s_channel_write(_fd_tx, buf, stereoSamples * 4, &written, waitTicks);
    return written > 0;
}

// ── fdReadChunk ───────────────────────────────────────────────────────────────
// Read stereo PCM from RX DMA into buf[]. Returns number of int16 samples read
// (stereo pairs × 2). buf must hold at least stereoSamples*2 int16 values.
static int fdReadChunk(int16_t* buf, int stereoSamples, TickType_t waitTicks = 0) {
    if (!_fd_rx) return 0;
    size_t got = 0;
    i2s_channel_read(_fd_rx, buf, stereoSamples * 4, &got, waitTicks);
    return (int)(got / 2);  // bytes → int16 count
}

// ── fdRunTest ─────────────────────────────────────────────────────────────────
// Plays a 440 Hz sine tone on the speaker while simultaneously reading the mic.
// Runs for durationMs milliseconds. Returns captured RMS (0.0 = silence / fail).
// Serial output reports tx/rx stats for the findings log.
static float fdRunTest(uint32_t durationMs = 3000) {
    static constexpr int CHUNK = 256;  // stereo pairs per iteration
    int16_t txBuf[CHUNK * 2];  // stereo: L,R interleaved
    int16_t rxBuf[CHUNK * 2];

    double rmsAccum = 0.0;
    int    rmsN     = 0;
    int    txTotal  = 0;
    int    rxTotal  = 0;
    uint32_t phase  = 0;

    uint32_t t0 = millis();
    while (millis() - t0 < durationMs) {
        // Generate CHUNK stereo pairs of 440 Hz sine
        for (int i = 0; i < CHUNK; i++) {
            int16_t s = (int16_t)(sinf(2.0f * (float)M_PI * 440.0f * phase / FD_RATE) * 16000);
            txBuf[i * 2]     = s;  // L
            txBuf[i * 2 + 1] = s;  // R (same)
            phase++;
        }
        size_t written = 0;
        i2s_channel_write(_fd_tx, txBuf, CHUNK * 4, &written, pdMS_TO_TICKS(20));
        txTotal += (int)(written / 4);

        // Read from mic
        size_t got = 0;
        i2s_channel_read(_fd_rx, rxBuf, CHUNK * 4, &got, pdMS_TO_TICKS(20));
        int n = (int)(got / 2);  // int16 samples (both L+R channels)
        for (int i = 0; i < n; i++) {
            float fs = rxBuf[i] / 32768.0f;
            rmsAccum += (double)(fs * fs);
        }
        rmsN += n;
        rxTotal += n / 2;  // stereo pairs received
    }

    float rms = (rmsN > 0) ? sqrtf((float)(rmsAccum / rmsN)) : 0.0f;
    Serial.printf("[fd] test done — tx=%d rx=%d rms=%.5f\n", txTotal, rxTotal, rms);
    Serial.printf("[fd] rms %s (%.5f) — %s\n",
        rms > 0.001f ? "REAL" : "SILENCE/FAIL",
        rms,
        rms > 0.001f ? "full-duplex confirmed" : "check ES8311 wiring / init");
    return rms;
}
