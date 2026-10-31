from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Identifiant d'exécution invalide.")
        return self.root / run_id

    def save(self, run: dict) -> None:
        folder = self.folder(run["id"])
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / "state.tmp"
        temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(folder / "state.json")

    def read(self, run_id: str) -> dict:
        return json.loads((self.folder(run_id) / "state.json").read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        result = []
        for path in self.root.glob("*/state.json"):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda run: run["created_at"], reverse=True)

    def create(self, prompt: str, mode: str, plan_only: bool) -> dict:
        run = {
            "id": uuid4().hex, "prompt": prompt, "mode": mode, "plan_only": plan_only,
            "status": "queued", "created_at": now(), "finished_at": None,
            "plan": None, "tasks": [], "events": [], "calls": [], "test_result": None,
            "review": None, "security": None, "questions": [], "summary": "", "error": None, "repairs": 0,
        }
        self.save(run)
        return run

    def log_call(self, run_id: str, record: dict) -> None:
        with (self.folder(run_id) / "calls.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
