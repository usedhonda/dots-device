# Dots トラブルシューティング

まず USB シリアルを 115200 baud で開き、秘密値を貼り付けずに `health`、`link`、`interaction`、必要なら `measurements` と `motion` を取得します。端末の表示、端末の永続状態、ネットワーク配送、サービス側 receipt は別の証拠です。

## 症状別の確認

### 質問が表示されない

1. `health` で `wifi`、`imu`、`touch`、`bridge_task_created` と `bridge` を確認します。
2. `link` の `successes`、`failures`、`age_ms`、`http` を見ます。Wi-Fi 接続だけではトンネル poll の成功を意味しません。
3. 直接経路ならサービス側の `device_publish_question` の結果と question ID を照合します。端末は同じ ID の質問を冪等扱いし、未 receipt の回答がある間は次の質問を拒否します。
4. `health` が接続中でも質問が遅い場合、NTP 待ち、TLS 接続、サービス側の会話処理を分けます。`last_http` は HTTP の結果であり、モデル処理完了の時刻ではありません。

### 選択したのに回答が届かない

画面が HOME に戻るのはローカル選択が受理された証拠です。`interaction` の `send_status`、`queue_ms`、`http_ms`、`total_ms`、`attempts` は画面側の回答キューと送信計測（直接経路・レガシー経路で実装が異なる）を示します。直接経路では outbox の `pending/unknown/sent/terminal` をシリアルの直接診断と合わせます。`sent` は webhook の HTTP 成功を示しますが、サービスが回答を会話へ適用して receipt を返したことは示しません。回答 ID、`device.answer` イベント記録、`device_record_receipt` の receipt ID を順番に突き合わせます。

同じ選択肢を再タップしても、新しい送信は作られません。stale または terminal なら、古い質問を再送せず、サービス側の question/receipt 状態を確認してから新しい question を発行します。

### receipt が表示されない

receipt は選択保存やイベント送信とは別の段階です。サービスが返した `interaction_id`、`choice_id`、`receipt_id`、要約が実際の回答と一致しているか確認します。一度保存された receipt と異なる値は拒否されます。端末の HOME に「回答済み」が残っていても、receipt の不在を補うために手動で成功扱いにしないでください。

### Wi-Fi が切れる、または TLS が始まらない

`health` の `wifi_status`、`wifi_disconnect_reason`、`wifi_disconnect_count`、RSSI と `link` の `age_ms` を時系列で見ます。起動後に時計が妥当になるまで直接タスクは TLS を行いません。端末から NTP サーバーへ到達できるか、DNS、CA 検証、HTTPS 到達性を順に切り分けます。アクセスポイント自身の時計はこのファームウェアの時刻源ではありません。TLS の証明書検証を無効にしたり、HTTP に落としたりして復旧させる設定はありません。

Wi-Fi 再接続を繰り返す場合、同じ箇所を再起動する前に `measurements` で boot ID、uptime、RSSI、電圧、reset reason、stage を保存します。再接続処理は `firmware/kai_companion/kai_companion.ino` の通信タスクにあります。

### KAI が傾きに追従しない、または水平で戻らない

`motion` と `telemetry` を比較します。画面軸は `right = -accelY`、`down = accelX` です。水平時の小さな右方向オフセットは HOME 帰還の補正対象です。`neutral` または HOME 長押し（650 ms 超）で位置と速度をリセットできます。`simulated:true` の出力はシリアル注入値であり、実センサーの証拠ではありません。

### USB では動くが電池で再起動する

これは未解決の電源切り分けです。`measurements` の `battery_mv`、`min_battery_mv`、boot ID、`reset_reason` を、USB 時と電池時で同じ手順で記録します。ADC の値は GPIO 0 の推定値で、プローブした電源電圧そのものではありません。brownout の閾値や原因をこのログだけで断定せず、電源・配線・電池・負荷の独立した測定を行います。Wi-Fi 送信出力を抑え、バックライトを制限しても、電池だけの受入れを自動的に証明するものではありません。

### Mac ブリッジの案内を見た

Mac の HTTP ブリッジはレガシー/ローカル復旧経路です。直接 HTTPS/MCP が有効なビルドでは `bridgeTask` が直接 poll とイベント送信を担当し、Mac の `/state` や `/choice` と同じ遅延・状態機械ではありません。ログに「Mac への接続を待っています」と出ても、直接経路の enrollment や TLS の状態を表すとは限りません。ブリッジを使う場合だけ [`bridge/README.md`](../bridge/README.md) の認証済みローカル手順を使い、直接経路の成功証拠として再利用しないでください。

## 接続状態を連続記録する

既存のシリアル利用を終了してから、リポジトリ直下で次のヘルパーを実行します。出力は ignored の `.local/` に保存します。既存ファイルは上書きしないため、再取得時は別名を指定します。

```sh
python3 tools/trace_connection.py --port /dev/cu.usbmodem1101 --seconds 180 --output .local/connection-trace.jsonl
```

ヘルパーは raw descriptor を一度だけ開き、DTR/RTS や termios を変更しません。開始時に `health`、`link`、`power`、以後5秒ごとに `health` と `link` を要求し、安全な診断項目だけをホスト側の経過秒 `elapsed_s` とともに記録します。生ログ、質問内容、認証値は出力しません。端末のリセット、再接続操作、ファームウェア変更は行いません。

USB を開くだけでも ESP32-C6 がリセットされる可能性があるため、取得前の uptime と記録中の `uptime_ms` の連続性を確認します。`polls`、`failures`、`wifi_disconnect_count`、`touch_samples` などの件数は累積値です。同じ起動区間の差分を比較し、リセットをまたいで増減を計算しないでください。`wifi_status` と `direct` の HTTP・poll件数の変化を並べると、Wi-Fi 接続とトンネル通信の進行を分けて見られます。USB 接続中の `battery_mv` は ADC の推定値であり、電池だけでの安定稼働の証拠にはなりません。

## 診断の意味と限界

シリアル `health` は端末の状態、`link` は通信タスクの集計、`interaction` は画面と回答キュー、`measurements` はリセット前後の電源・無線の手掛かりです。いずれもサービス側の会話内容や receipt を代替しません。実機での一回のタップ、イベント配送、サービス処理、receipt 反映を同じ ID で追跡できた場合だけ、端末からサービスまでの end-to-end 成功として記録します。

実機確認を行わずに、シミュレーション、モック、HTTP 200、Wi-Fi 接続表示だけからクラウド enrollment、通常会話の応答時間、電池安定性、重複なしの運用を主張しないでください。
