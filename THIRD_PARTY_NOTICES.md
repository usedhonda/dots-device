# Third-party notices

Original project code, documentation, and the procedural geometric demo character are covered by [MIT](LICENSE). Private character packs are excluded. This license does not replace the licenses of dependencies or fonts.

## Japanese glyph tables

The generated Japanese glyph tables derive from **Noto Sans CJK JP Regular**, Copyright 2014-2021 Adobe, licensed under SIL Open Font License 1.1. Noto is a trademark of Google Inc. The original font is not bundled. Keep [the font license and notice](licenses/NotoSansCJK-OFL.txt) with the generated tables. See [font provenance and regeneration](docs/font-assets.md).

## External build dependencies

| Dependency | Version | License / source |
| --- | --- | --- |
| ESP32 Arduino core | 3.3.1 | [LGPL-2.1](https://github.com/espressif/arduino-esp32/blob/3.3.1/LICENSE.md) |
| ArduinoJson | 7.4.3 | [MIT](https://github.com/bblanchon/ArduinoJson/blob/v7.4.3/LICENSE.txt) |
| U8g2 | 2.36.19 | [BSD-2-Clause](https://github.com/olikraus/u8g2/blob/master/LICENSE); font data have separate terms |
| Arduino_GFX | 1.5.9 | [BSD](https://github.com/moononournation/Arduino_GFX/blob/master/license.txt) |
| FastIMU | 1.2.8 | [MIT](https://github.com/LiquidCGS/FastIMU/blob/main/LICENSE) |
| Waveshare esp_lcd_touch_axs5106l | Manufacturer demo snapshot | Standalone redistribution terms not established; obtained separately from the manufacturer |
| Pillow | >=12.1 | [HPND](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |

These dependencies are downloaded/installed locally rather than copied into this repository. Their upstream packages contain the applicable notices. Redistributing a compiled firmware or a bundled toolchain requires assessing the licenses of the included components; this repository does not grant additional rights.

The custom ESP32 tunnel client implements documented wire behavior; it is not the official OpenAI Go client. Upstream protocol reference: [openai/tunnel-client](https://github.com/openai/tunnel-client), Apache-2.0. No upstream Go source is bundled. Full provenance is in [the dependency inventory](docs/third-party-inventory.md).
