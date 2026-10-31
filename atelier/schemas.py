from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Area = Literal["backend", "frontend", "tests", "docs"]
Specialist = Literal["backend", "frontend", "tester", "writer"]


class Task(StrictModel):
    id: str
    title: str
    instructions: str
    area: Area
    dependencies: list[str]

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", value):
            raise ValueError("Identifiant de tâche invalide.")
        return value


class Plan(StrictModel):
    name: str
    summary: str
    contract: str
    acceptance_criteria: list[str]
    tasks: list[Task]

    @model_validator(mode="after")
    def validate_graph(self):
        if not {'backend', 'frontend', 'tests'} <= {task.area for task in self.tasks}:
            raise ValueError("Le plan doit inclure backend, frontend et tests.")
        if not 1 <= len(self.tasks) <= 8:
            raise ValueError("Le plan doit contenir entre une et huit tâches.")
        ids = {task.id for task in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("Les identifiants de tâches doivent être uniques.")
        # One writer per directory; shared files are fixed by the coordinator.
        if len({task.area for task in self.tasks}) != len(self.tasks):
            raise ValueError("Une seule tâche par zone de fichiers est autorisée.")
        done = set()
        for task in self.tasks:
            if task.id in task.dependencies or not set(task.dependencies) <= ids:
                raise ValueError("Dépendance inconnue ou tâche dépendante d'elle-même.")
        while len(done) < len(ids):
            ready = {t.id for t in self.tasks if set(t.dependencies) <= done} - done
            if not ready:
                raise ValueError("Le plan contient un cycle de dépendances.")
            done |= ready
        return self


class Routing(StrictModel):
    specialist: Specialist
    reason: str


class ModelChoice(StrictModel):
    tier: Literal["economy", "advanced"]
    reason: str


class Artifact(StrictModel):
    path: str
    content: str


class Bundle(StrictModel):
    summary: str
    files: list[Artifact]


class Review(StrictModel):
    approved: bool
    summary: str
    issues: list[str]


class SecurityFinding(StrictModel):
    severity: Literal["low", "medium", "high", "critical"]
    path: str
    description: str
    recommendation: str


class SecurityReview(StrictModel):
    approved: bool
    summary: str
    findings: list[SecurityFinding]


class LiaisonMessage(StrictModel):
    question: str
    context: str
    suggestions: list[str]


class AnswerQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1, max_length=50)
    action: Literal["continue", "revise"]
    answer: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def meaningful_revision(self):
        if self.action == "revise" and not self.answer.strip():
            raise ValueError("Indique la précision ou l'amélioration à apporter.")
        return self


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=5, max_length=8000)
    mode: Literal["demo", "live"] = "demo"
    plan_only: bool = False

    @field_validator("prompt")
    @classmethod
    def clean_prompt(cls, value: str) -> str:
        if len(value.strip()) < 5:
            raise ValueError("Décris ton application en au moins cinq caractères.")
        return value.strip()
