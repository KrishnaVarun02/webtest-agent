from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, TypeVar

from pydantic import BaseModel

from .schemas import GenerationReport, GraphRun, NormalizedRecording, Recording, ReviewPlan
from .security import redact, sanitize_recording


SCHEMA_VERSION = 1
T = TypeVar("T", bound=BaseModel)


def _json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_plan(plan: ReviewPlan) -> ReviewPlan:
    data = plan.model_dump(mode="json", by_alias=True)
    # The inventory is copied from an already-sanitized NormalizedRecording and
    # is immutable through the review API. Re-redacting it would corrupt encoded
    # placeholders and JSON-schema property names such as `accessToken`.
    inventory = data.get("apiInventory", [])
    # Extractor values are schema-validated JSONPaths. A variable can
    # legitimately be named `api_token`; treating that key as captured secret
    # data would replace `$.accessToken` and corrupt the approved flow.
    extractor_paths = {
        (workflow.get("workflowId"), step.get("stepId")): step.get("extracts", {})
        for workflow in data.get("workflows", [])
        for step in workflow.get("steps", [])
    }
    safe_data = redact(data)
    safe_data["apiInventory"] = inventory
    for workflow in safe_data.get("workflows", []):
        for step in workflow.get("steps", []):
            key = (workflow.get("workflowId"), step.get("stepId"))
            if key in extractor_paths:
                step["extracts"] = extractor_paths[key]
    return ReviewPlan.model_validate(safe_data)


class SQLiteRepository:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS schema_meta (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recordings (
                    recording_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sanitized_recording_json TEXT NOT NULL,
                    normalized_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    recording_id TEXT NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plans_recording ON plans(recording_id);
                CREATE TABLE IF NOT EXISTS graph_runs (
                    run_id TEXT PRIMARY KEY,
                    recording_id TEXT NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
                    plan_id TEXT,
                    status TEXT NOT NULL,
                    current_node TEXT NOT NULL,
                    run_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_recording ON graph_runs(recording_id);
                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    recording_id TEXT NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
                    plan_id TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    html_path TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(f"unsupported SQLite schema version {row['version']}")
            connection.commit()

    def save_recording(self, recording: Recording, normalized: NormalizedRecording) -> None:
        safe_recording = sanitize_recording(recording)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO recordings(
                       recording_id, session_id, sanitized_recording_json, normalized_json, created_at
                   ) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(recording_id) DO UPDATE SET
                       session_id=excluded.session_id,
                       sanitized_recording_json=excluded.sanitized_recording_json,
                       normalized_json=excluded.normalized_json""",
                (
                    normalized.recording_id,
                    safe_recording.session_id,
                    _json(safe_recording),
                    _json(normalized),
                    now,
                ),
            )
            connection.commit()

    def get_recording(self, recording_id: str) -> Recording | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT sanitized_recording_json FROM recordings WHERE recording_id = ?", (recording_id,)
            ).fetchone()
        return Recording.model_validate_json(row[0]) if row else None

    def get_normalized(self, recording_id: str) -> NormalizedRecording | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT normalized_json FROM recordings WHERE recording_id = ?", (recording_id,)
            ).fetchone()
        return NormalizedRecording.model_validate_json(row[0]) if row else None

    def normalized_for_session(self, session_id: str) -> NormalizedRecording | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT normalized_json FROM recordings WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return NormalizedRecording.model_validate_json(row[0]) if row else None

    def save_plan(self, plan: ReviewPlan, *, expected_revision: int | None = None) -> ReviewPlan:
        safe = _safe_plan(plan)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT revision FROM plans WHERE plan_id = ?", (safe.plan_id,)).fetchone()
            if expected_revision is not None and (existing is None or existing["revision"] != expected_revision):
                connection.rollback()
                raise ValueError("plan revision conflict")
            connection.execute(
                """INSERT INTO plans(plan_id, recording_id, revision, status, plan_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(plan_id) DO UPDATE SET
                       recording_id=excluded.recording_id,
                       revision=excluded.revision,
                       status=excluded.status,
                       plan_json=excluded.plan_json,
                       updated_at=excluded.updated_at""",
                (safe.plan_id, safe.recording_id, safe.revision, safe.status, _json(safe), now),
            )
            connection.commit()
        return safe

    def get_plan(self, plan_id: str) -> ReviewPlan | None:
        with self._connection() as connection:
            row = connection.execute("SELECT plan_json FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
        return ReviewPlan.model_validate_json(row[0]) if row else None

    def latest_plan_for_recording(self, recording_id: str) -> ReviewPlan | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT plan_json FROM plans WHERE recording_id = ? ORDER BY revision DESC, updated_at DESC LIMIT 1",
                (recording_id,),
            ).fetchone()
        return ReviewPlan.model_validate_json(row[0]) if row else None

    def save_run(self, run: GraphRun) -> GraphRun:
        # Graph inputs have already crossed the recording/plan/generator/output
        # sanitization boundaries. Re-running a key-name redactor here would
        # corrupt structural JSON Schema fields such as `accessToken`.
        safe = GraphRun.model_validate(run.model_dump(mode="json", by_alias=True))
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO graph_runs(run_id, recording_id, plan_id, status, current_node, run_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET
                       plan_id=excluded.plan_id,
                       status=excluded.status,
                       current_node=excluded.current_node,
                       run_json=excluded.run_json,
                       updated_at=excluded.updated_at""",
                (
                    safe.run_id,
                    safe.recording_id,
                    safe.plan_id,
                    safe.status,
                    safe.current_node,
                    _json(safe),
                    safe.updated_at.isoformat(),
                ),
            )
            connection.commit()
        return safe

    def get_run(self, run_id: str) -> GraphRun | None:
        with self._connection() as connection:
            row = connection.execute("SELECT run_json FROM graph_runs WHERE run_id = ?", (run_id,)).fetchone()
        return GraphRun.model_validate_json(row[0]) if row else None

    def latest_run_for_recording(self, recording_id: str) -> GraphRun | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT run_json FROM graph_runs WHERE recording_id = ? ORDER BY updated_at DESC LIMIT 1",
                (recording_id,),
            ).fetchone()
        return GraphRun.model_validate_json(row[0]) if row else None

    def save_report(self, report: GenerationReport, html_path: Path | None = None) -> GenerationReport:
        safe = GenerationReport.model_validate(redact(report.model_dump(mode="json", by_alias=True)))
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO reports(report_id, recording_id, plan_id, report_json, html_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(report_id) DO UPDATE SET
                       report_json=excluded.report_json,
                       html_path=excluded.html_path""",
                (
                    safe.report_id,
                    safe.recording_id,
                    safe.plan_id,
                    _json(safe),
                    str(html_path) if html_path else None,
                    safe.created_at.isoformat(),
                ),
            )
            connection.commit()
        return safe

    def get_report(self, report_id: str) -> tuple[GenerationReport, str | None] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT report_json, html_path FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        if not row:
            return None
        return GenerationReport.model_validate_json(row["report_json"]), row["html_path"]

    def raw_database_text(self) -> str:
        """Diagnostic helper used by privacy tests; not exposed over HTTP."""
        with self._connection() as connection:
            rows = []
            for table, columns in {
                "recordings": "sanitized_recording_json, normalized_json",
                "plans": "plan_json",
                "graph_runs": "run_json",
                "reports": "report_json",
            }.items():
                rows.extend(" ".join(str(value) for value in row) for row in connection.execute(f"SELECT {columns} FROM {table}"))
        return "\n".join(rows)
