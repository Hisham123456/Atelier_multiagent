import asyncio
import json
from time import perf_counter
from uuid import uuid4

from openai import AsyncOpenAI, AuthenticationError, RateLimitError, APIConnectionError

from .agents import INSTRUCTIONS, SCHEMAS
from .demo import demo_response
from .storage import now


class AgentError(RuntimeError):
    pass


class ModelGateway:
    """One entry point for calls, validation, limits and durable audit records."""

    def __init__(self, settings, store, run: dict, emit, client=None):
        self.settings, self.store, self.run, self.emit = settings, store, run, emit
        self.client = client
        self.slots = asyncio.Semaphore(settings.concurrency)
        self.reservations = 0

    async def close(self):
        if self.client is not None:
            await self.client.close()

    async def call(self, role: str, payload: dict, tier="economy", task_id=None):
        async with self.slots:
            if self.reservations >= self.settings.max_calls:
                raise AgentError("Limite d'appels atteinte. Consulte les résultats avant de relancer.")
            self.reservations += 1
            model = self.settings.model(tier)
            record = {
                "id": uuid4().hex, "role": role, "task_id": task_id, "model": model,
                "tier": tier, "mode": self.run["mode"], "started_at": now(),
                "status": "running", "duration_ms": None, "input_tokens": None,
                "output_tokens": None, "cost_usd": None,
            }
            self.run["calls"].append(record)
            display = {"chief": "Le chef", "router": "Le routeur", "selector": "Le sélecteur de modèles",
                       "worker": "Le spécialiste", "reviewer": "Le relecteur", "security": "L'agent sécurité",
                       "liaison": "L'agent de liaison"}[role]
            self.emit("call_started", role, f"{display} commence son travail.", task_id)
            started = perf_counter()
            raw = None
            try:
                if self.run["mode"] == "demo":
                    await asyncio.sleep(self.settings.demo_delay * (1 if role in {"router", "selector"} else 2.67))
                    raw = demo_response(role, payload)
                else:
                    if not self.settings.api_key:
                        raise AgentError("Ajoute OPENAI_API_KEY dans .env, puis redémarre l'atelier.")
                    if self.client is None:
                        self.client = AsyncOpenAI(api_key=self.settings.api_key, max_retries=0,
                                                  timeout=self.settings.call_timeout)
                    response = await asyncio.wait_for(
                        self.client.responses.create(
                            model=model,
                            instructions=INSTRUCTIONS[role],
                            input=json.dumps(payload, ensure_ascii=False),
                            text={"format": {"type": "json_schema", "name": role,
                                             "strict": True, "schema": SCHEMAS[role].model_json_schema()}},
                            max_output_tokens=14000 if role == "worker" else 6000,
                            store=False,
                        ), timeout=self.settings.call_timeout,
                    )
                    if response.usage:
                        record["input_tokens"] = response.usage.input_tokens
                        record["output_tokens"] = response.usage.output_tokens
                        record["cost_usd"] = self.settings.cost(tier, response.usage.input_tokens,
                                                                 response.usage.output_tokens)
                    if response.status != "completed":
                        raise AgentError("Réponse incomplète du modèle. Le résultat n'a pas été appliqué.")
                    if not response.output_text:
                        raise AgentError("Le modèle n'a pas fourni de résultat exploitable (refus possible).")
                    raw = json.loads(response.output_text)
                result = SCHEMAS[role].model_validate(raw)
                record["status"] = "completed"
                return result
            except asyncio.CancelledError:
                record["status"] = "cancelled"
                raise
            except Exception as error:
                record["status"] = "failed"
                if isinstance(error, AuthenticationError):
                    message = "Clé OpenAI refusée. Vérifie ta clé API dans .env."
                elif isinstance(error, RateLimitError):
                    message = "Limite ou quota OpenAI atteint. Vérifie ton compte avant de relancer."
                elif isinstance(error, (APIConnectionError, ConnectionError)):
                    message = "Connexion à OpenAI impossible. Vérifie ta connexion."
                elif isinstance(error, (asyncio.TimeoutError, TimeoutError)):
                    message = "Délai de réponse dépassé. Tu peux relancer avec une tâche plus courte."
                elif isinstance(error, AgentError):
                    message = str(error)
                else:
                    # Do not expose HTTP headers, API keys or arbitrary provider exception bodies.
                    message = f"Réponse invalide pour {role} ({type(error).__name__})."
                record["error"] = message
                raise AgentError(message) from error
            finally:
                record["duration_ms"] = round((perf_counter() - started) * 1000)
                record["finished_at"] = now()
                self.store.log_call(self.run["id"], {
                    **record, "instructions": INSTRUCTIONS[role], "input": payload, "response": raw,
                })
                outcome = {"completed": "travail terminé", "failed": "échec de l'appel", "cancelled": "appel arrêté"}.get(record["status"], record["status"])
                self.emit("call_finished", role, f"{display} : {outcome}.", task_id)
