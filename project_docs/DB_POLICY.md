# DB_POLICY

`data/laws.db` は、このリポジトリの検索根拠です。法令調査では、DBに存在する法令と条文だけを回答根拠に使います。

`data/laws.db` は法令系テーブル `laws` / `articles` のために使い、告示本文は別DBの `data/kokuji_notices.db` に分離して同梱します。告示本文は法令条文ではないため、`articles` には混ぜません。

## 運用ルール
- DBにない内容は、回答根拠にしません。
- DBで確認できない事項は、「このDB上では確認できません」と明記します。
- 未収録法令を追加する場合は、法令IDと法令名の対応を確認してから取り込みます。
- 既存DBを更新するときは、既存WebアプリとCLI検索の動作確認を行います。
- 告示本文DBの生成・PDF取得・本文抽出は `Kokuji_DB` 側の責務とし、このリポジトリでは行いません。
- このリポジトリでは `data/kokuji_notices.db` を読み取り専用の検索対象として扱います。
- `source_registry` で `kokuji` を active / inactive 切替できますが、inactive でも DB ファイルは削除しません。
- 告示検索では、`document_number_norm` / `document_number_digits` がある場合はそれらを優先し、ない場合は `document_number` / `notice_name` / `full_text` にフォールバックして、古いDBでも検索UIが落ちないようにします。
- 長文確認用の標準テキスト出力先は `output/exports/` とし、Web UI の `TXT保存` は `latest_law_search.txt` / `latest_kokuji_search.txt` を上書きします。
- `python -m cli.search_laws --export-txt` も同じ思想で使い、引数なしなら `output/exports/latest_law_search.txt` を標準出力先とします。
