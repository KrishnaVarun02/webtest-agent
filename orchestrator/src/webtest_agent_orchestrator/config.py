from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
ORCHESTRATOR_DIR = PACKAGE_DIR.parents[1]
MONOREPO_DIR = ORCHESTRATOR_DIR.parent


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.getenv(name, default).split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path
    generated_root: Path
    report_root: Path
    generator_root: Path
    llm_provider: str = "offline"
    openai_model: str = "gpt-5-mini"
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    )
    max_recording_requests: int = 10_000
    max_payload_bytes: int = 1_000_000
    validation_timeout_seconds: int = 300

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=Path(os.getenv("WEBTEST_DB_PATH", ORCHESTRATOR_DIR / "data" / "webtest-agent.db")),
            generated_root=Path(os.getenv("WEBTEST_GENERATED_ROOT", MONOREPO_DIR / "generated")),
            report_root=Path(os.getenv("WEBTEST_REPORT_ROOT", ORCHESTRATOR_DIR / "reports")),
            generator_root=Path(os.getenv("WEBTEST_GENERATOR_ROOT", MONOREPO_DIR / "generator")),
            llm_provider=os.getenv("WEBTEST_LLM_PROVIDER", "offline").strip().lower(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
            cors_origins=_csv(
                "WEBTEST_CORS_ORIGINS",
                "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000",
            ),
            max_recording_requests=int(os.getenv("WEBTEST_MAX_RECORDING_REQUESTS", "10000")),
            max_payload_bytes=int(os.getenv("WEBTEST_MAX_PAYLOAD_BYTES", "1000000")),
            validation_timeout_seconds=int(os.getenv("WEBTEST_VALIDATION_TIMEOUT_SECONDS", "300")),
        )

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.generated_root.mkdir(parents=True, exist_ok=True)
        self.report_root.mkdir(parents=True, exist_ok=True)

