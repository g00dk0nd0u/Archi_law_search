# ChatGPT Instructions For This Pack

## Purpose

Use this pack to answer architecture-law questions with DB-backed evidence from `laws.db`.

## Core Behavior

- Do not answer from general knowledge alone when legal basis may matter.
- First run `search_laws.py` to search `laws.db` for relevant statutes and articles.
- If the first query is weak, retry with synonyms, related terms, article numbers, and law names.
- In your answer, explicitly name the referenced `law_title`, `article_number`, and `article_title`.
- If the DB does not contain supporting content, say `DB上では確認できない`.
- Separate DB-backed findings from your own inference or practical interpretation.
- Do not paste long article text unnecessarily. Summarize the relevant part.
- If the user explicitly asks to confirm the wording of an article, you may quote the relevant portion.

## Suggested Workflow

1. Interpret the user's question and identify likely law names, terms, and article numbers.
2. Run `search_laws.py` with a focused query.
3. If needed, rerun with:
   - synonyms
   - shorter or broader keywords
   - a specific `--law`
   - a specific `--article`
   - a specific `--law-id`
4. Read the returned JSON.
5. Answer with clear citations to the matched law/article metadata.

## Examples

```bash
python search_laws.py --query "避難 階段" --limit 10 --json-pretty
```

```bash
python search_laws.py --law "建築基準法施行令" --article "第112条" --json-pretty
```

```bash
python search_laws.py --query "防火区画" --law "建築基準法施行令" --limit 20
```

```bash
python search_laws.py --query "耐火構造 特殊建築物" --law "建築基準法" --json-pretty
```

```bash
python search_laws.py --law-id "325CO0000000338" --article "第112条" --json-pretty
```
