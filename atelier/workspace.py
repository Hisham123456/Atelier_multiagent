import asyncio
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import shutil
import signal
from tempfile import TemporaryDirectory
from uuid import uuid4
import zipfile

from .provider import AgentError


RUN_APP = '''"""Lancer avec : python run_app.py --port 8090"""
import argparse
from pathlib import Path
from wsgiref.simple_server import make_server
from wsgiref.util import FileWrapper
from mimetypes import guess_type
from backend.app import create_app

ROOT = Path(__file__).resolve().parent
api = create_app(ROOT / "data")

def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    if path.startswith("/api/"):
        return api(environ, start_response)
    target = (ROOT / "frontend" / (path.lstrip("/") or "index.html")).resolve()
    if not target.is_relative_to((ROOT / "frontend").resolve()) or not target.is_file():
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Page introuvable"]
    start_response("200 OK", [("Content-Type", guess_type(str(target))[0] or "application/octet-stream")])
    return FileWrapper(target.open("rb"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    with make_server("127.0.0.1", args.port, application) as server:
        print(f"Application : http://127.0.0.1:{args.port}", flush=True)
        server.serve_forever()
'''

TEST_RUNNER = r'''import json, os, sys, unittest, runpy, threading
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from wsgiref.simple_server import make_server
root = Path(__file__).resolve().parent
report = Path(sys.argv[1])
sys.path.insert(0, str(root))
os.chdir(root)
counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "smoke_passed": False}
try:
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    counts.update(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
    if result.wasSuccessful() and result.testsRun > len(result.skipped):
        namespace = runpy.run_path(str(root / "run_app.py"))
        with make_server("127.0.0.1", 0, namespace["application"]) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen("http://127.0.0.1:" + str(server.server_port) + "/", timeout=5) as response:
                    if response.status != 200 or not response.read(200000):
                        raise ValueError("La page d'accueil ne fonctionne pas.")
                counts["smoke_passed"] = True
            finally:
                server.shutdown()
                thread.join(timeout=2)
except BaseException as error:
    counts["errors"] += 1
    print("Vérification de lancement :", type(error).__name__, str(error), file=sys.stderr)
report.write_text(json.dumps(counts), encoding="utf-8")
sys.exit(0 if counts["tests"] > counts["skipped"] and not counts["failures"] and not counts["errors"] and counts["smoke_passed"] else 1)
'''



class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def scaffold(self, contract: str):
        for area in ("backend", "frontend", "tests", "docs"):
            (self.root / area).mkdir(exist_ok=True)
        (self.root / "backend" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "run_app.py").write_text(RUN_APP, encoding="utf-8")
        (self.root / "_atelier_tests.py").write_text(TEST_RUNNER, encoding="utf-8")
        (self.root / "CONTRACT.md").write_text(contract, encoding="utf-8")
        (self.root / ".gitignore").write_text("data/\n__pycache__/\n", encoding="utf-8")

    def path(self, name: str) -> Path:
        if not name or "\\" in name or ":" in name or "\x00" in name:
            raise ValueError("Chemin de fichier invalide.")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part.casefold() in {"..", ".git", ".env"} or part != part.rstrip(" .") for part in path.parts):
            raise ValueError("Le fichier doit rester dans le projet généré.")
        target = (self.root / Path(*path.parts)).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError("Chemin hors du projet.")
        if any(re.search(r"[<>\"|?*]", part) or part.rstrip(" .").split(".")[0].upper()
               in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}
               for part in path.parts):
            raise ValueError("Nom de fichier non compatible avec Windows.")
        return target

    def apply(self, bundle, area: str):
        if not 1 <= len(bundle.files) <= 30:
            raise AgentError("Un spécialiste doit fournir entre un et trente fichiers.")
        validated = []
        seen = set()
        for artifact in bundle.files:
            path = self.path(artifact.path)
            if not artifact.path.startswith(area + "/"):
                raise AgentError(f"Le spécialiste ne peut écrire que dans {area}/.")
            folded = str(path).casefold()
            if folded in seen:
                raise AgentError("Deux fichiers ont le même chemin.")
            if len(artifact.content.encode("utf-8")) > 200_000:
                raise AgentError("Fichier trop volumineux.")
            seen.add(folded)
            validated.append((path, artifact.content))
        # Validate the whole bundle before writing any file.
        for path, content in validated:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def files(self):
        return sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*")
                      if path.is_file() and "__pycache__" not in path.parts and "data" not in path.relative_to(self.root).parts)

    def contents(self, area=None):
        result = {}
        for name in self.files():
            if area and not name.startswith(area + "/"):
                continue
            result[name] = self.path(name).read_text(encoding="utf-8")
        if sum(len(value) for value in result.values()) > 500_000:
            raise AgentError("Projet trop volumineux pour cette première version.")
        return result

    def archive(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in self.files():
                if name != "_atelier_tests.py":
                    archive.write(self.path(name), name)
        return buffer.getvalue()

    async def test(self, isolated=False, timeout=30):
        missing = [name for name in ("backend/app.py", "frontend/index.html") if not self.path(name).is_file()]
        if missing:
            return {"passed": False, "tests": 0, "exit_code": -1, "output": "Fichiers obligatoires absents : " + ", ".join(missing)}
        if isolated and not shutil.which("docker"):
            return {"passed": False, "tests": 0, "exit_code": -1, "blocked": True,
                    "output": "Code conservé. Les tests OpenAI nécessitent Docker et l'image python:3.14-slim pour une exécution isolée."}
        # Always run a disposable copy. Tests cannot modify the delivered project.
        with TemporaryDirectory(prefix="atelier-test-") as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            for name, content in self.contents().items():
                if name == "_atelier_tests.py":
                    continue
                destination = project / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            (project / "_atelier_tests.py").write_text(TEST_RUNNER, encoding="utf-8")
            report_name = "result-" + uuid4().hex + ".json"
            env = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "LANG"}}
            container = "atelier-" + uuid4().hex
            command = [sys.executable, "-I", str(project / "_atelier_tests.py"), str(project / report_name)]
            if isolated:
                command = ["docker", "run", "--rm", "--pull=never", "--name", container,
                           "--network=none", "--memory=256m", "--cpus=1", "--pids-limit=64",
                           "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
                           "--tmpfs", "/tmp:rw,size=64m", "--user", "65534:65534",
                           "--mount", f"type=bind,source={project},target=/project",
                           "--workdir", "/project", "python:3.14-slim", "python", "-I",
                           "/project/_atelier_tests.py", "/project/" + report_name]
            process = await asyncio.create_subprocess_exec(*command, cwd=project, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                **({"start_new_session": True} if os.name != "nt" else {}))
            tail = bytearray()

            async def drain():
                while chunk := await process.stdout.read(8192):
                    tail.extend(chunk)
                    if len(tail) > 30000:
                        del tail[:-30000]
                await process.wait()

            async def stop():
                try:
                    if isolated:
                        killer = await asyncio.create_subprocess_exec("docker", "rm", "-f", container,
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                        await asyncio.wait_for(killer.wait(), 5)
                    if os.name == "nt":
                        killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F",
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                        await asyncio.wait_for(killer.wait(), 5)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, OSError, asyncio.TimeoutError):
                    pass
                if process.returncode is None:
                    process.kill()

            reader = asyncio.create_task(drain())
            try:
                await asyncio.wait_for(asyncio.shield(reader), timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError) as error:
                await stop()
                try:
                    await asyncio.wait_for(asyncio.shield(reader), 5)
                except asyncio.TimeoutError:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                if isinstance(error, asyncio.CancelledError):
                    raise
                return {"passed": False, "tests": 0, "exit_code": -1, "output": "Tests interrompus après le délai autorisé."}
            text = tail.decode("utf-8", errors="replace")
            try:
                counts = json.loads((project / report_name).read_text(encoding="utf-8"))
                valid = all(type(counts.get(key)) is int and counts[key] >= 0 for key in ("tests", "failures", "errors", "skipped"))
                if not valid:
                    raise ValueError("Compteurs invalides")
                passed = process.returncode == 0 and counts["tests"] > counts["skipped"] and counts["failures"] == counts["errors"] == 0 and counts.get("smoke_passed") is True
            except (OSError, ValueError, TypeError, AttributeError):
                counts, passed = {"tests": 0}, False
            return {**counts, "passed": passed, "exit_code": process.returncode,
                    "output": text or "Impossible d'exécuter les tests. Vérifie Docker et son image locale."}
