"""Differential update flow for kokuji notices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .kokuji_database import (
    DEFAULT_KOKUJI_CSV_PATH,
    NoticeRow,
    collect_counts,
    connect_db,
    ensure_kokuji_schema,
    process_notice,
    read_notice_rows,
    refresh_kokuji_fts,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "laws.db"
LOG_DIR = REPO_ROOT / "output" / "logs"
LATEST_LOG_PATH = LOG_DIR / "latest_kokuji_update.log"
DEFAULT_LIMIT = 20


@dataclass(frozen=True)
class DbNoticeRecord:
    id: int
    notice_name: str
    document_number: str
    document_date: str
    organization: str
    url: str
    match_reason: str
    fetch_status: str
    text_status: str
    full_text: str


@dataclass(frozen=True)
class DiffSummary:
    csv_record_count: int
    db_record_count: int
    missing_in_db_count: int
    missing_in_csv_count: int
    empty_full_text_count: int
    error_records_count: int
    changed_metadata_count: int
    final_update_target_count: int
    total_update_candidates_count: int


@dataclass(frozen=True)
class UpdateTarget:
    row: NoticeRow
    reason_labels: list[str]
    db_notice_id: int | None


class LogWriter:
    def __init__(self, handles: list[TextIO]) -> None:
        self._handles = handles

    def write(self, message: str = "") -> None:
        print(message)
        for handle in self._handles:
            handle.write(f"{message}\n")
            handle.flush()


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def make_timestamp_log_path() -> Path:
    ensure_log_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"kokuji_update_{timestamp}.log"


def normalize(value: str | None) -> str:
    return (value or "").strip()


def csv_strict_key(row: NoticeRow) -> tuple[str, str, str, str]:
    return (
        normalize(row.notice_name),
        normalize(row.document_number),
        normalize(row.document_date),
        normalize(row.organization),
    )


def csv_loose_key(row: NoticeRow) -> tuple[str, str, str] | None:
    parts = (
        normalize(row.document_number),
        normalize(row.document_date),
        normalize(row.organization),
    )
    if all(parts):
        return parts
    return None


def db_strict_key(row: DbNoticeRecord) -> tuple[str, str, str, str]:
    return (
        normalize(row.notice_name),
        normalize(row.document_number),
        normalize(row.document_date),
        normalize(row.organization),
    )


def db_loose_key(row: DbNoticeRecord) -> tuple[str, str, str] | None:
    parts = (
        normalize(row.document_number),
        normalize(row.document_date),
        normalize(row.organization),
    )
    if all(parts):
        return parts
    return None


def load_db_rows(db_path: Path) -> list[DbNoticeRecord]:
    if not db_path.exists():
        return []
    conn = connect_db(db_path)
    try:
        ensure_kokuji_schema(conn, rebuild_fts=False)
        rows = conn.execute(
            """
            SELECT
                id,
                notice_name,
                COALESCE(document_number, '') AS document_number,
                COALESCE(document_date, '') AS document_date,
                COALESCE(organization, '') AS organization,
                COALESCE(url, '') AS url,
                COALESCE(match_reason, '') AS match_reason,
                COALESCE(fetch_status, '') AS fetch_status,
                COALESCE(text_status, '') AS text_status,
                COALESCE(full_text, '') AS full_text
            FROM kokuji_notices
            ORDER BY id
            """
        ).fetchall()
        return [
            DbNoticeRecord(
                id=int(row["id"]),
                notice_name=row["notice_name"],
                document_number=row["document_number"],
                document_date=row["document_date"],
                organization=row["organization"],
                url=row["url"],
                match_reason=row["match_reason"],
                fetch_status=row["fetch_status"],
                text_status=row["text_status"],
                full_text=row["full_text"],
            )
            for row in rows
        ]
    finally:
        conn.close()


def is_error_record(row: DbNoticeRecord) -> bool:
    fetch_status = normalize(row.fetch_status).lower()
    text_status = normalize(row.text_status).lower()
    return (
        fetch_status == "fetch_error"
        or fetch_status == "error"
        or text_status == "error"
        or text_status.endswith("_error")
        or "_error" in text_status
    )


def metadata_changed(csv_row: NoticeRow, db_row: DbNoticeRecord) -> bool:
    return any(
        [
            normalize(csv_row.notice_name) != normalize(db_row.notice_name),
            normalize(csv_row.document_number) != normalize(db_row.document_number),
            normalize(csv_row.document_date) != normalize(db_row.document_date),
            normalize(csv_row.organization) != normalize(db_row.organization),
            normalize(csv_row.url) != normalize(db_row.url),
            normalize(csv_row.match_reason) != normalize(db_row.match_reason),
        ]
    )


def match_rows(
    csv_rows: list[NoticeRow],
    db_rows: list[DbNoticeRecord],
) -> tuple[dict[int, int], set[int], set[int]]:
    matched_csv_to_db: dict[int, int] = {}
    used_db_indexes: set[int] = set()

    url_map: dict[str, list[int]] = {}
    strict_map: dict[tuple[str, str, str, str], list[int]] = {}
    loose_map: dict[tuple[str, str, str], list[int]] = {}

    for db_index, db_row in enumerate(db_rows):
        if normalize(db_row.url):
            url_map.setdefault(normalize(db_row.url), []).append(db_index)
        strict_map.setdefault(db_strict_key(db_row), []).append(db_index)
        loose_key = db_loose_key(db_row)
        if loose_key is not None:
            loose_map.setdefault(loose_key, []).append(db_index)

    for csv_index, csv_row in enumerate(csv_rows):
        url = normalize(csv_row.url)
        candidates = url_map.get(url, []) if url else []
        available = [idx for idx in candidates if idx not in used_db_indexes]
        if len(available) == 1:
            matched_csv_to_db[csv_index] = available[0]
            used_db_indexes.add(available[0])

    for csv_index, csv_row in enumerate(csv_rows):
        if csv_index in matched_csv_to_db:
            continue
        candidates = strict_map.get(csv_strict_key(csv_row), [])
        available = [idx for idx in candidates if idx not in used_db_indexes]
        if len(available) == 1:
            matched_csv_to_db[csv_index] = available[0]
            used_db_indexes.add(available[0])

    for csv_index, csv_row in enumerate(csv_rows):
        if csv_index in matched_csv_to_db:
            continue
        loose_key = csv_loose_key(csv_row)
        if loose_key is None:
            continue
        candidates = loose_map.get(loose_key, [])
        available = [idx for idx in candidates if idx not in used_db_indexes]
        if len(available) == 1:
            matched_csv_to_db[csv_index] = available[0]
            used_db_indexes.add(available[0])

    missing_csv_indexes = set(range(len(csv_rows))) - set(matched_csv_to_db)
    missing_db_indexes = set(range(len(db_rows))) - used_db_indexes
    return matched_csv_to_db, missing_csv_indexes, missing_db_indexes


def build_targets(csv_rows: list[NoticeRow], db_rows: list[DbNoticeRecord]) -> tuple[DiffSummary, list[UpdateTarget]]:
    matches, missing_csv_indexes, missing_db_indexes = match_rows(csv_rows, db_rows)

    empty_full_text_count = 0
    error_records_count = 0
    changed_metadata_count = 0
    targets_by_csv_index: dict[int, UpdateTarget] = {}

    for csv_index in sorted(missing_csv_indexes):
        targets_by_csv_index[csv_index] = UpdateTarget(
            row=csv_rows[csv_index],
            reason_labels=["missing_in_db"],
            db_notice_id=None,
        )

    for csv_index, db_index in matches.items():
        csv_row = csv_rows[csv_index]
        db_row = db_rows[db_index]
        reasons: list[str] = []
        if normalize(db_row.full_text) == "":
            empty_full_text_count += 1
            reasons.append("empty_full_text")
        if is_error_record(db_row):
            error_records_count += 1
            reasons.append("error_record")
        if metadata_changed(csv_row, db_row):
            changed_metadata_count += 1
            reasons.append("changed_metadata")
        if reasons:
            targets_by_csv_index[csv_index] = UpdateTarget(
                row=csv_row,
                reason_labels=reasons,
                db_notice_id=db_row.id,
            )

    targets = [targets_by_csv_index[index] for index in sorted(targets_by_csv_index)]
    summary = DiffSummary(
        csv_record_count=len(csv_rows),
        db_record_count=len(db_rows),
        missing_in_db_count=len(missing_csv_indexes),
        missing_in_csv_count=len(missing_db_indexes),
        empty_full_text_count=empty_full_text_count,
        error_records_count=error_records_count,
        changed_metadata_count=changed_metadata_count,
        final_update_target_count=len(targets),
        total_update_candidates_count=len(targets),
    )
    return summary, targets


def print_summary(log: LogWriter, summary: DiffSummary) -> None:
    log.write(f"CSV record count: {summary.csv_record_count}")
    log.write(f"DB record count: {summary.db_record_count}")
    log.write(f"Missing in DB: {summary.missing_in_db_count}")
    log.write(f"Missing in CSV: {summary.missing_in_csv_count}")
    log.write(f"Empty full_text: {summary.empty_full_text_count}")
    log.write(f"Error records: {summary.error_records_count}")
    log.write(f"Changed metadata records: {summary.changed_metadata_count}")
    log.write(f"Final update target count: {summary.final_update_target_count}")


def run_check_only(
    *,
    log: LogWriter,
    summary: DiffSummary,
    input_csv: Path,
    db_path: Path,
) -> int:
    log.write("Check only mode. The DB will not be modified, and no network requests will be made.")
    log.write(f"Input CSV: {input_csv}")
    log.write(f"DB path: {db_path}")
    log.write("")
    print_summary(log, summary)
    return 0


def run_apply(
    *,
    log: LogWriter,
    summary: DiffSummary,
    targets: list[UpdateTarget],
    requested_limit: int | None,
    input_csv: Path,
    db_path: Path,
    verbose: bool,
) -> int:
    selected_targets = targets if requested_limit is None else targets[:requested_limit]
    selected_count = len(selected_targets)
    log.write(f"Input CSV: {input_csv}")
    log.write(f"DB path: {db_path}")
    log.write(f"Total update candidates: {len(targets)}")
    print_summary(log, summary)
    if selected_count == 0:
        log.write("No records need to be updated.")
        return 0

    conn = connect_db(db_path)
    try:
        fts_enabled = ensure_kokuji_schema(conn, rebuild_fts=False)
        for index, target in enumerate(selected_targets, start=1):
            fetch_status, text_status, text_char_count, page_count = process_notice(
                conn,
                target.row,
                fts_enabled=fts_enabled,
            )
            conn.commit()
            if verbose:
                log.write(
                    f"[{index}/{selected_count}] {target.row.notice_name[:40]} "
                    f"{fetch_status} {text_status} chars={text_char_count} pages={page_count} "
                    f"reasons={','.join(target.reason_labels)}"
                )

        if fts_enabled:
            refresh_kokuji_fts(conn)
            conn.commit()

        counts = collect_counts(conn)
        log.write("")
        log.write(f"Updated records: {selected_count}")
        log.write(f"DB kokuji_notices count after update: {counts['kokuji_notices']}")
        log.write(
            f"DB kokuji_notices with full_text after update: {counts['kokuji_notices_with_full_text']}"
        )
        log.write(f"DB kokuji_notice_errors count after update: {counts['kokuji_notice_errors']}")
    finally:
        conn.close()

    return 0


def execute_update(
    *,
    input_csv: Path = DEFAULT_KOKUJI_CSV_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    apply: bool = False,
    limit: int | None = None,
    verbose: bool = False,
) -> int:
    if not input_csv.exists():
        print(f"Input CSV not found: {input_csv}")
        return 1
    if limit is not None and limit <= 0:
        print("--limit must be greater than 0.")
        return 1

    csv_rows = read_notice_rows(input_csv)
    db_rows = load_db_rows(db_path)
    full_summary, targets = build_targets(csv_rows, db_rows)
    final_target_count = len(targets)
    if apply and limit is not None:
        final_target_count = min(final_target_count, limit)
    summary = DiffSummary(
        csv_record_count=full_summary.csv_record_count,
        db_record_count=full_summary.db_record_count,
        missing_in_db_count=full_summary.missing_in_db_count,
        missing_in_csv_count=full_summary.missing_in_csv_count,
        empty_full_text_count=full_summary.empty_full_text_count,
        error_records_count=full_summary.error_records_count,
        changed_metadata_count=full_summary.changed_metadata_count,
        final_update_target_count=final_target_count,
        total_update_candidates_count=full_summary.total_update_candidates_count,
    )

    timestamp_log_path = make_timestamp_log_path()
    with timestamp_log_path.open("w", encoding="utf-8") as timestamp_handle, LATEST_LOG_PATH.open(
        "w", encoding="utf-8"
    ) as latest_handle:
        log = LogWriter([timestamp_handle, latest_handle])
        log.write(f"started_at={datetime.now().isoformat()}")
        log.write(f"mode={'Update' if apply else 'Check only'}")
        log.write(f"log_path={timestamp_log_path}")
        log.write(f"latest_log_path={LATEST_LOG_PATH}")
        log.write("")
        if apply:
            result = run_apply(
                log=log,
                summary=summary,
                targets=targets,
                requested_limit=DEFAULT_LIMIT if limit is None else limit,
                input_csv=input_csv,
                db_path=db_path,
                verbose=verbose,
            )
        else:
            result = run_check_only(
                log=log,
                summary=summary,
                input_csv=input_csv,
                db_path=db_path,
            )
        log.write("")
        log.write(f"finished_at={datetime.now().isoformat()}")
        log.write(f"return_code={result}")
        return result
