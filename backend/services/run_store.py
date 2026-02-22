from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_PATH = Path("data/app_runs.db")


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _get_conn()
    try:
        # Improves concurrent read/write behavior and reduces fsync overhead for API usage.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                document_type TEXT,
                summary_json TEXT,
                payload_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                prd_text TEXT,
                prd_provider TEXT,
                prd_warning TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                filename TEXT,
                content_type TEXT,
                file_uri TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extractions (
                document_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                extraction_json TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(document_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS structured_docs (
                document_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                document_type TEXT,
                normalized_json TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(document_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runs_created_at
            ON runs(created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_structured_docs_document_type
            ON structured_docs(document_type)
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_document_upload(
    document_id: str,
    filename: str | None,
    content_type: str | None,
    file_uri: str | None,
) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO documents(document_id, created_at, filename, content_type, file_uri)
            VALUES(?, datetime('now'), ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                filename = excluded.filename,
                content_type = excluded.content_type,
                file_uri = excluded.file_uri
            """,
            (document_id, filename, content_type, file_uri),
        )
        conn.commit()
    finally:
        conn.close()


def save_extraction(document_id: str, extraction: Dict[str, Any]) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO extractions(document_id, created_at, extraction_json)
            VALUES(?, datetime('now'), ?)
            ON CONFLICT(document_id) DO UPDATE SET
                extraction_json = excluded.extraction_json,
                created_at = datetime('now')
            """,
            (document_id, json.dumps(extraction, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def save_structured_doc(document_id: str, normalized: Dict[str, Any]) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO structured_docs(document_id, created_at, document_type, normalized_json)
            VALUES(?, datetime('now'), ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                document_type = excluded.document_type,
                normalized_json = excluded.normalized_json,
                created_at = datetime('now')
            """,
            (
                document_id,
                (normalized or {}).get("document_type"),
                json.dumps(normalized, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_document_pipeline(document_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        dcur = conn.execute(
            """
            SELECT document_id, created_at, filename, content_type, file_uri
            FROM documents
            WHERE document_id = ?
            """,
            (document_id,),
        )
        doc = dcur.fetchone()
        if doc is None:
            return None

        ecur = conn.execute(
            """
            SELECT extraction_json, created_at
            FROM extractions
            WHERE document_id = ?
            """,
            (document_id,),
        )
        ext = ecur.fetchone()

        scur = conn.execute(
            """
            SELECT document_type, normalized_json, created_at
            FROM structured_docs
            WHERE document_id = ?
            """,
            (document_id,),
        )
        structured = scur.fetchone()

        return {
            "document": {
                "document_id": doc["document_id"],
                "created_at": doc["created_at"],
                "filename": doc["filename"],
                "content_type": doc["content_type"],
                "file_uri": doc["file_uri"],
            },
            "extraction": {
                "created_at": ext["created_at"] if ext else None,
                "data": _safe_json_load(ext["extraction_json"]) if ext else None,
            },
            "structured": {
                "created_at": structured["created_at"] if structured else None,
                "document_type": structured["document_type"] if structured else None,
                "data": _safe_json_load(structured["normalized_json"]) if structured else None,
            },
        }
    finally:
        conn.close()


def save_run(payload: Dict[str, Any], result: Dict[str, Any]) -> str:
    run_id = str(uuid.uuid4())
    summary = _extract_summary(result)
    document_type = (result.get("normalized") or {}).get("document_type")

    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, created_at, document_type, summary_json,
                payload_json, result_json, prd_text, prd_provider, prd_warning
            )
            VALUES (
                ?, datetime('now'), ?, ?, ?, ?, NULL, NULL, NULL
            )
            """,
            (
                run_id,
                document_type,
                json.dumps(summary, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def attach_prd_to_run(run_id: str, prd_result: Dict[str, Any]) -> bool:
    conn = _get_conn()
    try:
        cur = conn.execute(
            """
            UPDATE runs
            SET prd_text = ?, prd_provider = ?, prd_warning = ?
            WHERE run_id = ?
            """,
            (
                prd_result.get("prd_text"),
                prd_result.get("provider"),
                prd_result.get("warning"),
                run_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_runs(limit: int = 25) -> List[Dict[str, Any]]:
    limit = max(1, min(200, int(limit or 25)))
    conn = _get_conn()
    try:
        cur = conn.execute(
            """
            SELECT run_id, created_at, document_type, summary_json, prd_provider
            FROM runs
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "document_type": row["document_type"],
                "summary": _safe_json_load(row["summary_json"]),
                "prd_provider": row["prd_provider"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        cur = conn.execute(
            """
            SELECT run_id, created_at, document_type, summary_json,
                   payload_json, result_json, prd_text, prd_provider, prd_warning
            FROM runs
            WHERE run_id = ?
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "document_type": row["document_type"],
            "summary": _safe_json_load(row["summary_json"]),
            "payload": _safe_json_load(row["payload_json"]),
            "result": _safe_json_load(row["result_json"]),
            "prd": {
                "text": row["prd_text"],
                "provider": row["prd_provider"],
                "warning": row["prd_warning"],
            },
        }
    finally:
        conn.close()


def _extract_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    segmentation = (result.get("segmentation") or {}).get("output", {})
    behavior = (result.get("behavior") or {}).get("output", {})
    forecast = (result.get("forecast") or {}).get("output", {})
    decisions = result.get("decisions") or {}

    return {
        "segmentation": segmentation.get("summary", {}),
        "behavior": behavior.get("summary", {}),
        "forecast": forecast.get("summary", {}),
        "decisions_count": len(decisions.get("strategic_decisions", [])),
        "alerts_count": len(decisions.get("risk_alerts", [])),
    }


def _safe_json_load(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None
