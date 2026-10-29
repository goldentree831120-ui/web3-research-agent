"""All settings come from environment variables (.env). Nothing secret is hard-coded."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Config:
    # "<provider>:<model>", e.g. "openai:gpt-4o-mini", "anthropic:claude-haiku-4-5",
    # "google_genai:gemini-2.0-flash", "groq:openai/gpt-oss-120b". The provider's own API key
    # env var must be set (OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, GROQ_API_KEY...).
    llm_model: str = os.getenv("LLM_MODEL", "groq:openai/gpt-oss-120b")
    sepolia_rpc_url: str = os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
    staking_address: str = os.getenv("STAKING_ADDRESS", "0xd6AE22a0adE46C7eDbB92db28F6360089B94f513")
    max_tool_calls: int = int(os.getenv("MAX_TOOL_CALLS", "6"))
    max_model_calls: int = int(os.getenv("MAX_MODEL_CALLS", "8"))
    # Retries on HTTP 429 (rate limit). The provider SDK waits for its Retry-After header.
    max_retries: int = int(os.getenv("MAX_RETRIES", "4"))
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "15"))
    kb_dir: Path = ROOT / "kb"
    log_path: Path = ROOT / "logs" / "tool_calls.jsonl"


CONFIG = Config()
