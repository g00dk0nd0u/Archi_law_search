import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class LawSource:
    law_id: str
    law_name: str


def _to_text(value: str | None) -> str:
    return (value or "").strip()


def _article_sort_key(article_no: str) -> tuple[int, int]:
    # 例: 第111条 -> (111, 0), 第111条の2 -> (111, 2)
    digits = "".join(ch if ch.isdigit() else " " for ch in article_no)
    numbers = [int(x) for x in digits.split() if x]
    if not numbers:
        return (10**9, 0)
    if len(numbers) == 1:
        return (numbers[0], 0)
    return (numbers[0], numbers[1])


def iter_articles(root: ET.Element):
    """APIレスポンスからArticle要素を走査して (article_no, body) を返す。"""
    for article in root.findall(".//{*}Article"):
        article_no = _to_text(article.findtext(".//{*}ArticleTitle"))
        if not article_no:
            continue
        body = "".join(article.itertext())
        body = "\n".join(line.strip() for line in body.splitlines() if line.strip())
        if not body:
            continue
        yield article_no, body


def init_db(conn: sqlite3.Connection):
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS laws (
            law_id TEXT PRIMARY KEY,
            law_name TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            law_id TEXT NOT NULL,
            article_no TEXT NOT NULL,
            body TEXT NOT NULL,
            article_sort_base INTEGER NOT NULL,
            article_sort_branch INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(law_id, article_no),
            FOREIGN KEY(law_id) REFERENCES laws(law_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            article_no,
            body,
            law_id UNINDEXED,
            content='articles',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
            INSERT INTO articles_fts(rowid, article_no, body, law_id)
            VALUES (new.id, new.article_no, new.body, new.law_id);
        END;

        CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
            INSERT INTO articles_fts(articles_fts, rowid, article_no, body, law_id)
            VALUES('delete', old.id, old.article_no, old.body, old.law_id);
        END;

        CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
            INSERT INTO articles_fts(articles_fts, rowid, article_no, body, law_id)
            VALUES('delete', old.id, old.article_no, old.body, old.law_id);
            INSERT INTO articles_fts(rowid, article_no, body, law_id)
            VALUES (new.id, new.article_no, new.body, new.law_id);
        END;
        """
    )


def upsert_law(conn: sqlite3.Connection, source: LawSource, root: ET.Element) -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO laws(law_id, law_name, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(law_id) DO UPDATE SET
            law_name=excluded.law_name,
            updated_at=excluded.updated_at
        """,
        (source.law_id, source.law_name, now),
    )

    inserted = 0
    for article_no, body in iter_articles(root):
        base, branch = _article_sort_key(article_no)
        conn.execute(
            """
            INSERT INTO articles(law_id, article_no, body, article_sort_base, article_sort_branch, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(law_id, article_no) DO UPDATE SET
                body=excluded.body,
                article_sort_base=excluded.article_sort_base,
                article_sort_branch=excluded.article_sort_branch,
                updated_at=excluded.updated_at
            """,
            (source.law_id, article_no, body, base, branch, now),
        )
        inserted += 1

    return inserted


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))
