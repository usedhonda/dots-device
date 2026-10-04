# KAI ESP32-C6 firmware

Target board: Waveshare ESP32-C6-Touch-LCD-1.47. The firmware drives the 320x172 landscape panel with Arduino_GFX, the AXS5106L touch controller, and the QMI8658 IMU. Display pins are SPI `SCK=1`, `MOSI=2`, `DC=15`, `CS=14`, `RST=22`, backlight `23`; touch/IMU I2C is `SDA=18`, `SCL=19`, touch reset `20`, interrupt `21`, IMU address `0x6b`.

## Runtime behavior

The current firmware configuration uses the direct HTTPS/MCP task; its ignored local direct configuration supplies enrollment and transport values. It polls the enrolled service over TLS, exposes the device tools, persists answer events, and records the matching receipt. The source also retains the legacy authenticated Mac HTTP bridge path for local recovery; it is not the current default behavior.

The HOME page animates KAI from gravity-driven motion. A home tap waves; a 650 ms hold resets the character position. The speech bubble uses the opposite side of the character, hides during movement, and returns when speed settles. Side and speed hysteresis prevent center/noise flicker. Its touch region follows that side; a speech-bubble tap toggles hide/show, and new summary or question content restores visibility. Fifteen seconds without touch returns to HOME (question reading may remain on its reply page while active). Settings stores the normal/dark theme in Preferences.

Questions render with 20px Japanese text, scrollable on the left. Choice labels also use the native 20px atlas and are shown two per reply page. One choice tap queues one answer, immediately returns HOME, and keeps the selected-answer feedback unchanged as the answer event and receipt progress. Re-tapping the selected choice only navigates home; it does not enqueue a duplicate request.

The footer presents compact connection indicators only. Serial diagnostics carry detailed health, HTTP status, retry, event, and receipt evidence; those values are not rendered as user-facing HTTP codes.

## Local generated inputs

KAI source and generated data live under ignored `.local/characters/kai/source` and `.local/characters/kai/generated/`; `firmware/kai_companion/kai_assets.h` is an ignored internal alias to the selected pack. `button_assets.h` and the ignored Wi-Fi/transport headers are generated or supplied locally and are intentionally absent from a clean checkout. Do not print credentials or private runtime configuration. Generate the character header with `python3 tools/prepare_assets.py .local/characters/kai/source .local/characters/kai/generated/kai_assets.h` and action icons with `python3 tools/prepare_action_icons.py`.

## Clean build

Use the project-root command below with a fresh empty `build` directory. The vendor library directory is external and ignored:

```sh
arduino-cli compile -b esp32:esp32:esp32c6:CDCOnBoot=cdc,FlashSize=8M,PartitionScheme=default_8MB \
  --libraries .local/vendor/Arduino/libraries --build-path build firmware/kai_companion
```

The external vendor set comes from the [Waveshare ESP32-C6-Touch-LCD-1.47 demo](https://docs.waveshare.com/ESP32-C6-Touch-LCD-1.47): Arduino_GFX 1.5.9 (BSD), FastIMU 1.2.8 (MIT), and the `esp_lcd_touch_axs5106l` manufacturer driver. No standalone license was detected for the manufacturer driver, so it is not redistributed by this project. Keep the copied libraries in `.local/vendor/Arduino/libraries` for local builds.

The serial protocol includes `home`, `screenshot`, `health`, `motion`, `neutral`, touch/gesture injection, and tilt diagnostics. A serial connection may reset the board. These tools and local simulation help inspect firmware behavior; they do not prove physical touch, cloud enrollment, deployment, or battery-only stability.
