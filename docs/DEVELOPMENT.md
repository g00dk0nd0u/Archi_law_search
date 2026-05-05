# DEVELOPMENT

## 開発ルール

- 既存Webアプリを壊さないことを優先します。
- 依存追加はせず、標準ライブラリのみを維持します。
- 告示更新処理の依存は [requirements-kokuji.txt](../requirements-kokuji.txt) に分離し、通常経路へ漏らしません。
- 修正は小さい差分で行います。
- DBスキーマを変更した場合は、対応するテストも更新します。
- 最終的に `python -m unittest` を通します。
- 不要なDB変更や、根拠のない収録内容の書き換えはしません。

## 確認コマンド

```bash
python -m unittest
```

必要に応じて、Webアプリの目視確認も行ってください。
