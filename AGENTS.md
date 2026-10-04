# Development guide

Target: Waveshare ESP32-C6-Touch-LCD-1.47, ESP32 Arduino core 3.3.1. Start with README.md and docs/getting-started.md. Direct HTTPS is the current transport; the Mac relay is a separate legacy path.

Keep Wi-Fi credentials, tunnel keys, subscriptions, runtime logs and private character artwork under ignored local paths. Do not commit generated private character headers or diagnostic captures. Use the procedural demo for public fixtures.

Preserve question/answer/receipt IDs, single-tap answers, pending-question protection, TLS certificate verification and callback validation. A local selection, webhook acceptance and Dot receipt are distinct states.

Use focused existing checks for changed behavior; documentation-only edits need a diff/link check rather than firmware build. A build proves compilation, not live Dot delivery, physical touch or battery stability. The CI firmware job compiles the demo with synthetic configuration.

Generated Japanese atlases use the pinned Noto source and OFL notice; use explicit font inputs. Code and procedural demo are MIT; third-party materials retain their own terms.
