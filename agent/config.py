import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# Project paths
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ENV_FILE = PROJECT_ROOT / ".env"


# ============================================================
# Load environment variables
# ============================================================

load_dotenv(ENV_FILE)


# ============================================================
# Agent configuration
# ============================================================

@dataclass(frozen=True)
class AgentConfig:
    """
    Configuration used by CodingAgent.

    Configuration related to API access is loaded from .env.

    Expected environment variables:

    QWEN_API_KEY
    QWEN_BASE_URL
    QWEN_MODEL

    DASHSCOPE_API_KEY may also be used instead of QWEN_API_KEY.
    """

    api_key: str
    base_url: str
    model: str

    workspace: Path

    max_steps: int = 12

    @classmethod
    def from_env(
        cls,
        workspace: str = "workspace",
        max_steps: int = 12,
    ) -> "AgentConfig":
        """
        Create AgentConfig from environment variables.
        """

        api_key = (
            os.getenv("QWEN_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
        )

        base_url = os.getenv("QWEN_BASE_URL")

        model = os.getenv(
            "QWEN_MODEL",
            "qwen3.7-plus",
        )

        # ----------------------------------------------------
        # Validate API configuration
        # ----------------------------------------------------

        if not api_key:
            raise RuntimeError(
                "Missing API key. "
                "Please configure QWEN_API_KEY "
                "or DASHSCOPE_API_KEY in .env."
            )

        if not base_url:
            raise RuntimeError(
                "Missing QWEN_BASE_URL in .env."
            )

        if not model:
            raise RuntimeError(
                "Missing QWEN_MODEL."
            )

        # ----------------------------------------------------
        # Resolve workspace
        # ----------------------------------------------------

        workspace_path = Path(workspace)

        if not workspace_path.is_absolute():
            workspace_path = (
                PROJECT_ROOT / workspace_path
            )

        workspace_path = workspace_path.resolve()

        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            workspace=workspace_path,
            max_steps=max_steps,
        )