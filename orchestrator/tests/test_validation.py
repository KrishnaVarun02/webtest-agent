from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from webtest_agent_orchestrator.services import ValidationService


def test_validation_refuses_paths_outside_generated_root(settings, tmp_path: Path) -> None:
    try:
        ValidationService(settings).validate(tmp_path / "outside")
    except ValueError as exc:
        assert "generated root" in str(exc)
    else:
        raise AssertionError("outside validation path was accepted")


def test_validation_reports_missing_pom(settings) -> None:
    project = settings.generated_root / "empty"
    project.mkdir(parents=True)
    result = ValidationService(settings).validate(project)
    assert not result.success
    assert result.attempts == 0
    assert "pom.xml" in result.sanitized_output


def test_validation_repairs_at_most_twice_and_redacts_output(settings, monkeypatch) -> None:
    project = settings.generated_root / "broken"
    project.mkdir(parents=True)
    (project / "pom.xml").write_text("<project/>", encoding="utf-8")
    service = ValidationService(settings)
    monkeypatch.setattr("webtest_agent_orchestrator.services.shutil.which", lambda _: "/usr/bin/mvn")
    monkeypatch.setattr(
        "webtest_agent_orchestrator.services.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="password=seeded-secret", stderr="compile failed"),
    )
    monkeypatch.setattr(service, "_repair", lambda *args, **kwargs: True)
    result = service.validate(project, max_repair_attempts=2)
    assert result.attempts == 3
    assert "seeded-secret" not in result.sanitized_output
    assert "${REDACTED}" in result.sanitized_output
