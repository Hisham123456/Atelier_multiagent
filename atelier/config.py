from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    api_key: str = ""
    economy: str = "gpt-6-luna"
    advanced: str = "gpt-6.1-sol"
    concurrency: int = 3
    max_calls: int = 64
    call_timeout: float = 180
    max_repairs: int = 2
    demo_delay: float = 0.45
    economy_input_price: float | None = None
    economy_output_price: float | None = None
    advanced_input_price: float | None = None
    advanced_output_price: float | None = None

    @property
    def data_dir(self) -> Path:
        return self.root / ".atelier" / "runs"

    def model(self, tier: str) -> str:
        return self.advanced if tier == "advanced" else self.economy

    def cost(self, tier: str, incoming: int, outgoing: int) -> float | None:
        a = getattr(self, f"{tier}_input_price")
        b = getattr(self, f"{tier}_output_price")
        return None if a is None or b is None else (incoming * a + outgoing * b) / 1_000_000


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")

    def price(name: str) -> float | None:
        value = os.getenv(name, "").strip()
        if not value:
            return None
        result = float(value)
        if result < 0:
            raise ValueError(f"{name} doit être positif.")
        return result

    return Settings(
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        economy=os.getenv("ATELIER_MODEL_ECONOMY", "gpt-6-luna"),
        advanced=os.getenv("ATELIER_MODEL_ADVANCED", "gpt-6.1-sol"),
        concurrency=max(1, min(6, int(os.getenv("ATELIER_MAX_CONCURRENCY", "3")))),
        max_calls=max(1, int(os.getenv("ATELIER_MAX_CALLS", "64"))),
        call_timeout=max(1, float(os.getenv("ATELIER_CALL_TIMEOUT", "180"))),
        max_repairs=max(0, min(3, int(os.getenv("ATELIER_MAX_REPAIRS", "2")))),
        economy_input_price=price("ATELIER_ECONOMY_INPUT_PRICE"),
        economy_output_price=price("ATELIER_ECONOMY_OUTPUT_PRICE"),
        advanced_input_price=price("ATELIER_ADVANCED_INPUT_PRICE"),
        advanced_output_price=price("ATELIER_ADVANCED_OUTPUT_PRICE"),
    )
