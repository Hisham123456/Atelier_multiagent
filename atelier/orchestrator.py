import asyncio
from uuid import uuid4

from .provider import AgentError, ModelGateway
from .schemas import Task
from .storage import now
from .workspace import Workspace

SPECIALISTS = {"backend": "backend", "frontend": "frontend", "tests": "tester", "docs": "writer"}
TERMINAL = {"completed", "prepared", "needs_attention", "failed", "cancelled", "interrupted"}


async def together(coroutines):
    """Cancel and await siblings on failure; no task outlives the run."""
    jobs = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*jobs)
    except BaseException:
        for job in jobs:
            if not job.done():
                job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        raise


class Orchestrator:
    def __init__(self, settings, store, gateway_factory=ModelGateway):
        self.settings, self.store = settings, store
        self.gateway_factory = gateway_factory
        self.jobs = {}
        self.current = {}
        self.waiters = {}
        for run in store.list():
            if run["status"] not in TERMINAL:
                run.update(status="interrupted", finished_at=now(),
                           error="Le serveur a été arrêté pendant cette exécution. Relance une nouvelle demande.")
                for task in run["tasks"]:
                    if task["status"] not in {"completed", "prepared"}:
                        task["status"] = "interrupted"
                for call in run["calls"]:
                    if call["status"] == "running":
                        call["status"] = "interrupted"
                for question in run["questions"]:
                    if question["status"] == "pending":
                        question["status"] = "closed"
                store.save(run)

    def emit(self, run, kind, agent, message, task_id=None):
        run["events"].append({"id": len(run["events"]) + 1, "at": now(), "kind": kind,
                              "agent": agent, "task_id": task_id, "message": message})
        self.store.save(run)

    def start(self, request):
        if any(not job.done() for job in self.jobs.values()):
            raise AgentError("Une équipe travaille déjà. Attends la fin ou arrête son exécution.")
        if request.mode == "live" and not self.settings.api_key:
            raise AgentError("Configure OPENAI_API_KEY dans .env et redémarre pour utiliser les modèles.")
        run = self.store.create(request.prompt, request.mode, request.plan_only)
        self.current[run["id"]] = run
        self.jobs[run["id"]] = asyncio.create_task(self.execute(run))
        return run

    async def cancel(self, run_id):
        job = self.jobs.get(run_id)
        if job and not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            # A task cancelled before its coroutine starts cannot run its finally block.
            run = self.current[run_id]
            if run["status"] not in TERMINAL:
                run.update(status="cancelled", finished_at=now())
                self.store.save(run)
        return self.store.read(run_id)

    async def close(self):
        await together([self.cancel(run_id) for run_id in list(self.jobs)])

    def answer(self, run_id, response):
        run = self.current.get(run_id)
        if not run or run["status"] in TERMINAL:
            raise AgentError("Cette équipe n'attend plus de réponse. Lance une nouvelle mission pour poursuivre.")
        question = next((item for item in run["questions"] if item["id"] == response.question_id), None)
        if not question or question["status"] != "pending":
            raise AgentError("Cette question a déjà été traitée ou remplacée par un nouveau point d'étape.")
        question.update(status="answered", answer=response.answer.strip(), action=response.action,
                        answered_at=now(), consumed=False)
        self.emit(run, "user_feedback", "user", response.answer.strip() or "Continuer sans changement.")
        waiter = self.waiters.get(question["id"])
        if waiter:
            waiter.set()
        return run

    async def execute(self, run):
        def emit(kind, agent, message, task_id=None):
            self.emit(run, kind, agent, message, task_id)
        gateway = self.gateway_factory(self.settings, self.store, run, emit)
        workspace = Workspace(self.store.folder(run["id"]) / "project")

        def feedback():
            return [{key: item.get(key) for key in ("stage", "question", "action", "answer")}
                    for item in run["questions"] if item["status"] == "answered"]

        async def checkpoint(stage, blocking):
            if not blocking and any(item["status"] == "pending" for item in run["questions"]):
                return None
            message = await gateway.call("liaison", {"stage": stage, "request": run["prompt"],
                                "plan": run["plan"], "tasks": run["tasks"], "tests": run["test_result"],
                                "security": run["security"], "previous_answers": feedback()})
            if blocking:
                for item in run["questions"]:
                    if item["status"] == "pending":
                        item["status"] = "superseded"
            question = {"id": uuid4().hex, "stage": stage, **message.model_dump(), "blocking": blocking,
                        "status": "pending", "created_at": now(), "answer": None, "action": None,
                        "answered_at": None, "consumed": False}
            waiter = asyncio.Event()
            self.waiters[question["id"]] = waiter
            run["questions"].append(question)
            previous = run["status"]
            if blocking:
                run["status"] = "awaiting_input"
            emit("question", "liaison", message.question)
            if blocking:
                try:
                    await waiter.wait()
                    run["status"] = previous
                finally:
                    self.waiters.pop(question["id"], None)
            return question

        try:
            run["status"] = "planning"
            emit("phase", "chief", "Le chef découpe la demande et fixe le contrat commun.")
            plan = await gateway.call("chief", {"request": run["prompt"]}, "advanced")
            def set_plan(value):
                run["plan"] = value.model_dump()
                run["tasks"] = [{**task.model_dump(), "status": "pending", "specialist": None,
                                 "routing_reason": None, "tier": None, "model": None, "model_reason": None,
                                 "started_at": None, "finished_at": None, "summary": ""} for task in value.tasks]

            async def confirm_plan(value):
                for revision in range(3):
                    set_plan(value)
                    confirmation = await checkpoint("plan", True)
                    confirmation["consumed"] = True
                    if confirmation["action"] == "continue":
                        return value
                    if revision == 2:
                        raise AgentError("Deux adaptations du plan ont été réalisées. Relance une mission avec le périmètre précisé.")
                    value = await gateway.call("chief", {"request": run["prompt"], "user_feedback": feedback(),
                                                        "previous_plan": value.model_dump()}, "advanced")
                return value

            plan = await confirm_plan(plan)
            run["status"] = "routing"
            emit("phase", "router", "Le routeur et le sélecteur préparent les missions.")

            async def prepare(task):
                payload = {"task": task, "contract": plan.contract}
                routing = await gateway.call("router", payload, task_id=task["id"])
                if routing.specialist != SPECIALISTS[task["area"]]:
                    raise AgentError("Le routeur a choisi un spécialiste incompatible avec la zone de fichiers.")
                choice = await gateway.call("selector", payload, task_id=task["id"])
                task.update(specialist=routing.specialist, routing_reason=routing.reason, tier=choice.tier,
                            model=self.settings.model(choice.tier), model_reason=choice.reason,
                            status="prepared" if run["plan_only"] else "ready")
                emit("task_prepared", "selector", choice.reason, task["id"])

            await together([prepare(task) for task in run["tasks"]])
            if run["plan_only"]:
                run.update(status="prepared", summary="Plan, spécialistes et modèles prêts. Aucun code n'a été généré.")
                return
            workspace.scaffold(plan.contract)
            run["status"] = "building"
            emit("phase", "chief", "Les spécialistes commencent les tâches indépendantes.")

            async def work(task, feedback=None):
                task.update(status="running", started_at=now(), finished_at=None)
                emit("task_started", task["specialist"], task["title"], task["id"])
                try:
                    if feedback:
                        choice = await gateway.call("selector", {"task": task, "repair": True, "feedback": feedback}, task_id=task["id"])
                        task.update(tier=choice.tier, model=self.settings.model(choice.tier), model_reason=choice.reason)
                    payload = {"request": run["prompt"], "contract": plan.contract, "task": task,
                               "specialist": task["specialist"], "feedback": feedback,
                               "user_feedback": [{"answer": item["answer"], "action": item["action"]}
                                                 for item in run["questions"] if item["status"] == "answered"],
                               "existing_files": workspace.contents(task["area"]) if feedback else {},
                               "dependency_files": {name: content for dependency in task["dependencies"]
                                   for name, content in workspace.contents(next(t["area"] for t in run["tasks"] if t["id"] == dependency)).items()}}
                    bundle = await gateway.call("worker", payload, task["tier"], task["id"])
                    workspace.apply(bundle, task["area"])
                    task.update(status="completed", summary=bundle.summary, finished_at=now())
                    emit("task_finished", task["specialist"], bundle.summary, task["id"])
                except asyncio.CancelledError:
                    task.update(status="cancelled", finished_at=now())
                    raise
                except Exception:
                    task.update(status="failed", finished_at=now())
                    raise

            async def build(repair_feedback=None):
                pending = {task["id"] for task in run["tasks"]}
                completed = set()
                for task in run["tasks"]:
                    task["status"] = "ready"
                while pending:
                    ready = [task for task in run["tasks"] if task["id"] in pending and set(task["dependencies"]) <= completed]
                    if not ready:
                        raise AgentError("Les dépendances empêchent la suite de l'exécution.")
                    await together([work(task, repair_feedback) for task in ready])
                    done = {task["id"] for task in ready}
                    pending -= done
                    completed |= done

            await build()
            await checkpoint("progress", True)
            for attempt in range(self.settings.max_repairs + 1):
                final_revision = False
                # Review before any generated Python is imported or executed.
                run["status"] = "reviewing"
                security = await gateway.call("security", {"request": run["prompt"], "contract": plan.contract,
                    "files": workspace.contents(), "tests": run["test_result"], "user_feedback": feedback()}, "advanced")
                run["security"] = security.model_dump()
                unsafe = not security.approved or any(f.severity in {"high", "critical"} for f in security.findings)
                run["status"] = "testing"
                emit("phase", "tester", "Exécution réelle des tests sur le projet assemblé.")
                run["test_result"] = ({"passed": False, "tests": 0, "output": "Exécution bloquée par la sécurité.", "exit_code": -1}
                                      if unsafe else await workspace.test(isolated=run["mode"] == "live"))
                if run["test_result"].get("blocked"):
                    run.update(status="needs_attention", summary=run["test_result"]["output"])
                    break
                run["status"] = "reviewing"
                emit("phase", "reviewer", "Le relecteur et l'agent sécurité examinent le projet en parallèle.")
                review_payload = {"request": run["prompt"], "contract": plan.contract,
                                  "files": workspace.contents(), "tests": run["test_result"], "user_feedback": feedback()}

                async def inspect(role):
                    choice = await gateway.call("selector", {"task": {"area": role, "title": "Sécurité du code" if role == "security" else "Relire le projet"}, "repair": attempt > 0})
                    return await gateway.call(role, review_payload, choice.tier)

                review, security = await together([inspect("reviewer"), inspect("security")])
                run["review"] = review.model_dump()
                run["security"] = security.model_dump()
                security_ok = security.approved and not any(item.severity in {"high", "critical"} for item in security.findings)
                pending_revisions = [item for item in run["questions"] if item["status"] == "answered"
                                     and item["action"] == "revise" and not item["consumed"]]
                if run["test_result"]["passed"] and review.approved and not review.issues and security_ok and not pending_revisions:
                    confirmation = await checkpoint("final", True)
                    final_revision = confirmation["action"] == "revise"
                    if confirmation["action"] == "continue":
                        confirmation["consumed"] = True
                        run.update(status="completed", summary=review.summary)
                        emit("phase", "chief", "Projet validé : tests, relecture, sécurité et retour utilisateur recueillis.")
                        break
                if attempt >= self.settings.max_repairs:
                    run.update(status="needs_attention", summary="Le projet est disponible, mais des points restent à corriger.")
                    break
                run.update(status="repairing", repairs=attempt + 1)
                emit("phase", "chief", f"Le chef demande une correction, tentative {attempt + 1}.")
                for item in run["questions"]:
                    if item["status"] == "answered":
                        item["consumed"] = True
                revised = bool(pending_revisions) or final_revision
                if revised:
                    plan = await gateway.call("chief", {"request": run["prompt"], "previous_plan": plan.model_dump(),
                        "user_feedback": feedback(), "issues": review.issues}, "advanced")
                    plan = await confirm_plan(plan)
                    await together([prepare(task) for task in run["tasks"]])
                    workspace.scaffold(plan.contract)
                await build({"issues": review.issues, "security": security.model_dump(),
                             "tests": run["test_result"], "user_feedback": feedback()})

        except asyncio.CancelledError:
            run["status"] = "cancelled"
            emit("phase", "chief", "Exécution arrêtée. Les fichiers déjà produits sont conservés.")
        except Exception as error:
            run.update(status="failed", error=str(error) if isinstance(error, (AgentError, ValueError))
                       else f"L'exécution a rencontré une erreur ({type(error).__name__}).")
            emit("error", "chief", run["error"])
        finally:
            for question in run["questions"]:
                if question["status"] == "pending":
                    question["status"] = "closed"
                self.waiters.pop(question["id"], None)
            for task in run["tasks"]:
                if task["status"] in {"pending", "ready", "running"}:
                    task["status"] = "cancelled" if run["status"] == "cancelled" else "blocked"
            run["finished_at"] = now()
            self.store.save(run)
            await gateway.close()
