# Archi Law Search

`data/laws.db` を根拠に、建築関連法令を検索するためのリポジトリです。用途は 2 つです。

- 人間がブラウザUIで手動検索する Web アプリ
- Codex が CLI 経由で DB 検索し、法令調査や根拠確認に使う運用

このリポジトリは Python 標準ライブラリのみで動作します。HTTPS 接続に必要な CA バンドルは [certs/cacert.pem](/Users/ryokondo/Documents/iMac_Python/Archi_law_search/certs/cacert.pem) を同梱しています。

## Webアプリとして使う

最初に DB を準備します。

```bash
python -m src.prepare_sqlite --db data/laws.db
```

次に Web アプリを起動します。

```bash
python -m src.web_app --db data/laws.db --host 127.0.0.1 --port 8765
```

ブラウザで `http://127.0.0.1:8765` を開いて検索します。`Settings` から法令の追加・更新・削除もできます。

## Codex / CLI として使う

法令調査では、必ず `python -m cli.search_laws` を使って `data/laws.db` を検索します。

```bash
python -m cli.search_laws --query "容積率" --limit 10
python -m cli.search_laws --law-id 325AC0000000201 --article 第五十二条 --json-pretty
python -m cli.search_laws --law "建築基準法" --article 第五十二条 --json-pretty
```

`--law` は、DB 内に完全一致する法令名があるときは完全一致で検索し、完全一致がないときだけ部分一致にフォールバックします。法令が分かる場合は `--law-id` の使用を推奨します。

## DBの場所

- 共通DB: [data/laws.db](/Users/ryokondo/Documents/iMac_Python/Archi_law_search/data/laws.db)

現在の DB 収録範囲や運用上の注意は [docs/DB_POLICY.md](/Users/ryokondo/Documents/iMac_Python/Archi_law_search/docs/DB_POLICY.md) を参照してください。

## docs

- [docs/CODEX_USAGE.md](/Users/ryokondo/Documents/iMac_Python/Archi_law_search/docs/CODEX_USAGE.md)
- [docs/USER_MANUAL.md](/Users/ryokondo/Documents/iMac_Python/Archi_law_search/docs/USER_MANUAL.md)
- [docs/DEVELOPMENT.md](/Users/ryokondo/Documents/iMac_Python/Archi_law_search/docs/DEVELOPMENT.md)
- [docs/DB_POLICY.md](/Users/ryokondo/Documents/iMac_Python/Archi_law_search/docs/DB_POLICY.md)

## テスト

```bash
python -m unittest
```
