# DEVELOPMENT

## 開発ルール

- 既存Webアプリを壊さないことを優先します。
- 依存追加はせず、標準ライブラリのみを維持します。
- 告示DB生成やPDF抽出はこのリポジトリで行わず、`Kokuji_DB` 側で生成した `data/kokuji_notices.db` を取り込みます。
- 修正は小さい差分で行います。
- Web UI の検索対象切替は `source=law` / `source=kokuji` の GET パラメータで保持し、未指定や不正値は `law` として扱います。
- `kokuji` は `source_registry.is_active` と `data/kokuji_notices.db` の両方が有効なときだけ選択可能にします。
- DBスキーマを変更した場合は、対応するテストも更新します。
- 最終的に `python -m unittest` を通します。
- 不要なDB変更や、根拠のない収録内容の書き換えはしません。

## 確認コマンド

```bash
python -m unittest
```

必要に応じて、Webアプリの目視確認も行ってください。
