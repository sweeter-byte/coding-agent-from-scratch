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
    Runtime configuration for CodingAgent.

    API credentials are loaded from environment variables.
    They must never be hard-coded into the repository.
    """

    api_key: str
    base_url: str
    model: str
    workspace: Path

    max_steps: int = 12
    max_context_messages: int = 40
    max_model_retries: int = 2
    max_consecutive_errors: int = 4

    @classmethod
    def from_env(
        cls,
        workspace: str = "workspace",
        max_steps: int = 12,
        max_context_messages: int = 40,
        max_model_retries: int = 2,
        max_consecutive_errors: int = 4,
    ) -> "AgentConfig":
        """
        Create AgentConfig from environment variables.

        Expected variables:

        QWEN_API_KEY or DASHSCOPE_API_KEY
        QWEN_BASE_URL
        QWEN_MODEL (optional, defaults to qwen3.7-plus)
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
                "Missing API key. Please configure "
                "QWEN_API_KEY or DASHSCOPE_API_KEY in .env."
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
        # Validate runtime configuration
        # ----------------------------------------------------

        if max_steps <= 0:
            raise ValueError(
                "max_steps must be greater than 0."
            )

        if max_context_messages < 2:
            raise ValueError(
                "max_context_messages must be at least 2."
            )

        if max_model_retries < 0:
            raise ValueError(
                "max_model_retries cannot be negative."
            )

        if max_consecutive_errors <= 0:
            raise ValueError(
                "max_consecutive_errors must be greater than 0."
            )

        # ----------------------------------------------------
        # Resolve workspace
        # ----------------------------------------------------

        workspace_path = Path(workspace)

        if not workspace_path.is_absolute():
            workspace_path = (
                PROJECT_ROOT
                / workspace_path
            )

        workspace_path = (
            workspace_path.resolve()
        )

        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            workspace=workspace_path,
            max_steps=max_steps,
            max_context_messages=(
                max_context_messages
            ),
            max_model_retries=(
                max_model_retries
            ),
            max_consecutive_errors=(
                max_consecutive_errors
            ),
        )