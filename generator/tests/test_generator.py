from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from webtest_generator import GenerationError, generate_project, repair_project


GENERATOR_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = GENERATOR_ROOT / "fixtures" / "approved-plan.json"


def fixture_plan() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def generated_text(project: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(project.rglob("*"))
        if path.is_file()
    )


class GeneratorContractTest(unittest.TestCase):
    def test_generates_complete_exact_maven_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = generate_project(fixture_plan(), Path(directory), "sample-api-tests")
            project = Path(manifest["projectDirectory"])
            for relative in (
                "pom.xml",
                "testng.xml",
                "README.md",
                ".env.example",
                "src/test/java/framework/Config.java",
                "src/test/java/framework/RequestExecutor.java",
                "src/test/java/framework/RequestDefinition.java",
                "src/test/java/framework/AuthProvider.java",
                "src/test/java/framework/NoAuthProvider.java",
                "src/test/java/framework/BearerTokenAuthProvider.java",
                "src/test/java/framework/BasicAuthProvider.java",
                "src/test/java/framework/ApiKeyAuthProvider.java",
                "src/test/java/framework/CookieAuthProvider.java",
                "src/test/java/framework/CustomAuthProvider.java",
                "src/test/java/framework/ScenarioContext.java",
                "src/test/java/framework/DynamicValueExtractor.java",
                "src/test/java/framework/TestDataFactory.java",
                "src/test/java/framework/PollingUtility.java",
                "src/test/java/framework/AssertionUtility.java",
                "src/test/java/framework/SecretRedactor.java",
                "src/test/java/generated/clients/GeneratedApiClient.java",
                "src/test/java/generated/listeners/WebTestReportListener.java",
                "src/test/resources/config/generation.json",
                "src/test/resources/recordings/source-recordings.json",
                "src/test/resources/flows/approved-plan.json",
            ):
                self.assertTrue((project / relative).is_file(), relative)
            scenarios = list((project / "src/test/java/generated/scenarios").glob("*Test.java"))
            self.assertEqual(1, len(scenarios))
            pom = (project / "pom.xml").read_text(encoding="utf-8")
            for version in ("21", "7.12.0", "6.0.1", "2.22.2", "4.3.0", "5.1.2", "3.6.0", "3.14.1"):
                self.assertIn(version, pom)
            source = scenarios[0].read_text(encoding="utf-8")
            for group in ("smoke", "regression", "positive", "negative", "asynchronous", "destructive"):
                self.assertIn(f'"{group}"', source)
            self.assertIn("config.requireDestructiveOptIn()", source)
            self.assertIn("<webtest.excludedGroups>destructive</webtest.excludedGroups>", pom)
            self.assertIn("<excludedGroups>${webtest.excludedGroups}</excludedGroups>", pom)
            self.assertIn('<exclude name="destructive"/>', (project / "testng.xml").read_text(encoding="utf-8"))

    def test_generation_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = Path(generate_project(fixture_plan(), Path(first), "same-project")["projectDirectory"])
            two = Path(generate_project(fixture_plan(), Path(second), "same-project")["projectDirectory"])
            one_files = {path.relative_to(one): path.read_bytes() for path in one.rglob("*") if path.is_file()}
            two_files = {path.relative_to(two): path.read_bytes() for path in two.rglob("*") if path.is_file()}
            self.assertEqual(one_files, two_files)

    def test_manifest_hashes_every_non_manifest_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(generate_project(fixture_plan(), Path(directory), "manifest-check")["projectDirectory"])
            manifest = json.loads((project / "generation-manifest.json").read_text(encoding="utf-8"))
            for entry in manifest["files"]:
                content = (project / entry["path"]).read_bytes()
                self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest(), entry["path"])

    def test_generation_report_contains_evidence_coverage_and_dependencies(self) -> None:
        plan = fixture_plan()
        plan["assumptions"] = ["Top-level approved assumption"]
        plan["uncertainties"] = ["Top-level approved uncertainty"]
        plan["workflows"][0]["assumptions"] = ["Workflow approved assumption"]
        plan["workflows"][0]["uncertainties"] = ["Workflow approved uncertainty"]
        plan["workflows"][0]["scenarios"][0]["uncertainty"] = "Scenario approved uncertainty"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(generate_project(plan, Path(directory), "report-check")["projectDirectory"])
            report = json.loads((project / "generation-report.json").read_text(encoding="utf-8"))
            for key in (
                "uiCoverageMap",
                "apiInventory",
                "endpointExamples",
                "workflows",
                "testMatrix",
                "assumptions",
                "uncertainties",
                "unsupportedTraffic",
                "dataDependencies",
                "sourceRecordingIds",
                "generatedFiles",
            ):
                self.assertIn(key, report)
            self.assertTrue(report["uiCoverageMap"])
            action = report["uiCoverageMap"][0]["actions"][0]
            self.assertTrue(action["actionId"])
            self.assertTrue(action["operationIds"])
            self.assertTrue(report["endpointExamples"])
            self.assertTrue(report["endpointExamples"][0]["requestId"])
            self.assertIn("response", report["endpointExamples"][0])
            self.assertTrue(report["dataDependencies"])
            dependency = report["dataDependencies"][0]
            for key in (
                "workflowId",
                "stepId",
                "operationId",
                "sourceStepId",
                "sourceJsonPath",
                "targetStepId",
                "targetLocation",
                "variableName",
            ):
                self.assertIn(key, dependency)
            self.assertIn("Top-level approved assumption", report["assumptions"])
            self.assertIn("Workflow approved assumption", report["assumptions"])
            self.assertIn("Top-level approved uncertainty", report["uncertainties"])
            self.assertIn("Workflow approved uncertainty", report["uncertainties"])
            self.assertIn("Scenario approved uncertainty", report["uncertainties"])

    def test_requires_plan_and_workflow_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            draft = fixture_plan()
            draft["status"] = "draft"
            with self.assertRaisesRegex(GenerationError, "status='approved'"):
                generate_project(draft, Path(directory), "draft")
            rejected = fixture_plan()
            rejected["workflows"][0]["approval"] = "rejected"
            with self.assertRaisesRegex(GenerationError, "approved workflow"):
                generate_project(rejected, Path(directory), "rejected")

    def test_rejects_unsafe_project_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../escape", ".hidden", "has/slash", "", "x" * 81):
                with self.subTest(name=name), self.assertRaises(GenerationError):
                    generate_project(fixture_plan(), Path(directory), name)

    def test_never_persists_seeded_secrets_or_credentials(self) -> None:
        plan = fixture_plan()
        marker = "LEAK-SENTINEL-79e3c82b"
        login = next(value for value in plan["apiInventory"] if value["operationId"] == "post-login")
        login["examples"][0]["requestBody"] = {"username": marker + "-user", "password": marker + "-password"}
        login["examples"][0]["requestHeaders"]["Authorization"] = "Bearer " + marker
        login["examples"][0]["responseBody"]["accessToken"] = marker + "-token"
        plan["suppliedTestData"] = {"TEST_USERNAME": marker + "-supplied-user", "password": marker + "-supplied"}
        plan["workflows"][0]["scenarios"][0]["assertions"].append(
            {"kind": "value", "path": "$.accessToken", "expected": marker, "evidence": "seeded redaction test"}
        )
        for operation in plan["apiInventory"]:
            operation["origin"] = "https://real-target.example:9443"
            for example in operation["examples"]:
                example["url"] = "https://real-target.example:9443" + operation["normalizedPath"]
        with tempfile.TemporaryDirectory() as directory:
            project = Path(generate_project(plan, Path(directory), "redaction-check")["projectDirectory"])
            text = generated_text(project)
            self.assertNotIn(marker, text)
            self.assertIn("${TEST_USERNAME}", text)
            self.assertIn("${TEST_PASSWORD}", text)
            self.assertIn("${API_TOKEN}", text)
            self.assertNotIn("real-target.example", text)

    def test_never_persists_seeded_dynamic_ids_or_timestamps_anywhere(self) -> None:
        plan = fixture_plan()
        record_id = "11111111-1111-4111-8111-111111111111"
        job_id = "22222222-2222-4222-8222-222222222222"
        timestamp = "2026-09-21T10:00:03.123456Z"
        plan["createdAt"] = timestamp
        plan["updatedAt"] = timestamp
        operation = next(value for value in plan["apiInventory"] if value["operationId"] == "get-record")
        operation["pathParameters"][0]["samples"] = [record_id]
        example = operation["examples"][0]
        example["timestamp"] = timestamp
        example["url"] = f"https://seeded.example/api/records/{record_id}?jobId={job_id}"
        example["requestBody"] = {"recordId": record_id, "jobId": job_id, "requestedAt": timestamp}
        example["responseBody"] = {
            "id": record_id,
            "jobId": job_id,
            "createdAt": timestamp,
            "status": "processed",
        }
        plan["workflows"][0]["scenarios"][0]["assertions"].extend(
            [
                {"kind": "value", "path": "$.id", "expected": record_id, "evidence": "recorded id"},
                {
                    "kind": "value",
                    "path": "$.createdAt",
                    "expected": timestamp,
                    "evidence": "recorded timestamp",
                },
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            project = Path(
                generate_project(plan, Path(directory), "dynamic-redaction-check")["projectDirectory"]
            )
            text = generated_text(project)
            for marker in (record_id, job_id, timestamp, "seeded.example"):
                self.assertNotIn(marker, text)
            self.assertIn("${RESOURCE_ID}", text)
            self.assertIn("${RECORDED_TIMESTAMP}", text)
            self.assertIn("$.id", text)
            self.assertIn('"required": [', text)

    def test_preserves_structural_json_paths_and_mutates_one_valid_field(self) -> None:
        plan = fixture_plan()
        create = next(value for value in plan["apiInventory"] if value["operationId"] == "post-records")
        invalid = copy.deepcopy(create["examples"][0])
        invalid.update(
            requestId="000-invalid-example",
            timestamp="2025-01-01T00:00:00Z",
            requestBody={"quantity": 2},
            responseStatus=400,
            responseBody={"error": "name is required"},
        )
        create["examples"].insert(0, invalid)
        with tempfile.TemporaryDirectory() as directory:
            project = Path(generate_project(plan, Path(directory), "evidence-check")["projectDirectory"])
            source = next((project / "src/test/java/generated/scenarios").glob("*Test.java")).read_text(encoding="utf-8")
            self.assertIn('DynamicValueExtractor.extract(response1, "$.accessToken"', source)
            self.assertIn('\\"name\\":\\"Generated record\\"', source)
            negative = source.split("rejectACreateRequestMissingName", 1)[1].split("@Test", 1)[0]
            self.assertIn('body(TestDataFactory.json("{\\\"quantity\\\":2}"))', negative)
            self.assertNotIn('DynamicValueExtractor.extract(response2, "$.id"', negative)

    def test_preserves_format_and_type_assertion_metadata_for_dynamic_fields(self) -> None:
        plan = fixture_plan()
        positive = next(
            value
            for value in plan["workflows"][0]["scenarios"]
            if value["scenarioId"] == "crud-positive"
        )
        positive["assertions"].extend(
            [
                {
                    "kind": "status",
                    "path": None,
                    "expected": 200,
                    "evidence": "approved response status",
                },
                {
                    "kind": "content_type",
                    "path": None,
                    "expected": "application/json",
                    "evidence": "approved response content type",
                },
                {
                    "kind": "format",
                    "path": "$.createdAt",
                    "expected": "date-time",
                    "evidence": "approved timestamp format",
                },
                {
                    "kind": "field_type",
                    "path": "$.id",
                    "expected": "string",
                    "evidence": "approved identifier type",
                },
            ]
        )
        get_record = next(
            value for value in plan["apiInventory"] if value["operationId"] == "get-record"
        )
        get_record["examples"][0]["responseBody"]["createdAt"] = "2026-09-21T10:00:03Z"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(
                generate_project(plan, Path(directory), "assertion-metadata-check")["projectDirectory"]
            )
            source = next((project / "src/test/java/generated/scenarios").glob("*Test.java")).read_text(
                encoding="utf-8"
            )
            self.assertIn('AssertionUtility.assertFormat(response4, "$.id", "uuid")', source)
            self.assertIn(
                'AssertionUtility.assertFormat(response4, "$.createdAt", "date-time")', source
            )
            self.assertIn('AssertionUtility.assertJsonType(response4, "$.id", "string")', source)
            self.assertIn('AssertionUtility.assertStatus(response4, 200)', source)
            self.assertIn(
                'AssertionUtility.assertContentType(response4, "application/json")', source
            )
            self.assertNotIn('assertFormat(response4, "$.id", "${RESOURCE_ID}")', source)

    def test_injects_setup_and_transitive_path_dependencies(self) -> None:
        plan = fixture_plan()
        workflow = plan["workflows"][0]
        get_step = next(value for value in workflow["steps"] if value["stepId"] == "get-record")
        get_step["dependencies"][0]["targetLocation"] = "path[2]"
        get_step["dependencies"][0]["variableName"] = "created_id"
        create_step = next(value for value in workflow["steps"] if value["stepId"] == "create-record")
        create_step["extracts"] = {"created_id": "$.id"}
        positive = next(value for value in workflow["scenarios"] if value["scenarioId"] == "crud-positive")
        positive["stepIds"] = ["get-record"]
        positive["expectedStatuses"] = [200]
        with tempfile.TemporaryDirectory() as directory:
            project = Path(generate_project(plan, Path(directory), "dependency-check")["projectDirectory"])
            source = next((project / "src/test/java/generated/scenarios").glob("*Test.java")).read_text(encoding="utf-8")
            method = source.split("createUpdateAndReadARecord", 1)[1].split("@Test", 1)[0]
            self.assertIn('RequestDefinition.builder("POST", "/api/login")', method)
            self.assertIn('RequestDefinition.builder("POST", "/api/records")', method)
            self.assertIn('RequestDefinition.builder("GET", "/api/records/${created_id}")', method)

    def test_origin_and_environment_safety_is_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(generate_project(fixture_plan(), Path(directory), "safety-check")["projectDirectory"])
            config = (project / "src/test/java/framework/Config.java").read_text(encoding="utf-8")
            executor = (project / "src/test/java/framework/RequestExecutor.java").read_text(encoding="utf-8")
            self.assertIn('required("WEBTEST_BASE_URL")', config)
            self.assertIn('required("WEBTEST_AUTHORIZED_ORIGINS")', config)
            self.assertIn("validateAuthorizedOrigin", config)
            self.assertIn("validateRelativeRequestPath", executor)
            self.assertNotIn("127.0.0.1", executor)
            self.assertNotIn("https://", executor)

    def test_repair_project_atomically_restores_generated_compile_drift(self) -> None:
        plan = fixture_plan()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(generate_project(plan, Path(directory), "repair-check")["projectDirectory"])
            source = next((project / "src/test/java/generated/scenarios").glob("*Test.java"))
            original = source.read_bytes()
            source.write_text(source.read_text(encoding="utf-8") + "\nthis will not compile\n", encoding="utf-8")
            repaired = repair_project(
                project_path=project,
                diagnostics="[ERROR] COMPILATION ERROR: illegal start of type",
                plan=plan,
            )
            self.assertTrue(repaired)
            self.assertEqual(original, source.read_bytes())

    def test_repair_project_refuses_assertion_or_runtime_failures(self) -> None:
        plan = fixture_plan()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(generate_project(plan, Path(directory), "repair-refusal")["projectDirectory"])
            source = next((project / "src/test/java/generated/scenarios").glob("*Test.java"))
            source.write_text(source.read_text(encoding="utf-8") + "\n// preserved drift\n", encoding="utf-8")
            drifted = source.read_bytes()
            repaired = repair_project(
                project_path=project,
                diagnostics=(
                    "Tests run: 1, Failures: 1\n"
                    "java.lang.AssertionError: expected HTTP 200 but got 500\n"
                    "Failed to execute goal org.apache.maven.plugins:maven-surefire-plugin"
                ),
                plan=plan,
            )
            self.assertFalse(repaired)
            self.assertEqual(drifted, source.read_bytes())

    def test_cli_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(GENERATOR_ROOT)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "webtest_generator.cli",
                    "generate",
                    "--plan",
                    str(FIXTURE),
                    "--output-root",
                    directory,
                    "--project-name",
                    "cli-check",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            manifest = json.loads(result.stdout)
            self.assertEqual("cli-check", manifest["projectName"])
            self.assertTrue((Path(directory) / "cli-check" / "pom.xml").is_file())


if __name__ == "__main__":
    unittest.main()
