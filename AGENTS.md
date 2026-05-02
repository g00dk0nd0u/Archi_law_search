# AGENTS.md

- このリポジトリは、Webアプリ開発と Codex 法令調査の両方に使います。
- 法令調査では、必ず `python -m cli.search_laws` で `data/laws.db` を検索して確認します。
- 一般知識だけで法令回答しません。
- 回答には、法令名・条番号・条名・該当原文を含めます。
- DBで確認できない内容は、「このDB上では確認できません」と明記します。
- `--article` は前方一致検索であり、枝番条文も含みます。
- 開発時は既存Webアプリを壊さないことを優先します。
- 詳細は `docs/CODEX_USAGE.md` / `docs/DEVELOPMENT.md` / `docs/DB_POLICY.md` を参照してください。
