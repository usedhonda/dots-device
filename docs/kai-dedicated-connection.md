# 端末の専用接続

現在の導入は[直接HTTPSモードの手順](getting-started.md)を参照してください。端末が外向きにトンネルを取得し、質問をMCPツールで受け、回答を署名付きwebhookで返します。Macの常駐中継は直接モードには不要です。

[構成](architecture.md)、[Dotへ渡す指示](dot-instructions.md)、[往復の確認](normal-chat-device-flow.md)を合わせて読んでください。端末用のJSONを通常チャットに出す方法では接続できません。

旧Mac HTTP中継は開発・ローカル復旧用として残っています。使う場合だけ[中継の説明](../bridge/README.md)を参照し、直接モードの結果と区別してください。
