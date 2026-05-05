# Archi Law Search

`data/laws.db` を根拠に、建築関連法令と建築系告示本文を検索するためのリポジトリです。用途は 2 つです。

- 人間がブラウザUIで手動検索する Web アプリ
- Codex が CLI 経由で DB 検索し、法令調査や根拠確認に使う運用

通常の法令検索と Web アプリは Python 標準ライブラリのみで動作します。HTTPS 接続に必要な CA バンドルは [certs/cacert.pem](certs/cacert.pem) を同梱しています。
告示 PDF 更新処理だけは別依存で、[requirements-kokuji.txt](requirements-kokuji.txt) に `requests` / `pypdf` を分離しています。

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
`--article` は前方一致検索です。たとえば `第三十五条` を指定すると、`第三十五条の二` や `第三十五条の三` も含めて確認できます。

## DBの場所

- 共通DB: [data/laws.db](data/laws.db)
- 告示CSV: [data/accepted_kokuji_notices.csv](data/accepted_kokuji_notices.csv)

現在の DB 収録範囲や運用上の注意は [docs/DB_POLICY.md](docs/DB_POLICY.md) を参照してください。

## Kokuji DB 更新

告示本文は `data/laws.db` に同居しますが、`laws` / `articles` には混ぜず、`kokuji_*` テーブルで独立管理します。

CSV を作るとき:

```bash
python tools/make_kokuji_csv.py
```

既定入力は `data/001992597.xlsx` です。ファイルが無い場合は、入力候補パスを表示して終了します。

差分確認のみ:

```bash
python tools/update_kokuji_db.py --dry-run
```

更新実行:

```bash
python tools/update_kokuji_db.py --apply --limit 3
```

更新ログは `output/logs/` に timestamp 付きで残り、`output/logs/latest_kokuji_update.log` も毎回更新されます。

告示検索 CLI:

```bash
python -m cli.search_kokuji --query "準不燃" --limit 10
python -m cli.search_kokuji --query "建築物" --limit 10 --json-pretty
```

検索は LIKE を主とし、FTS5 が使える環境では補助的に FTS を使います。

## docs

- [docs/CODEX_USAGE.md](docs/CODEX_USAGE.md)
- [docs/USER_MANUAL.md](docs/USER_MANUAL.md)
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- [docs/DB_POLICY.md](docs/DB_POLICY.md)

## テスト

```bash
python -m unittest
```
