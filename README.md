# Archi Law Search（建築法規検索）

建築基準法（`325AC0000000201`）、建築基準法施行令（`325CO0000000338`）、建築士法（`325AC1000000202`）をデフォルトで e-Gov 法令 API から取得し、SQLite に格納して検索するアプリです。その他の法令は Web UI の `Settings` から追加・更新・削除できます。

このリポジトリは **Python標準ライブラリのみ** で動作する構成です。  
- 事前準備: `src.prepare_sqlite`（API取得 → SQLite格納）
- 利用時UI: `src.web_app`（ローカルWeb UI）

HTTPS 接続に必要な CA バンドルは `certs/cacert.pem` としてリポジトリに同梱しています。追加の `pip install` は不要です。

## クイックスタート

### 1) SQLiteを準備
```bash
python -m src.prepare_sqlite --db data/laws.db
```

`--asof YYYY-MM-DD` を指定すると基準日で取得できます。初期取込対象は `建築基準法` `建築基準法施行令` `建築士法` の3件です。

### 2) Web UIを起動
```bash
python -m src.web_app --db data/laws.db --host 127.0.0.1 --port 8765
```

ブラウザで `http://127.0.0.1:8765` を開いて検索します。右上の `Settings` から、法令マスタ一覧を見ながら追加取込・更新・削除ができます。

## データベース設計（概要）
- `laws`: 法令マスタ（法令ID・法令名・更新日時）
- `articles`: 条文（法令ID・条番号・本文・並び替え用キー）
- `articles_fts`: FTS5 全文検索テーブル

`articles` への INSERT/UPDATE/DELETE はトリガーで `articles_fts` に自動反映されます。

## UIについて
このリポジトリは `src.web_app` によるローカルWeb UIを利用します。  
検索前に `python -m src.prepare_sqlite --db data/laws.db` を実行し、その後 `python -m src.web_app --db data/laws.db --host 127.0.0.1 --port 8765` で起動してください。

## テスト・ユーティリティ
- 本文生成の欠損検査: `python -m tests.check_missing_content`
- 条番号範囲を指定: `python -m tests.check_missing_content 111 120`
