# Third-party dependency inventory

This is a provenance and notice inventory for the current `dots-device` firmware. It records what was observed in the checkout and in the upstream sources; it does not grant a license, vendor private inputs, or make a public-release decision. Evidence below was collected 2026-10-04.

## Build inputs used by the firmware

The include scan of `firmware/kai_companion` and the retained build metadata show the following direct inputs. `build/libraries.cache` records the ESP32 core, U8g2 and ArduinoJson paths used by the adopted local build; `.local/vendor` is ignored and is not a public dependency lock.

| Component | Retained version / pin | License evidence | Provenance and release notes |
| --- | --- | --- | --- |
| Espressif Arduino core for ESP32 | 3.3.1 (path in `build/libraries.cache`) | Upstream repository identifies LGPL-2.1; retain the upstream notice and applicable LGPL text. | [arduino-esp32](https://github.com/espressif/arduino-esp32), [v3.3.1 release](https://github.com/espressif/arduino-esp32/releases/tag/3.3.1). The installed `package.json` reports an older package metadata value (`3.3.0`), so the build path and Board Manager record should be captured for a future public lock rather than treating that file alone as proof. |
| U8g2 | 2.36.19 (`library.properties` and `library.json`) | BSD-2-Clause for U8g2 code. Fonts have separate terms; review the font-specific notices before redistributing any U8g2 font data. | [u8g2](https://github.com/olikraus/u8g2), [license](https://github.com/olikraus/u8g2/blob/master/LICENSE). Firmware includes `U8g2lib.h`; the retained copy is outside this repository at the local Arduino library path. |
| ArduinoJson | 7.4.3 (`library.properties` and `library.json`) | MIT (`LICENSE.txt`). | [v7.4.3 release](https://github.com/bblanchon/ArduinoJson/releases/tag/v7.4.3), [license](https://github.com/bblanchon/ArduinoJson/blob/v7.4.3/LICENSE.txt). Firmware includes `ArduinoJson.h`. |
| FastIMU | 1.2.8 (`.local/vendor/Arduino/libraries/FastIMU/library.properties`) | MIT (`LICENSE`). | [LiquidCGS/FastIMU](https://github.com/LiquidCGS/FastIMU). Firmware includes `FastIMU.h`; local metadata records the repository URL and version. |
| GFX Library for Arduino | 1.5.9 (`.local/vendor/Arduino/libraries/GFX_Library_for_Arduino/library.properties`) | BSD text in local `license.txt`. | [moononournation/Arduino_GFX](https://github.com/moononournation/Arduino_GFX). Firmware includes `Arduino_GFX_Library.h`. |
| `esp_lcd_touch_axs5106l` | No version field in the demo or local driver | No standalone license file or license header was present in the official demo directory examined. Do not assume Waveshare's repository or a sibling library license covers it. | The official [Waveshare board documentation](https://docs.waveshare.com/ESP32-C6-Touch-LCD-1.47) and [wiki](https://www.waveshare.com/wiki/1.47inch_Touch_LCD) identify this as an offline-installed touch driver. The downloaded demo URL is `https://files.waveshare.com/wiki/ESP32-C6-Touch-LCD-1.47/ESP32-C6-Touch-LCD-1.47-Demo.zip`; archive SHA-256 is recorded in the detail log. The two local driver files byte-match the archive's `Arduino/libraries/esp_lcd_touch_axs5106l/` files. Keep this dependency external until redistribution permission and notice requirements are established. |

### LVGL directory status

`.local/vendor/Arduino/libraries/lvgl` is present because it is part of the Waveshare demo set (metadata says 8.4.0 and MIT), but the firmware include scan contains no `lvgl`/`lvgl.h` include and the adopted build cache contains no LVGL object. It is therefore a retained demo dependency, not a dependency of this firmware. Remove it from any future public dependency list unless the firmware begins using it; if it is redistributed, retain the LVGL MIT notice and audit bundled examples and third-party subcomponents separately.

## Waveshare demo provenance

The official wiki lists `GFX_Library_for_Arduino` 1.5.9, `FastIMU` 1.2.8, LVGL 8.4.0, and `esp_lcd_touch_axs5106l` as the board demo's libraries; it marks the touch driver as offline-installed and gives no version or license. The 56,969,621-byte archive served by Waveshare on 2026-10-04 had SHA-256 `ad8e27b172035fb73b5dbe88b821b1ff37bd677c20db294a9da7e5317ee176dd` and `Last-Modified: 2025-05-12T08:46:59Z`. Its driver files have these SHA-256 values:

```text
esp_lcd_touch_axs5106l.cpp  48771abb2c35c0a077a3652b7a69324a7ebad478c9d861d369330693909c0
esp_lcd_touch_axs5106l.h    08bc1fc0ef62de30be619ee31e8ecc3d3cdb9789c3b7a8e7012d51f5b451a363
```

The archive listing showed no license file under that driver directory. This is provenance and integrity evidence only; it is not permission to redistribute the code.

## OpenAI tunnel-client comparison

The ESP32 code in `firmware/kai_companion/direct_tunnel.h` is a custom implementation: it uses Arduino `HTTPClient`, bounded JSON parsing, and the `/v1/tunnels/{id}/poll` and `/response` routes, and sends the tunnel headers and wire version `2026-08-25`. `direct_mcp.h` advertises MCP protocol `2026-07-28`. The source contains a comment naming upstream files as wire evidence, but no copied Go source was found and the firmware is not linked to the Go module.

The read-only recovery checkout `work/vendor/tunnel-client` is `github.com/openai/tunnel-client`, Apache-2.0, local `HEAD` `c8aeedec334db55bbd69bb16db6b71276993d708`, with source `pkg/version/VERSION` `0.0.15`. The public release tag `v0.0.15` resolves to `a390c168ff1b2d14e73a95991c186c6aba3ff5a0`; that release pin is the appropriate provenance reference if a future public document needs a released upstream snapshot. The local checkout is the moving `master` snapshot, so it must not be described as the exact v0.0.15 source. See the [upstream license](https://github.com/openai/tunnel-client/blob/master/LICENSE), [v0.0.15 release](https://github.com/openai/tunnel-client/releases/tag/v0.0.15), and [wire protocol documentation](https://github.com/openai/tunnel-client/blob/master/docs/protocol.md).

This establishes protocol inspiration and upstream license evidence, not that the custom ESP32 implementation is an official OpenAI client, a derivative of copied Go code, or compatible with every tunnel service release. A public release should state the supported wire/MCP versions and retain the Apache-2.0 notice only if OpenAI source is actually redistributed.

## Unresolved release work

- No standalone license or redistribution grant was found for the Waveshare touch driver. Obtain permission or require users to download the official demo themselves.
- Capture immutable Board Manager/package metadata for ESP32 core 3.3.1 and exact archives for U8g2 2.36.19 and ArduinoJson 7.4.3 before publishing a reproducible lock.
- Review U8g2 font terms and any generated font assets independently; the U8g2 library license does not automatically license font data.
- Decide whether the custom tunnel implementation is documented as a protocol implementation only, and add protocol fixtures before claiming compatibility.
