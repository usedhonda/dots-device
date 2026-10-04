# 公開用サンプル

このディレクトリには、公開リポジトリへ置ける設定ヘッダの例があります。`private_config.example.h` を `firmware/kai_companion/private_config.h` に、`direct_private_config.example.h` を `firmware/kai_companion/direct_private_config.h` にコピーしてから、ローカルの値へ置き換えてください。実際のWi-Fi情報、トンネルID、キーはコミットやログへ書きません。

`private_config.example.h` には、直接接続でも既存の中継コードをコンパイルするために、従来の `BRIDGE_HOST`、`BRIDGE_PORT`、`BRIDGE_TOKEN` を定義しています。`direct_private_config.example.h` の `DIRECT_SUB` は意図的に `{}` のままで、購読登録は行いません。

ネットワークへ接続せず画面だけを確認する場合は、直接設定ヘッダを作らず、`private_config.h` のプレースホルダー値でオフライン表示を試せます。これはローカル表示の確認であり、トンネル登録やイベント購読の成功を意味しません。

## デモキャラクター

MITで再配布できる、このプロジェクト用の単純な図形ロボットを生成できます。KAIの素材や参照画像は使いません。

```sh
python3 -m pip install -r requirements.txt
python3 tools/prepare_demo_character.py \
  --output-dir .local/characters/demo/source
python3 tools/prepare_assets.py \
  .local/characters/demo/source \
  .local/characters/demo/generated/kai_assets.h
```

生成物は指定した `--output-dir` の中だけに書かれます。アトラスは192×208ピクセルのセルで、待機、右移動、左移動、手振りの4動作を含みます。デモ画像と生成コードは本プロジェクトのMITライセンスで扱います。
