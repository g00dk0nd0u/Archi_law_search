# Archi Law Search

`data/laws.db` を根拠に建築関連法令を検索し、別DBの `data/kokuji_notices.db` を標準ライブラリ `sqlite3` だけで検索できるようにしたリポジトリです。用途は 2 つです。

- 人間がブラウザUIで手動検索する Web アプリ
- Codex が CLI 経由で DB 検索し、法令調査や根拠確認に使う運用

通常の法令検索、Web アプリ、告示検索は Python 標準ライブラリのみで動作します。HTTPS 接続に必要な CA バンドルは [certs/cacert.pem](certs/cacert.pem) を同梱しています。
告示 PDF の取得・本文抽出・DB生成はこのリポジトリでは行わず、別リポジトリ `Kokuji_DB` 側の責務とします。

## Webアプリとして使う

最初に DB を準備します。

```bash
python -m src.prepare_sqlite --db data/laws.db
```

次に Web アプリを起動します。

```bash
python -m src.web_app --db data/laws.db --host 127.0.0.1 --port 8765
```

ブラウザで `http://127.0.0.1:8765` を開いて検索します。検索フォームは左から `番号` → `検索キーワード` → `法令 / 告示スイッチ` → `検索` の順で、デフォルトは `法令` です。`Settings` から法令の追加・更新・削除もできます。

- `source=law` では `article` に条番号、`q` に本文キーワードを入れます
- `source=kokuji` では `notice_number` に告示番号、`q` にキーワードを入れます
- `source=kokuji` に対して `article=1436` のような旧URLが来た場合も、`notice_number` の代替として扱います
- `source` 未指定または不正値は `law` 扱いです
- 結果バー右側の `TXT保存` は、現在の検索結果全文を `output/exports/latest_law_search.txt` または `output/exports/latest_kokuji_search.txt` に上書き保存します
- 告示結果のリンク列では、`PDF` / `HTML` / `LINK` の下に `全文コピー` が表示され、必要な本文だけ個別コピーできます
- 告示番号は `国土交通省告示<br>第1119号` のように `第〜号` の直前で改行表示します

- `source=law` のときは `data/laws.db` を検索します
- `source=kokuji` のときは `data/kokuji_notices.db` を検索します
- `source_registry` の `kokuji.is_active` が false、または `data/kokuji_notices.db` が見つからない場合、告示スイッチは無効表示になります

## Codex / CLI として使う

法令調査では、必ず `python -m cli.search_laws` を使って `data/laws.db` を検索します。

```bash
python -m cli.search_laws --query "容積率" --limit 10
python -m cli.search_laws --law-id 325AC0000000201 --article 第五十二条 --json-pretty
python -m cli.search_laws --law "建築基準法" --article 第五十二条 --json-pretty
python -m cli.search_laws --query "容積率" --export-txt
```

`--law` は、DB 内に完全一致する法令名があるときは完全一致で検索し、完全一致がないときだけ部分一致にフォールバックします。法令が分かる場合は `--law-id` の使用を推奨します。
`--article` は前方一致検索です。たとえば `第三十五条` を指定すると、`第三十五条の二` や `第三十五条の三` も含めて確認できます。
`--export-txt` を引数なしで付けると、`output/exports/latest_law_search.txt` に保存します。明示パス指定時はそのパスを優先します。

## DBの場所

- 共通DB: [data/laws.db](data/laws.db)
- 告示DB: [data/kokuji_notices.db](data/kokuji_notices.db)

現在の DB 収録範囲や運用上の注意は [docs/DB_POLICY.md](docs/DB_POLICY.md) を参照してください。

## Kokuji DB 取込

告示本文は `data/laws.db` に混ぜず、`data/kokuji_notices.db` を別DBとして同梱します。通常法令DBの再生成・削除・更新時に告示DBを巻き込まないためです。

Kokuji_DB 側で生成した DB を取り込むとき:

```bash
python3 tools/import_kokuji_db.py --source ../Kokuji_DB/data/kokuji_notices.db
python3 tools/import_kokuji_db.py --source ../Kokuji_DB/data/kokuji_notices.db --dest data/kokuji_notices.db
```

`import_kokuji_db.py` は標準ライブラリのみを使い、取り込み前に最低限の SQLite スキーマ検証を行います。

告示検索 CLI:

```bash
python3 -m cli.search_kokuji --query "準不燃" --limit 10
python3 -m cli.search_kokuji --query "建築物" --limit 10 --json-pretty
python3 -m cli.search_kokuji --notice-number "1436号" --limit 10
```

検索は LIKE を主とし、DB内に FTS5 テーブルがある場合だけ補助的に使います。`document_number_norm` / `document_number_digits` がある新しい告示DBではそれらを優先し、古いDBでは `document_number` / `notice_name` / `full_text` に自動フォールバックします。
`kokuji` を検索対象に含めるかは `source_registry` の `is_active` で切り替えます。inactive でも DB ファイルは削除しません。

## docs

- [docs/CODEX_USAGE.md](docs/CODEX_USAGE.md)
- [docs/USER_MANUAL.md](docs/USER_MANUAL.md)
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- [docs/DB_POLICY.md](docs/DB_POLICY.md)

## テスト

```bash
python -m unittest
```
