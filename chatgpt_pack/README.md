# ChatGPT Law Search Pack

## Contents

This pack contains:

- `data/laws.db`
- `chatgpt_pack/search_laws.py`
- `chatgpt_pack/CHATGPT_INSTRUCTIONS.md`
- `chatgpt_pack/README.md`

## How To Use With ChatGPT

1. Create the ZIP from the repository with:

```bash
python tools/export_chatgpt_pack.py
```

2. Upload the generated ZIP from `dist/` to ChatGPT.
3. In ChatGPT analysis mode, extract the ZIP and read `chatgpt_pack/CHATGPT_INSTRUCTIONS.md`.
4. Run `search_laws.py` as needed to search `laws.db` before answering questions.

## CLI Examples

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
python search_laws.py --law-id "325CO0000000338" --article "第112条" --json-pretty
```

## Expected Tables In laws.db

Current repository DB was inspected and is expected to contain:

- `laws`
  - `law_id`
  - `law_name`
- `articles`
  - `id`
  - `law_id`
  - `article_no`
  - `body`
- `articles_fts`
  - FTS5 index for article search when available

The script does lightweight schema introspection so it can tolerate small column-name differences when possible.

## Known Limitations

- The DB may be outdated compared with the latest official law text.
- Full-text search for notices or circular PDFs is not included yet.
- Final legal judgment should always be confirmed against the original official source.
- `notifications_list.xlsx` is not included in this pack yet.
