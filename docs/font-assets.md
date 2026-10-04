# 日本語フォントアセット

日本語 UI のアトラスは、SIL Open Font License 1.1 で配布されている
Noto Sans CJK JP Regular から生成します。入力フォントはリポジトリへ同梱せず、
公式 upstream の固定コミットから取得したファイルを `--font` で明示します。

```sh
python tools/prepare_japanese_font.py \
  --font /path/to/NotoSansCJKjp-Regular.otf
python tools/prepare_japanese_large_font.py \
  --font /path/to/NotoSansCJKjp-Regular.otf
```

出力先を確認用の一時ファイルへ変更する場合は、各コマンドに `--output`
を追加してください。既定の出力先は tracked な firmware ヘッダーです。
生成ヘッダーには upstream URL と入力フォントの SHA-256 が記録されます。

入力フォントの provenance:

- URL: `https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf`
- SHA-256: `68a3fc98800b2a27b371f2fb79991daf3633bd89309d4ffaa6946fd587f375b5`
- ライセンス: [licenses/NotoSansCJK-OFL.txt](../licenses/NotoSansCJK-OFL.txt)

小さい表示用は 16px 2-bit、大きいボタンラベル用は 20px 4-bit です。生成器の
メトリクス assertion は、ASCII の比例幅と小さいかな・句読点の共通 baseline を
維持していることを確認します。
