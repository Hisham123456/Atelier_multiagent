"""Scenario deterministe : aucun modele n'est appele en demonstration."""

BACKEND = r'''import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class TaskStore:
    def __init__(self, data_dir):
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "tasks.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self):
        with self.connect() as db:
            return [{"id": row["id"], "title": row["title"], "done": bool(row["done"])} for row in db.execute("SELECT * FROM tasks ORDER BY id")]

    def add(self, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            raise ValueError("Le titre doit contenir entre 1 et 200 caracteres.")
        with self.connect() as db:
            cursor = db.execute("INSERT INTO tasks(title) VALUES (?)", (title.strip(),))
            return {"id": cursor.lastrowid, "title": title.strip(), "done": False}

    def update(self, task_id, done):
        if not isinstance(done, bool):
            raise ValueError("done doit etre un booleen.")
        with self.connect() as db:
            if db.execute("UPDATE tasks SET done=? WHERE id=?", (int(done), task_id)).rowcount == 0:
                raise KeyError(task_id)
        return next(task for task in self.list() if task["id"] == task_id)

    def delete(self, task_id):
        with self.connect() as db:
            if db.execute("DELETE FROM tasks WHERE id=?", (task_id,)).rowcount == 0:
                raise KeyError(task_id)

def create_app(data_dir):
    store = TaskStore(data_dir)

    def application(environ, start_response):
        status = "200 OK"
        try:
            path = environ.get("PATH_INFO", "")
            method = environ.get("REQUEST_METHOD", "GET")
            data = {}
            if method in {"POST", "PATCH"}:
                length = int(environ.get("CONTENT_LENGTH") or "0")
                if length < 0 or length > 10000:
                    raise ValueError("Corps de requete trop volumineux.")
                data = json.loads(environ["wsgi.input"].read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Un objet JSON est attendu.")
            if path == "/api/tasks" and method == "GET":
                result = store.list()
            elif path == "/api/tasks" and method == "POST":
                result, status = store.add(data.get("title")), "201 Created"
            elif path.startswith("/api/tasks/") and path.rsplit("/", 1)[-1].isdigit():
                task_id = int(path.rsplit("/", 1)[-1])
                if method == "PATCH":
                    result = store.update(task_id, data.get("done"))
                elif method == "DELETE":
                    store.delete(task_id)
                    result = {"deleted": True}
                else:
                    result, status = {"error": "Methode non autorisee."}, "405 Method Not Allowed"
            else:
                result, status = {"error": "Ressource introuvable."}, "404 Not Found"
        except (ValueError, TypeError):
            result, status = {"error": "Verifie les donnees envoyees."}, "400 Bad Request"
        except KeyError:
            result, status = {"error": "Tache introuvable."}, "404 Not Found"
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))])
        return [body]
    return application
'''

FRONTEND = r'''<!doctype html>
<html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mes tâches</title>
<style>
*{box-sizing:border-box}body{font:17px/1.6 system-ui,sans-serif;background:#eef2f6;color:#182e48;margin:0;padding:8vh 20px}main{max-width:680px;margin:auto;background:white;padding:36px;border-radius:16px}h1{font-size:36px;margin:0}p{color:#486078}form{display:flex;gap:10px;margin:30px 0}input[type=text]{min-width:0;flex:1;padding:12px;border:1px solid #9cabb9;border-radius:8px;font:inherit}button{padding:10px 16px;background:#174e85;color:white;border:0;border-radius:8px;font:inherit;cursor:pointer}button:disabled{opacity:.6;cursor:wait}button:focus-visible,input:focus-visible{outline:3px solid #2474bf;outline-offset:3px}ul{padding:0;list-style:none}li{display:flex;align-items:center;gap:14px;padding:16px 0;border-bottom:1px solid #dde4ea}li span{flex:1;overflow-wrap:anywhere}li button{background:#f4e9e9;color:#822a36;font-size:14px}li input{width:20px;height:20px}.done{text-decoration:line-through;color:#596b7c}#error{color:#9d2535}#empty{padding:24px 0}@media(max-width:480px){main{padding:24px}form{flex-direction:column}}
</style><main><h1>Mes tâches</h1><p>Une chose à la fois. Les tâches sont enregistrées sur cet ordinateur.</p>
<form id="form"><label for="title" hidden>Nouvelle tâche</label><input id="title" type="text" maxlength="200" required placeholder="Que veux-tu faire ?"><button>Ajouter</button></form>
<p id="error" role="alert"></p><p id="empty">Chargement…</p><ul id="tasks"></ul></main>
<script>
const list=document.querySelector('#tasks'), error=document.querySelector('#error'), empty=document.querySelector('#empty');
async function api(path='', options={}){const response=await fetch('/api/tasks'+path,{...options,headers:{'Content-Type':'application/json'}});const data=await response.json();if(!response.ok)throw Error(data.error||'Action impossible.');return data;}
async function load(){try{const tasks=await api();list.replaceChildren();empty.textContent=tasks.length?'':'Aucune tâche. Ajoute la première.';for(const task of tasks){const li=document.createElement('li'),box=document.createElement('input'),text=document.createElement('span'),del=document.createElement('button');box.type='checkbox';box.checked=task.done;box.setAttribute('aria-label','Terminer : '+task.title);text.textContent=task.title;text.className=task.done?'done':'';del.textContent='Supprimer';del.setAttribute('aria-label','Supprimer : '+task.title);box.onchange=()=>act(()=>api('/'+task.id,{method:'PATCH',body:JSON.stringify({done:box.checked})}));del.onclick=()=>act(()=>api('/'+task.id,{method:'DELETE'}));li.append(box,text,del);list.append(li);}}catch(e){error.textContent=e.message;empty.textContent='Impossible de charger les tâches.';}}
async function act(action){error.textContent='';try{await action();await load();}catch(e){error.textContent=e.message;await load();}}
document.querySelector('#form').onsubmit=async event=>{event.preventDefault();const input=document.querySelector('#title'),button=event.currentTarget.querySelector('button');button.disabled=true;error.textContent='';try{await api('',{method:'POST',body:JSON.stringify({title:input.value})});input.value='';await load();input.focus();}catch(e){error.textContent=e.message;}finally{button.disabled=false;}};
load();
</script></html>
'''

TESTS = r'''import io
import json
from tempfile import TemporaryDirectory
import unittest
from backend.app import create_app, TaskStore

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = create_app(self.folder.name)

    def request(self, method, path="/api/tasks", data=None):
        body = json.dumps(data).encode() if data is not None else b""
        result = {}
        def start_response(status, headers):
            result["status"] = int(status.split()[0])
        content = b"".join(self.app({"PATH_INFO": path, "REQUEST_METHOD": method, "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}, start_response))
        return result["status"], json.loads(content)

    def test_empty(self):
        self.assertEqual(self.request("GET"), (200, []))

    def test_add_and_persist(self):
        status, task = self.request("POST", data={"title": "Reviser"})
        self.assertEqual(status, 201)
        self.assertFalse(task["done"])
        self.app = create_app(self.folder.name)
        self.assertEqual(self.request("GET")[1][0]["title"], "Reviser")

    def test_complete(self):
        task = self.request("POST", data={"title": "Test"})[1]
        status, changed = self.request("PATCH", "/api/tasks/" + str(task["id"]), {"done": True})
        self.assertEqual(status, 200)
        self.assertTrue(changed["done"])

    def test_delete(self):
        task = self.request("POST", data={"title": "Test"})[1]
        self.assertEqual(self.request("DELETE", "/api/tasks/" + str(task["id"]))[0], 200)
        self.assertEqual(self.request("GET")[1], [])

    def test_invalid_title(self):
        for title in ("", "  ", None, 12, "a" * 201):
            self.assertEqual(self.request("POST", data={"title": title})[0], 400)

    def test_missing_task(self):
        self.assertEqual(self.request("DELETE", "/api/tasks/999")[0], 404)

    def test_boolean_validation(self):
        task = self.request("POST", data={"title": "Test"})[1]
        self.assertEqual(self.request("PATCH", "/api/tasks/" + str(task["id"]), {"done": "false"})[0], 400)

    def test_sql_and_html_stay_data(self):
        title = "<script>alert(1)</script>'; DROP TABLE tasks;"
        self.assertEqual(self.request("POST", data={"title": title})[0], 201)
        self.assertEqual(self.request("GET")[1][0]["title"], title)

if __name__ == "__main__":
    unittest.main()
'''

CONTRACT = """# Contrat de la liste de tâches
Application WSGI : backend.app.create_app(data_dir). Données SQLite dans data_dir.
TaskStore(data_dir) expose list(), add(title), update(id, done), delete(id).
GET /api/tasks => 200 et tableau [{id: entier, title: texte, done: booléen}].
POST /api/tasks avec {title} => 201 et tâche. Titre non vide, maximum 200 caractères.
PATCH /api/tasks/{id} avec {done: booléen} => 200 et tâche.
DELETE /api/tasks/{id} => 200 et {deleted:true}.
Erreur de saisie => 400 et {error:texte} ; identifiant absent => 404.
Interface frontend/index.html en français, fetch sur ces endpoints ; texte utilisateur via textContent.
Tests unittest dans tests/test_app.py, sans dépendances et avec répertoire temporaire.
"""


def demo_response(role, payload):
    if role == "liaison":
        stage = payload["stage"]
        return {
            "question": {"plan": "Le plan te convient-il pour cette première liste de tâches ?",
                         "progress": "Les premiers fichiers sont prêts. La direction te convient-elle ?",
                         "final": "Le projet et ses résultats te conviennent-ils ?"}[stage],
            "context": "Scénario fixe de démonstration : les réponses sont conservées, mais les modèles simulés ne peuvent pas inventer une autre application.",
            "suggestions": ["Clarifier les critères de réussite", "Préciser le comportement attendu"],
        }
    if role == "chief":
        descriptions = [
            ("backend", "Créer la logique et la persistance", "Implémenter TaskStore et l'application WSGI du contrat."),
            ("frontend", "Construire l'interface de la liste", "Créer une interface française qui utilise les endpoints du contrat."),
            ("tests", "Écrire les tests de comportement", "Tester les opérations, la persistance et les entrées invalides."),
            ("docs", "Rédiger le guide de lancement", "Expliquer comment lancer l'application et ses tests."),
        ]
        return {"name": "Mes tâches", "summary": "Scénario de démonstration fixe : liste de tâches persistante. Les décisions des agents sont simulées.",
                "contract": CONTRACT, "acceptance_criteria": ["Ajouter une tâche", "Terminer une tâche", "Supprimer une tâche", "Conserver les données après redémarrage"],
                "tasks": [{"id": area, "title": title, "instructions": instructions, "area": area, "dependencies": []} for area, title, instructions in descriptions]}
    if role == "router":
        area = payload["task"]["area"]
        return {"specialist": {"tests": "tester", "docs": "writer"}.get(area, area),
                "reason": f"La tâche concerne la zone {area} ; elle revient à son spécialiste."}
    if role == "selector":
        area = payload.get("task", {}).get("area", "review")
        tier = "economy" if area in {"frontend", "docs"} and not payload.get("repair") else "advanced"
        return {"tier": tier, "reason": "Tâche courte, contrat précis : niveau économique." if tier == "economy" else "Logique, tests ou relecture : niveau avancé pour vérifier les cas limites."}
    if role == "worker":
        area = payload["task"]["area"]
        files = {
            "backend": [{"path": "backend/app.py", "content": BACKEND}],
            "frontend": [{"path": "frontend/index.html", "content": FRONTEND}],
            "tests": [{"path": "tests/test_app.py", "content": TESTS}],
            "docs": [{"path": "docs/README.md", "content": "# Mes tâches\n\nDepuis la racine du projet : `python run_app.py --port 8090`.\nOuvrir http://127.0.0.1:8090.\nLes tâches sont conservées dans data/tasks.sqlite3.\nTests : `python -m unittest discover -s tests -v`.\nPython 3.11 ou plus récent, sans dépendance supplémentaire.\n"}],
        }
        return {"summary": f"Fichiers de démonstration préparés dans {area}/.", "files": files[area]}
    if role == "reviewer":
        passed = payload["tests"]["passed"]
        return {"approved": passed, "summary": "Relecture simulée : les vérifications automatiques ont réussi." if passed else "Les tests signalent un problème.",
                "issues": [] if passed else ["Corriger les erreurs des tests."]}
    if role == "security":
        return {"approved": True, "summary": "Analyse simulée : scénario de référence utilisant des requêtes SQL paramétrées et textContent. Aucun appel à un modèle de sécurité n'a été effectué.", "findings": []}
    raise ValueError("Rôle de démonstration inconnu.")
