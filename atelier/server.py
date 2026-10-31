from contextlib import asynccontextmanager
from io import BytesIO
import json
from pathlib import Path
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import load_settings
from .orchestrator import Orchestrator
from .provider import AgentError
from .schemas import CreateRun, AnswerQuestion
from .storage import Store
from .workspace import Workspace
from .instance import InstanceLock


def create_app(settings=None):
    settings = settings or load_settings()
    lock = InstanceLock(settings.data_dir.parent / 'instance.lock')
    store = Store(settings.data_dir)
    engine = Orchestrator(settings, store)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            try:
                await engine.close()
            finally:
                lock.close()

    app = FastAPI(title="Atelier multi-agents", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.engine, app.state.store, app.state.token = engine, store, token
    static = Path(__file__).parent / "static"

    @app.middleware("http")
    async def protect_local_api(request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0]
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "L'atelier accepte uniquement les connexions locales."}, status_code=403)
        # Browsers on another origin cannot launch jobs using this server's API.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not secrets.compare_digest(request.headers.get("x-atelier-token", ""), token):
                return JSONResponse({"detail": "Recharge la page pour actualiser la session locale."}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != f"http://{request.headers.get('host')}":
                return JSONResponse({"detail": "Origine de la demande refusée."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response

    def read_run(run_id):
        try:
            return store.read(run_id)
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "Exécution introuvable.")

    @app.get("/")
    async def home():
        return FileResponse(static / "index.html")

    @app.get("/api/config")
    async def config():
        return {"token": token, "live_available": bool(settings.api_key),
                "models": {"economy": settings.economy, "advanced": settings.advanced},
                "concurrency": settings.concurrency, "max_calls": settings.max_calls,
                "max_repairs": settings.max_repairs}

    @app.get("/api/runs")
    async def runs():
        return [{key: run[key] for key in ("id", "prompt", "mode", "status", "created_at", "summary")} for run in store.list()]

    @app.post("/api/runs", status_code=202)
    async def start(request: CreateRun):
        try:
            return engine.start(request)
        except AgentError as error:
            raise HTTPException(409 if any(not job.done() for job in engine.jobs.values()) else 400, str(error))

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        return read_run(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        read_run(run_id)
        return await engine.cancel(run_id)

    @app.post("/api/runs/{run_id}/answer")
    async def answer(run_id: str, response: AnswerQuestion):
        read_run(run_id)
        try:
            return engine.answer(run_id, response)
        except AgentError as error:
            raise HTTPException(409, str(error))

    @app.get("/api/runs/{run_id}/files")
    async def files(run_id: str):
        run = read_run(run_id)
        if run["plan_only"]:
            return []
        return Workspace(store.folder(run_id) / "project").files()

    @app.get("/api/runs/{run_id}/file")
    async def file(run_id: str, path: str):
        read_run(run_id)
        workspace = Workspace(store.folder(run_id) / "project")
        try:
            if path not in workspace.files():
                raise ValueError("Fichier inconnu.")
            return {"path": path, "content": workspace.path(path).read_text(encoding="utf-8")}
        except (OSError, ValueError):
            raise HTTPException(404, "Fichier introuvable.")

    @app.get("/api/runs/{run_id}/download")
    async def download(run_id: str):
        run = read_run(run_id)
        if run["plan_only"] or (not run["test_result"] and run["status"] not in {"completed", "needs_attention", "failed", "cancelled", "interrupted"}):
            raise HTTPException(409, "Le projet sera disponible après la génération.")
        return Response(Workspace(store.folder(run_id) / "project").archive(), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="application-' + run_id[:8] + '.zip"'})

    @app.get("/api/runs/{run_id}/report")
    async def report(run_id: str):
        run = read_run(run_id)
        return Response(json.dumps(run, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="rapport-{run_id[:8]}.json"'})

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app
