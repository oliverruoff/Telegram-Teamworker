"""Explicit environment configuration; secrets are never serialized."""

from dataclasses import dataclass
from pathlib import Path
import os
import shlex

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    group_id: int
    owner_id: int
    workspace: Path
    compact_tokens: int = 200_000
    reserve_tokens: int = 16_384
    context_bytes: int = 60_000
    max_file_bytes: int = 20_000_000

    @property
    def data(self) -> Path:
        return self.workspace / "data"

    def pi_args(self) -> list[str]:
        # Session lifecycle belongs to the bridge, not arbitrary CLI flags.
        extra = shlex.split(os.getenv("PI_ARGS", ""))
        allowed = {"--provider", "--model", "--thinking"}
        if (len(extra) % 2 or any(extra[i] not in allowed for i in range(0, len(extra), 2)) or
                any(extra[i].startswith("-") for i in range(1, len(extra), 2))):
            raise ValueError("PI_ARGS only accepts --provider, --model and --thinking with values")
        return ["--mode", "rpc", "--session-dir", str(self.data / "sessions"),
                "--skill", str(self.workspace / "skills"), *extra]


def load_config() -> Config:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    group_id = int(os.environ["TELEGRAM_GROUP_ID"])
    owner_id = int(os.environ["TELEGRAM_OWNER_ID"])
    if group_id >= 0 or owner_id <= 0:
        raise ValueError("TELEGRAM_GROUP_ID must be negative; TELEGRAM_OWNER_ID must be positive")
    cfg = Config(token, group_id, owner_id,
                 Path(os.getenv("TEAMWORKER_WORKSPACE", "/workspace")).resolve(),
                 int(os.getenv("COMPACT_TOKENS", "200000")),
                 int(os.getenv("CONTEXT_RESERVE_TOKENS", "16384")),
                 int(os.getenv("GROUP_CONTEXT_BYTES", "60000")))
    if cfg.compact_tokens < 4096 or cfg.reserve_tokens < 4096 or cfg.context_bytes < 1024:
        raise ValueError("Token limits must be >=4096 and GROUP_CONTEXT_BYTES >=1024")
    return cfg
