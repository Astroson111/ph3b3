# Iris (M5StickS3) — ES8311 Full-Duplex Findings

## StickS3 Audio Path: Pin/I2S Table

| Path         | I2S peripheral | MCK     | BCK     | WS      | DATA pin       |
|--------------|---------------|---------|---------|---------|----------------|
| Speaker (DAC)| I2S_NUM_0     | GPIO 18 | GPIO 17 | GPIO 15 | GPIO 14 (dout) |
| Mic (ADC)    | I2S_NUM_1     | GPIO 18 | GPIO 17 | GPIO 15 | GPIO 16 (din)  |

Source: `M5Unified/src/M5Unified.cpp` lines 2037–2046 (mic) and 2225–2240 (speaker).

MCK, BCK, and WS are **shared** between speaker and mic.  
DATA_OUT (GPIO 14) and DATA_IN (GPIO 16) are **independent** wires.

ES8311 codec I2C: address `0x18`, internal bus SDA=GPIO 47, SCL=GPIO 48.  
ES8311 power via PM1 IC: address `0x6E`, reg `0x11` bit 3 (bitOn = powered, bitOff = off).

## Why M5Unified Cannot Run Both Simultaneously

M5Unified's codec enable callbacks write ES8311 register `0x01` (CLK_MANAGER) with
mutually exclusive values:

| Mode         | Reg 0x01 | Effect                    |
|--------------|----------|---------------------------|
| Speaker only | `0xB5`   | DAC clock domains enabled |
| Mic only     | `0xBA`   | ADC clock domains enabled |
| **Full-duplex** | **`0xBF`** | **Both (bitwise OR)**  |

`0xB5 | 0xBA = 0xBF`. No other register prevents simultaneous operation —
the block is this single register write, not hardware.

M5Unified also installs I2S_NUM_0 (speaker) and I2S_NUM_1 (mic) as separate
independent MASTER channels, so only one drives BCK/WS at a time. The correct
full-duplex topology is a **single I2S_NUM_0 MASTER** with both TX (GPIO 14)
and RX (GPIO 16) channels — this is what the ES8311 codec is designed for.

## Full-Duplex Approach

1. `M5.Speaker.end()` — deletes I2S_NUM_0 channel; turns off PM1 power to ES8311.
2. Re-enable PM1 power: `M5.In_I2C.bitOn(0x6E, 0x11, 0b00001000, 100000)`.
3. Write ES8311 init sequence with `0x01 = 0xBF` (both clock domains):
   - `0x00 = 0x80` (reset)
   - `0x01 = 0xBF` (CLK_MANAGER: DAC + ADC clocks)
   - `0x02 = 0x18` (MULT_PRE=3)
   - `0x0D = 0x01` (power up analog)
   - `0x0E = 0x02` (enable PGA + ADC modulator)
   - `0x12 = 0x00` (power-up DAC)
   - `0x13 = 0x10` (enable output / HP drive)
   - `0x14 = 0x10` (ADC: Mic1p-Mic1n, minimum PGA gain)
   - `0x17 = 0xFF` (ADC volume max gain)
   - `0x1C = 0x6A` (ADC equalizer bypass, DC offset cancel)
   - `0x32 = 0xBF` (DAC volume ±0 dB)
   - `0x37 = 0x08` (bypass DAC equalizer)
4. `i2s_new_channel(I2S_NUM_0, MASTER, &tx_handle, &rx_handle)` — allocates full-duplex pair.
5. `i2s_channel_init_std_mode(tx_handle, ...)` — MCK=18, BCK=17, WS=15, dout=14, din=UNUSED.
6. `i2s_channel_init_std_mode(rx_handle, ...)` — bclk=17, ws=15, dout=UNUSED, din=16.
7. `i2s_channel_enable(tx_handle)` + `i2s_channel_enable(rx_handle)`.

## M5Unified Callback Names (for reference)

- Speaker enable: `M5Unified::_speaker_enabled_cb_sticks3` (`M5Unified.cpp:490`)
- Mic enable: `M5Unified::_microphone_enabled_cb_sticks3` (`M5Unified.cpp:910`)

## Make-or-Break Test

Play a 440 Hz sine tone on the TX channel while reading RMS from the RX channel
simultaneously. If captured samples are real (RMS > noise floor, not zeros, not constant)
during playback, the full-duplex path is confirmed. See `es8311_fullduplex.h` and
the "FD Test" menu entry in `iris_firmware.ino`.

## Deinit / Restore

`fdDeinit()` disables + deletes both I2S channels, powers down ES8311 via PM1,
then calls `M5.Speaker.begin()` + `M5.Speaker.setVolume(200)` to restore the normal
M5Unified speaker path for tap-to-talk.
