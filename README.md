# Archi Law Search（建築法規検索）

建築基準法（`325AC0000000201`）、建築基準法施行令（`325CO0000000338`）、建築士法（`325AC1000000202`）をデフォルトで e-Gov 法令 API から取得し、SQLite に格納して検索するアプリです。その他の法令は Web UI の `Settings` から追加・更新・削除できます。

このリポジトリは **Python標準ライブラリのみ** で動作する構成です。  
- Python 3.9 系を含む標準的な CPython で動作するようにしています
- SQLite の FTS5 が使える環境では全文検索を強化し、使えない環境では LIKE 検索へ自動フォールバックします
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
- `articles_fts`: FTS5 が使える環境でのみ作成される全文検索テーブル

FTS5 が有効な環境では、`articles` への INSERT/UPDATE/DELETE はトリガーで `articles_fts` に自動反映されます。  
FTS5 が使えない環境では `articles_fts` を作成せず、本文検索は LIKE ベースの互換モードで継続します。

## UIについて
このリポジトリは `src.web_app` によるローカルWeb UIを利用します。  
検索前に `python -m src.prepare_sqlite --db data/laws.db` を実行し、その後 `python -m src.web_app --db data/laws.db --host 127.0.0.1 --port 8765` で起動してください。

## テスト
- 回帰テスト: `python -m unittest tests.test_web_and_db`

## Rhino 8 / Python 3.9 / FTS5なし想定の確認
1. Rhino 8 の内蔵 CPython 3.9 で `src.web_app` と `src.prepare_sqlite` が構文エラーなく読み込めることを確認します。
2. `src.prepare_sqlite` で SQLite を作成し、`src.web_app` を起動します。
3. 条番号検索が動くことを確認します。
4. 本文キーワード検索で、FTS5 が無い環境でも例外で落ちずに LIKE 検索で結果が返ることを確認します。
