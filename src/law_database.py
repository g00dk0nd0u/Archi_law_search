"""法令XMLから条文レコードを作り、SQLiteへ保存する処理を担当する。"""

import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Optional, Set, Tuple, Union

if __package__ in (None, ""):
    from number_text_utils import normalize_num, normalize_separators
else:
    from .number_text_utils import normalize_num, normalize_separators


@dataclass(frozen=True)
class LawSource:
    law_id: str
    law_name: str


@dataclass(frozen=True)
class ArticleRecord:
    article_no: str
    body: str
    provision_kind: str
    provision_context: str
    amend_law_num: str = ""


def _to_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _article_sort_key(article_no: str) -> Tuple[int, int]:
    # 例: 第111条 -> (111, 0), 第111条の2 -> (111, 2)
    normalized = normalize_num(normalize_separators(article_no))
    numbers = [int(value) for value in re.findall(r"\d+", normalized)]
    if not numbers:
        return (10**9, 0)
    if len(numbers) == 1:
        return (numbers[0], 0)
    return (numbers[0], numbers[1])


def _article_body(article: ET.Element) -> str:
    body = "".join(article.itertext())
    return "\n".join(line.strip() for line in body.splitlines() if line.strip())


def iter_articles(root: ET.Element):
    """APIレスポンスから本則・附則を区別して Article を走査する。"""
    main_provision = root.find(".//{*}MainProvision")
    if main_provision is not None:
        for article in main_provision.findall(".//{*}Article"):
            article_no = _to_text(article.findtext(".//{*}ArticleTitle"))
            if not article_no:
                continue
            body = _article_body(article)
            if not body:
                continue
            yield ArticleRecord(article_no, body, "main", "main")

    for suppl_index, suppl in enumerate(root.findall(".//{*}SupplProvision"), start=1):
        amend_law_num = _to_text(suppl.attrib.get("AmendLawNum"))
        suppl_label = _to_text(suppl.findtext("./{*}SupplProvisionLabel")) or "附則"
        provision_context = amend_law_num or f"{suppl_label}#{suppl_index}"
        for article in suppl.findall(".//{*}Article"):
            article_no = _to_text(article.findtext(".//{*}ArticleTitle"))
            if not article_no:
                continue
            body = _article_body(article)
            if not body:
                continue
            yield ArticleRecord(article_no, body, "suppl", provision_context, amend_law_num)


BASE_SCHEMA_SQL = """
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
        provision_kind TEXT NOT NULL,
        provision_context TEXT NOT NULL,
        amend_law_num TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL,
        article_sort_base INTEGER NOT NULL,
        article_sort_branch INTEGER NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(law_id, article_no, provision_kind, provision_context),
        FOREIGN KEY(law_id) REFERENCES laws(law_id)
    );
"""

DROP_FTS_SQL = """
    DROP TRIGGER IF EXISTS articles_ai;
    DROP TRIGGER IF EXISTS articles_ad;
    DROP TRIGGER IF EXISTS articles_au;
    DROP TABLE IF EXISTS articles_fts;
"""

FTS_SCHEMA_SQL = """
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


def supports_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(content)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        try:
            conn.execute("DROP TABLE IF EXISTS temp.fts5_probe")
        except sqlite3.OperationalError:
            pass


def has_fts5_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'articles_fts' LIMIT 1"
    ).fetchone()
    return row is not None


def fts5_enabled(conn: sqlite3.Connection) -> bool:
    return supports_fts5(conn) and has_fts5_table(conn)


def _drop_fts_objects(conn: sqlite3.Connection) -> None:
    try:
        conn.executescript(DROP_FTS_SQL)
    except sqlite3.OperationalError:
        pass


def _ensure_fts_objects(conn: sqlite3.Connection, rebuild_fts: bool) -> None:
    if not supports_fts5(conn):
        _drop_fts_objects(conn)
        return

    conn.executescript(FTS_SCHEMA_SQL)
    if rebuild_fts and has_fts5_table(conn):
        conn.execute("INSERT INTO articles_fts(articles_fts) VALUES ('rebuild')")


def init_db(conn: sqlite3.Connection):
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        DROP TABLE IF EXISTS articles;
        DROP TABLE IF EXISTS laws;
        """
    )
    _drop_fts_objects(conn)
    conn.executescript(BASE_SCHEMA_SQL)
    _ensure_fts_objects(conn, rebuild_fts=True)


def ensure_db(conn: sqlite3.Connection, rebuild_fts: bool = True):
    conn.executescript(BASE_SCHEMA_SQL)
    _ensure_fts_objects(conn, rebuild_fts=rebuild_fts)


def upsert_law(conn: sqlite3.Connection, source: LawSource, root: ET.Element) -> int:
    ensure_db(conn, rebuild_fts=False)
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
    for article in iter_articles(root):
        base, branch = _article_sort_key(article.article_no)
        conn.execute(
            """
            INSERT INTO articles(
                law_id, article_no, provision_kind, provision_context, amend_law_num,
                body, article_sort_base, article_sort_branch, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(law_id, article_no, provision_kind, provision_context) DO UPDATE SET
                amend_law_num=excluded.amend_law_num,
                body=excluded.body,
                article_sort_base=excluded.article_sort_base,
                article_sort_branch=excluded.article_sort_branch,
                updated_at=excluded.updated_at
            """,
            (
                source.law_id,
                article.article_no,
                article.provision_kind,
                article.provision_context,
                article.amend_law_num,
                article.body,
                base,
                branch,
                now,
            ),
        )
        inserted += 1

    return inserted


def law_exists(conn: sqlite3.Connection, law_id: str) -> bool:
    ensure_db(conn, rebuild_fts=False)
    row = conn.execute("SELECT 1 FROM laws WHERE law_id = ? LIMIT 1", (law_id,)).fetchone()
    return row is not None


def list_installed_law_ids(conn: sqlite3.Connection) -> Set[str]:
    ensure_db(conn, rebuild_fts=False)
    return {row[0] for row in conn.execute("SELECT law_id FROM laws").fetchall()}


def delete_law(conn: sqlite3.Connection, law_id: str) -> None:
    ensure_db(conn, rebuild_fts=False)
    conn.execute("DELETE FROM articles WHERE law_id = ?", (law_id,))
    conn.execute("DELETE FROM laws WHERE law_id = ?", (law_id,))


def replace_law(conn: sqlite3.Connection, source: LawSource, root: ET.Element) -> int:
    articles = list(iter_articles(root))
    if not articles:
        raise ValueError(f"法令データを取得できませんでした: {source.law_name} ({source.law_id})")

    ensure_db(conn, rebuild_fts=False)
    delete_law(conn, source.law_id)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO laws(law_id, law_name, updated_at)
        VALUES (?, ?, ?)
        """,
        (source.law_id, source.law_name, now),
    )

    for article in articles:
        base, branch = _article_sort_key(article.article_no)
        conn.execute(
            """
            INSERT INTO articles(
                law_id, article_no, provision_kind, provision_context, amend_law_num,
                body, article_sort_base, article_sort_branch, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.law_id,
                article.article_no,
                article.provision_kind,
                article.provision_context,
                article.amend_law_num,
                article.body,
                base,
                branch,
                now,
            ),
        )

    return len(articles)


def connect_db(db_path: Union[str, Path]) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))
