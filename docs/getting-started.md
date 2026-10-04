# ESP32 Dots端末を作るための導入手順

この手順はWaveshare ESP32-C6-Touch-LCD-1.47と、現行の直接HTTPSモードを対象にしています。まずUSB給電で表示と操作を確かめ、その後Dotとの通信を確かめます。電池単独の動作は最後に独立して確認してください。

## 1. 開発環境とライブラリ

以下は検証に使ったバージョンです。最初は揃えてから変更すると原因を追いやすくなります。

| 必要なもの | バージョン／用途 |
| --- | --- |
| Arduino CLI 1.5.1 | ESP32のビルドと書き込み |
| ESP32 Arduino core | 3.3.1、ESP32-C6用 |
| U8g2 | 2.36.19 |
| ArduinoJson | 7.4.3 |
| Arduino_GFX | 1.5.9、メーカーのデモから取得 |
| FastIMU | 1.2.8、メーカーのデモから取得 |
| esp_lcd_touch_axs5106l | メーカーのタッチドライバ |
| Python | 3.10以上 |
| Pillow | 12.1以上、画像素材の変換 |

Arduino CLIを導入後、リポジトリのルートで実行します。

```sh
arduino-cli core update-index
arduino-cli core install esp32:esp32@3.3.1
arduino-cli lib install "U8g2@2.36.19" "ArduinoJson@7.4.3"
python3 -m venv .local/venv
.local/venv/bin/python -m pip install -r requirements.txt
```

`python3 --version` が3.9なら先に3.10以上のPythonを用意してください。macOS標準のPythonが条件を満たすとは限りません。

メーカーライブラリは、公式デモの固定チェックサムを確認するヘルパーで取得できます。外部ダウンロードであり、ドライバをこのリポジトリから再配布するものではありません。

```sh
.local/venv/bin/python tools/setup_vendor.py
```

取得した公式ZIPがある場合は `--archive FILE.zip` で指定できます。SHA-256が一致しなければ展開しません。出典と再配布条件は[依存一覧](third-party-inventory.md)を参照してください。

## 2. デモキャラクターで始める

最初はMITの単純な図形ロボットを使います。KAIの素材は必要ありません。

```sh
.local/venv/bin/python tools/prepare_demo_character.py --output-dir .local/characters/demo/source
.local/venv/bin/python tools/prepare_assets.py .local/characters/demo/source .local/characters/demo/generated/kai_assets.h
.local/venv/bin/python tools/prepare_action_icons.py
ln -s ../../.local/characters/demo/generated/kai_assets.h firmware/kai_companion/kai_assets.h
```

リンクのコマンドは既存の `kai_assets.h` がない新規導入時の例です。既存リンクがある場合は参照先を確認して差し替え、別の生成物をそのリンクへ直接書き込まないでください。

自分のキャラクターは[素材仕様](character-assets.md)に従い、透過スプライトシートと完全なmanifestを `.local/characters/my-character/source/` に用意します。192×208のセル、最初の4動作は待機・右移動・左移動・手振りです。デモで生成されたmanifestが完全な例になります。変換器は範囲・空セル・フレーム数を事前検証します。フラッシュには容量制限があり、コンパイル時の使用量も確認してください。

## 3. Wi-Fi設定と直接接続の設定

設定例をローカルヘッダへコピーします。

```sh
cp examples/private_config.example.h firmware/kai_companion/private_config.h
cp examples/direct_private_config.example.h firmware/kai_companion/direct_private_config.h
```

`private_config.h` の `WIFI_SSID` と `WIFI_PASSWORD` を自分の値へ、`direct_private_config.h` の `DIRECT_ID` と `DIRECT_KEY` を自分のトンネル設定へ変更します。直接モードでも残存する中継コードのコンパイル用に `BRIDGE_*` の定義が必要です。設定例にはプレースホルダーを含めてあります。

ビルドだけなら未変更の設定例を使えます。ネットワークに接続せず画面を試す場合は[例の説明](../examples/README.md)に従って直接設定ヘッダを省略してください。これはクラウドとの接続成功を意味しません。

これらのファイルはGit対象外です。値をREADMEやスクリーンショット、共有ログへコピーしないでください。`DIRECT_SUB` の空オブジェクトは初期設定の例で、回答イベントの購読を完成させる値ではありません。

直接設定ヘッダがない場合は中継モードになります。新規導入で「Macとの通信待ち」と表示される場合は、このヘッダと `KAI_DIRECT`、実際に書き込んだビルドを確認します。

## 4. ビルドしてUSBで書き込む

ルートから実行します。初回は未使用の `build` ディレクトリを使います。

```sh
arduino-cli compile -b esp32:esp32:esp32c6:CDCOnBoot=cdc,FlashSize=8M,PartitionScheme=default_8MB \
  --libraries .local/vendor/Arduino/libraries --build-path build firmware/kai_companion
arduino-cli board list
```

一覧で対象ボードのポートを特定し、次の `USB_PORT` を実際のポートに置き換えます。

```sh
arduino-cli upload -p USB_PORT -b esp32:esp32:esp32c6:CDCOnBoot=cdc,FlashSize=8M,PartitionScheme=default_8MB \
  --input-dir build firmware/kai_companion
```

まずキャラ表示、平らに置いた時の左側への復帰、ページ操作、テーマ保存を確認します。ビルド成功だけでは物理タッチやWi-Fi通信の成功を証明できません。

## 5. 自分のDotと接続する

[公式Secure MCP Tunnel手順](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)で自分のトンネルとruntime keyを用意し、対象のChatGPTワークスペースで接続を設定します。Platformの権限とChatGPT側の開発者モード／プラグイン権限は別です。利用可否は公式の条件を確認してください。

本リポジトリのESP32実装は独自のトンネルクライアントです。公式のPC向け `tunnel-client` をそのままESP32へ入れる手順ではありません。接続を作るだけでは、対象Dotのツール利用と回答イベント購読まで完成したことにはなりません。

[MCP Events公式手順](https://developers.openai.com/plugins/build/mcp-events)に従い、対象Dotで `device.answer` を購読し、callback検証と保存が成功することを確認します。接続後は[Dotへ渡す指示テンプレート](dot-instructions.md)を使用します。通常会話向けの指示と、回答イベントの処理向けの指示を両方保存してください。指示の保存は、ツール接続やイベント購読の代わりにはなりません。

## 6. 往復の成功を確かめる

1. Dotとの通常の会話から「ラーメン／カレー」のような短い質問を端末へ送る。
2. 実機にその質問が届く。
3. 候補を1回押すと即ホームに戻り、選択した回答の吹き出しが出る。
4. 相手側で同じ質問IDの回答が受領され、会話に反映される。
5. 同じ回答の受領が端末側へ戻る。

Wi-Fiランプ点灯、ツールの成功応答、画面上の回答表示のいずれか1つだけでは往復全体の成功とは言えません。遅い／届かない場合は[対処ガイド](troubleshooting.md)で段階を分けて調べます。

## フォントとライセンス

日本語アトラスはNoto Sans CJK JPから生成済みで、ビルド時にフォントのダウンロードは不要です。再生成は[フォントの手順](font-assets.md)に従い、固定した入力フォントを明示します。コードとデモはMIT、フォントはOFL、依存ライブラリは別の条件です。[ライセンス一覧](../THIRD_PARTY_NOTICES.md)を確認してください。

## 検証の範囲

CIは設定例と生成デモを使ったファームウェアのコンパイルと、回答・要約・動作の保護テストを行います。実際のWi-Fi加入、Dotの権限、イベント購読、物理回答、電池運用は自分の実機で確認してください。
