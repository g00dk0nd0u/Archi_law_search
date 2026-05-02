# AGENTS.md

- このリポジトリは、Webアプリ開発と Codex による法令調査の両方に使います。
- 法令調査では、必ず `data/laws.db` を `python -m cli.search_laws` で検索して確認します。
- 一般知識だけで法令回答しません。
- 回答には、法令名・条番号・条名・該当原文を含めます。
- DBで確認できない内容は、「このDB上では確認できません」と明記します。
- 開発時は、既存Webアプリの機能を壊さないことを優先します。
- 詳細は `docs/CODEX_USAGE.md` `docs/DEVELOPMENT.md` `docs/DB_POLICY.md` を参照してください。
