# Dots デバイスの構成と動作

このページは、Waveshare ESP32-C6-Touch-LCD-1.47（320×172、横向き）で動く Dots/KAI ファームウェアを、実装を読みながら追うためのリファレンスです。現在の標準経路は Wi-Fi 上の直接 HTTPS/MCP 接続です。Mac の HTTP ブリッジはソースに残るレガシー経路で、直接経路と同じものとして扱いません。

## ソースの地図

| 役割 | 主なファイル | 読むポイント |
| --- | --- | --- |
| 起動、描画、入力、タスク | [`firmware/kai_companion/kai_companion.ino`](../firmware/kai_companion/kai_companion.ino) | 画面状態、タッチ、Wi-Fi 起動、直接/レガシーのタスク分岐 |
| 重力アニメーション | [`firmware/kai_companion/gravity_motion.h`](../firmware/kai_companion/gravity_motion.h) | 40 ms 相当のローパス、速度、摩擦、境界反射 |
| センサー軸の変換 | [`firmware/kai_companion/tilt_input.h`](../firmware/kai_companion/tilt_input.h) | IMU の X/Y を画面の右/下へ変換、水平時の HOME 帰還 |
| 直接 MCP 状態 | [`firmware/kai_companion/direct_mcp.h`](../firmware/kai_companion/direct_mcp.h) | 質問・回答・receipt の永続化、ツール、重複防止 |
| 直接トンネル | [`firmware/kai_companion/direct_tunnel.h`](../firmware/kai_companion/direct_tunnel.h) | HTTPS `/v1/tunnels/.../poll`、JSON-RPC 応答、再送 |
| 回答イベント | [`firmware/kai_companion/direct_events.h`](../firmware/kai_companion/direct_events.h) | `device.answer` の outbox、署名、試行状態、receipt 前後の分離 |
| 直接ツール定義 | [`firmware/kai_companion/direct_tools.h`](../firmware/kai_companion/direct_tools.h) | publish/read/record/status の公開スキーマ |
| Mac レガシー経路 | [`bridge/bridge.py`](../bridge/bridge.py)、[`bridge/README.md`](../bridge/README.md) | ローカル HTTP の開発・復旧用経路。直接 HTTPS の代替設定ではない |

Wi-Fi、トンネル ID/鍵、購読値はローカル設定です。キャラクター素材もローカルのユーザー入力から生成するため、値や画像をここには掲載しません。`private_config.h`、`direct_private_config.h` と生成物は、公開チェックアウトの読者が用意する入力ではありません。

## 画面と入力

`kai_companion.ino` は HOME、メニュー、質問文、回答ページ、設定を横スワイプで切り替えます。質問は左側に 20 px の日本語、選択肢は右側に 2 件ずつ表示し、長い質問文は縦にスクロールできます。新しい質問を受けると HOME の吹き出しを表示し、回答ページへ移ります。選択肢を 1 回タップすると、選択状態を保存して直ちに HOME に戻ります。選択済み、送信中、再送中の同じ選択肢をもう一度タップしても、二重の回答イベントは作らず HOME への移動として扱います。

HOME では KAI のタップが約 1.5 秒の wave、650 ms 超の長押しが位置リセットです。設定ページのテーマは Preferences に保存されます。15 秒間操作がなければ、回答ページを除くページは HOME に戻ります。詳細な HTTP コードや再送回数は画面ではなくシリアル診断に出ます。

## 重力の軸とアニメーション

IMU の加速度 `(accelX, accelY)` はそのまま画面座標ではありません。`screenGravity()` が `right = -accelY`、`down = accelX` に変換します。水平に置いたときは `withHomeReturn()` が小さなセンサーオフセットを吸収し、右方向入力がほぼ 0 の範囲で左方向の HOME 帰還を与えます。

変換後の値は g 単位の画面加速度として `GravityMotion` に入り、約 40 ms のローパス、速度上限、動摩擦、減衰、画面端の弱い反発を経て位置を更新します。これは画面上の 2D 表現であり、物理的な重力シミュレーターや姿勢推定値そのものではありません。`motion` と `telemetry` のシリアル出力で、変換前後の軸を分けて確認できます。

## 直接質問から receipt まで

```text
サービス --device_publish_question--> ESP32 の永続 question
   ↓ poll / JSON-RPC
画面に質問・選択肢を表示
   ↓ 1 回の選択タップ
HOMEへ戻る + answer を保存 + device.answer outbox を作成
   ↓ HTTPS webhook（署名付き、再送あり）
サービスが回答を読む
   ↓ device_record_receipt
ESP32 が receipt_id/summary を保存し、HOME に反映
```

`DirectMCP::select()` は question ID と choice ID を検証して、回答を先に NVS に保存します。イベント送信の成否はこの保存とは別です。`DirectEvents::pump()` は最大 5 回まで送信を試し、送信前の `pending/unknown`、成功した `sent`、終端失敗を保持します。したがって、画面上の「回答済み」や「送信中」はサービスが receipt を返した証拠ではありません。receipt は回答 ID、選択肢 ID、receipt ID、要約が一致した `device_record_receipt` の実行で初めて確定します。

例えばツール入力は次のような構造です（送信例ではありません）。

```json
{"question_id":"demo-food-001","text":"お昼は？","choices":[{"id":"ramen","label":"ラーメン"},{"id":"curry","label":"カレー"}]}
```

## 直接トランスポートと会話の遅延

直接経路では、選択された回答を先に NVS へ保存します。この保存は Wi-Fi 切断中や時計の同期前にも行い、接続と時計が復旧してから回答イベントを配送します。配送はトンネルの受信待ちより先に処理します。未回答の質問や受領待ちの回答がある間は、トンネルのサーバー側受信待ちを 1 秒、通常時は 5 秒にします。これは受信待ちの設定であり、TLS 接続やモデル処理を含む総応答時間の保証ではありません。

ESP32 が Wi-Fi へ接続し、NTP で時計を合わせ、CA 検証付き TLS でトンネルを poll します。応答は JSON-RPC として処理され、同じ poll の送達が失敗した場合は保留して次回に再試行します。TLS 接続には上限時間があり、リダイレクトや不検証 TLS へのフォールバックはありません。

この経路で測れるのは、端末の poll、JSON-RPC 処理、回答イベント送信、receipt の反映です。モデルが質問を生成する時間、通常の会話処理、サービス側のキュー待ち、ネットワークの往復は端末の UI 応答時間とは別です。よって「タップで HOME に戻った」ことを「会話が完了した」と読み替えません。`health`、`link`、`interaction`、直接診断 JSON とサービス側のイベント/receipt 記録を同じ回答 ID で突き合わせます。

## Wi-Fi、NTP、TLS

起動時は送信出力を抑え、モデムスリープを無効にし、自動再接続と全チャネル走査を有効にして Wi-Fi を開始します。直接タスクは `time.google.com` と `pool.ntp.org` を使う `configTime()` を設定し、時計が妥当になるまで TLS 通信を始めません。TLS は同梱 CA を `NetworkClientSecure::setCACert()` に渡して検証します。Wi-Fi が切れた場合は即時に画面を再起動せず、再接続を待ちながら診断カウンタを更新します。

## 電源と測定の境界

起動前、Wi-Fi 開始前、その後 1 秒ごとに電圧・RSSI・リセット理由などを小さな NVS ジャーナルへ記録し、Mac 経路では確認応答後に削除します。電圧値は GPIO 0 の ADC 読み値に 3 を掛けた推定値です。USB 接続は電源とシリアル診断を提供しますが、電池だけの安定性を証明しません。現時点のソースと診断だけから、電池の瞬間的な電圧降下（brownout）の原因や再現条件が解決済みだとは言えません。

## ビルド時の境界

通常のビルド手順と外部ライブラリは [`README.md`](../README.md) と [`firmware/README.md`](../firmware/README.md) を参照してください。クリーンチェックアウトにはローカル設定、生成アセット、Waveshare 由来のライブラリが含まれないため、シリアルシミュレーションや単体テストの成功は、実機のタッチ、クラウド enrollment、サービスの end-to-end receipt、電池運用を証明しません。
