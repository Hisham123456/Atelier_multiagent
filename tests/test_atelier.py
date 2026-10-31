import asyncio
from dataclasses import replace
from datetime import datetime
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import zipfile

from fastapi.testclient import TestClient
from pydantic import ValidationError

from atelier.config import Settings
from atelier.demo import demo_response, CONTRACT
from atelier.orchestrator import Orchestrator
from atelier.provider import AgentError, ModelGateway
from atelier.schemas import AnswerQuestion, Bundle, CreateRun, Plan, SecurityReview
from atelier.server import create_app
from atelier.storage import Store
from atelier.workspace import Workspace


class SchemaTests(unittest.TestCase):
    def test_plan_parallel_roots(self):
        plan = Plan.model_validate(demo_response("chief", {}))
        self.assertEqual(len(plan.tasks), 4)
        self.assertTrue(all(not task.dependencies for task in plan.tasks))

    def test_cycle_rejected(self):
        data = demo_response("chief", {})
        data["tasks"][0]["dependencies"] = ["frontend"]
        data["tasks"][1]["dependencies"] = ["backend"]
        with self.assertRaises(ValidationError):
            Plan.model_validate(data)

    def test_unknown_dependency_rejected(self):
        data = demo_response("chief", {})
        data["tasks"][0]["dependencies"] = ["missing"]
        with self.assertRaises(ValidationError):
            Plan.model_validate(data)

    def test_duplicate_writer_rejected(self):
        data = demo_response("chief", {})
        data["tasks"][1]["area"] = "backend"
        with self.assertRaises(ValidationError):
            Plan.model_validate(data)

    def test_blank_request_and_empty_revision_rejected(self):
        with self.assertRaises(ValidationError):
            CreateRun(prompt="     ")
        with self.assertRaises(ValidationError):
            AnswerQuestion(question_id="q", action="revise", answer="")


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.workspace = Workspace(Path(self.folder.name))

    def bundle(self, name, content="print('test')"):
        return Bundle.model_validate({"summary": "ok", "files": [{"path": name, "content": content}]})

    async def test_paths_and_owner_checked_before_writing(self):
        for name in ("../outside.py", "C:/outside.py", "/outside.py", "backend/../../outside.py", "backend\\bad.py", "backend/CON.py", "backend/.env"):
            with self.subTest(name=name):
                with self.assertRaises((ValueError, AgentError)):
                    self.workspace.apply(self.bundle(name), "backend")
        with self.assertRaises(AgentError):
            self.workspace.apply(self.bundle("frontend/index.html"), "backend")

    async def test_bundle_is_validated_atomically(self):
        bundle = Bundle.model_validate({"summary": "x", "files": [{"path": "backend/good.py", "content": "ok"}, {"path": "../bad", "content": "bad"}]})
        with self.assertRaises(ValueError):
            self.workspace.apply(bundle, "backend")
        self.assertFalse((self.workspace.root / "backend/good.py").exists())

    async def test_demo_application_passes_real_tests_and_archive(self):
        self.workspace.scaffold(CONTRACT)
        for area in ("backend", "frontend", "tests", "docs"):
            self.workspace.apply(Bundle.model_validate(demo_response("worker", {"task": {"area": area}})), area)
        result = await self.workspace.test()
        self.assertTrue(result["passed"], result["output"])
        self.assertEqual(result["tests"], 8)
        with zipfile.ZipFile(io.BytesIO(self.workspace.archive())) as archive:
            self.assertIn("run_app.py", archive.namelist())
            self.assertNotIn("_atelier_tests.py", archive.namelist())

    async def test_zero_tests_is_failure(self):
        self.workspace.scaffold(CONTRACT)
        result = await self.workspace.test()
        self.assertFalse(result["passed"])
        self.assertEqual(result["tests"], 0)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = Settings(root=Path(self.folder.name), demo_delay=0)
        self.store = Store(self.settings.data_dir)
        self.run = self.store.create("Créer une application", "demo", False)

    def gateway(self, settings=None, client=None):
        return ModelGateway(settings or self.settings, self.store, self.run, lambda *args: self.store.save(self.run), client)

    async def test_call_limit_and_demo_accounting(self):
        gateway = self.gateway(replace(self.settings, max_calls=1))
        result = await gateway.call("chief", {})
        self.assertEqual(result.name, "Mes tâches")
        self.assertIsNone(self.run["calls"][0]["input_tokens"])
        with self.assertRaises(AgentError):
            await gateway.call("chief", {})
        record = json.loads((self.store.folder(self.run["id"]) / "calls.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("response", record)
        self.assertGreaterEqual(record["duration_ms"], 0)

    async def test_live_transport_parses_schema_and_records_usage(self):
        self.run["mode"] = "live"
        arguments = {}
        async def create(**kwargs):
            arguments.update(kwargs)
            return SimpleNamespace(status="completed", output_text=json.dumps(demo_response("router", {"task": {"area": "docs"}})), usage=SimpleNamespace(input_tokens=100, output_tokens=50))
        client = SimpleNamespace(responses=SimpleNamespace(create=create))
        gateway = self.gateway(replace(self.settings, api_key="test-not-a-real-key", economy_input_price=1, economy_output_price=2), client)
        result = await gateway.call("router", {"task": {"area": "docs"}})
        self.assertEqual(result.specialist, "writer")
        self.assertTrue(arguments["text"]["format"]["strict"])
        self.assertFalse(arguments["store"])
        self.assertEqual(self.run["calls"][0]["input_tokens"], 100)
        self.assertAlmostEqual(self.run["calls"][0]["cost_usd"], .0002)
        self.assertNotIn("test-not-a-real-key", (self.store.folder(self.run["id"]) / "calls.jsonl").read_text(encoding="utf-8"))

    async def test_incomplete_response_does_not_apply_result(self):
        self.run["mode"] = "live"
        async def create(**kwargs):
            return SimpleNamespace(status="incomplete", output_text="", usage=None)
        gateway = self.gateway(replace(self.settings, api_key="test"), SimpleNamespace(responses=SimpleNamespace(create=create)))
        with self.assertRaises(AgentError):
            await gateway.call("chief", {})
        self.assertEqual(self.run["calls"][0]["status"], "failed")


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = Settings(root=Path(self.folder.name), demo_delay=.003, max_repairs=0)
        self.store = Store(self.settings.data_dir)
        self.engine = Orchestrator(self.settings, self.store)

    async def asyncTearDown(self):
        await self.engine.close()

    async def finish(self, engine, run, revise_stage=None):
        revised = False
        for _ in range(1000):
            for question in run["questions"]:
                if question["status"] == "pending" and question["blocking"]:
                    revision = question["stage"] == revise_stage and not revised
                    engine.answer(run["id"], AnswerQuestion(question_id=question["id"], action="revise" if revision else "continue", answer="Préciser les critères" if revision else ""))
                    revised |= revision
            if engine.jobs[run["id"]].done():
                await engine.jobs[run["id"]]
                return run
            await asyncio.sleep(.01)
        self.fail("L'exécution ne termine pas.")

    async def test_complete_workflow_parallelism_liaison_and_security(self):
        run = self.engine.start(CreateRun(prompt="Créer une liste de tâches"))
        await self.finish(self.engine, run)
        self.assertEqual(run["status"], "completed", run["error"])
        self.assertTrue(run["security"]["approved"])
        self.assertEqual(run["test_result"]["tests"], 8)
        self.assertEqual([q["stage"] for q in run["questions"]], ["plan", "progress", "final"])
        calls = [call for call in run["calls"] if call["role"] == "worker"]
        self.assertEqual(len(calls), 4)
        overlap = any(datetime.fromisoformat(a["started_at"]) < datetime.fromisoformat(b["finished_at"])
                      and datetime.fromisoformat(b["started_at"]) < datetime.fromisoformat(a["finished_at"])
                      for index, a in enumerate(calls) for b in calls[index + 1:])
        self.assertTrue(overlap, "Les spécialistes doivent se chevaucher réellement.")
        for task in run["tasks"]:
            self.assertIsNotNone(task["routing_reason"])
            self.assertIsNotNone(task["model_reason"])

    async def test_plan_only_never_calls_worker_or_writes_code(self):
        run = self.engine.start(CreateRun(prompt="Créer une petite application", plan_only=True))
        await self.finish(self.engine, run)
        self.assertEqual(run["status"], "prepared")
        self.assertFalse(any(call["role"] == "worker" for call in run["calls"]))
        self.assertEqual(list((self.store.folder(run["id"]) / "project").iterdir()), [])

    async def test_user_precision_replans_before_work(self):
        run = self.engine.start(CreateRun(prompt="Créer une petite application", plan_only=True))
        await self.finish(self.engine, run, revise_stage="plan")
        self.assertEqual(sum(call["role"] == "chief" for call in run["calls"]), 2)
        self.assertIn("Préciser", run["questions"][0]["answer"])

    async def test_final_feedback_returns_to_specialists_then_rechecks(self):
        self.engine = Orchestrator(replace(self.settings, max_repairs=1), self.store)
        run = self.engine.start(CreateRun(prompt="Créer une liste de tâches"))
        await self.finish(self.engine, run, revise_stage="final")
        self.assertEqual(run["status"], "completed", run["error"])
        self.assertEqual(run["repairs"], 1)
        self.assertEqual(sum(call["role"] == "worker" for call in run["calls"]), 8)
        self.assertEqual(sum(call["role"] == "security" for call in run["calls"]), 4)
        self.assertEqual(sum(call["role"] == "chief" for call in run["calls"]), 2)

    async def test_security_high_blocks_validation(self):
        class UnsafeGateway(ModelGateway):
            async def call(self, role, *args, **kwargs):
                value = await super().call(role, *args, **kwargs)
                if role == "security":
                    return SecurityReview(approved=True, summary="Problème détecté", findings=[{"severity": "high", "path": "backend/app.py", "description": "Exemple de constat", "recommendation": "Corriger"}])
                return value
        self.engine = Orchestrator(self.settings, self.store, UnsafeGateway)
        run = self.engine.start(CreateRun(prompt="Créer une liste de tâches"))
        await self.finish(self.engine, run)
        self.assertEqual(run["status"], "needs_attention")

    async def test_cancellation_while_waiting_for_user(self):
        run = self.engine.start(CreateRun(prompt="Créer une petite application"))
        while run["status"] != "awaiting_input":
            await asyncio.sleep(.01)
        await self.engine.cancel(run["id"])
        self.assertEqual(run["status"], "cancelled")
        self.assertTrue(all(q["status"] != "pending" for q in run["questions"]))
        self.assertFalse(self.engine.waiters)

    async def test_single_active_run_and_missing_key(self):
        with self.assertRaises(AgentError):
            self.engine.start(CreateRun(prompt="Créer une petite application", mode="live"))
        run = self.engine.start(CreateRun(prompt="Créer une petite application"))
        with self.assertRaises(AgentError):
            self.engine.start(CreateRun(prompt="Créer une autre application"))
        await self.engine.cancel(run["id"])

    async def test_restart_marks_unfinished_runs(self):
        run = self.store.create("Créer une application", "demo", False)
        run["status"] = "building"
        self.store.save(run)
        Orchestrator(self.settings, self.store)
        self.assertEqual(self.store.read(run["id"])["status"], "interrupted")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        settings = Settings(root=Path(self.folder.name), demo_delay=0)
        self.client = TestClient(create_app(settings))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {"X-Atelier-Token": self.client.get("/api/config").json()["token"]}

    def test_home_and_config_do_not_expose_key(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sécurité", response.text)
        config = self.client.get("/api/config").json()
        self.assertNotIn("api_key", config)
        self.assertFalse(config["live_available"])

    def test_post_requires_local_token_and_origin(self):
        self.assertEqual(self.client.post("/api/runs", json={"prompt": "Créer un projet"}).status_code, 403)
        headers = {**self.headers, "Origin": "https://other.example"}
        self.assertEqual(self.client.post("/api/runs", headers=headers, json={"prompt": "Créer un projet"}).status_code, 403)

    def test_request_validation_and_unknown_run(self):
        self.assertEqual(self.client.post("/api/runs", headers=self.headers, json={"prompt": " "}).status_code, 422)
        self.assertEqual(self.client.get("/api/runs/not-a-run").status_code, 404)


if __name__ == "__main__":
    unittest.main()
