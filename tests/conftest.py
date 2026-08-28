from pathlib import Path

import pytest

from agent.config import AgentConfig


@pytest.fixture
def agent_config(tmp_path: Path) -> AgentConfig:
    """Return a fully local config that never needs a real API call."""
    return AgentConfig(
        api_key="test-key",
        base_url="http://127.0.0.1:9999/v1",
        model="fake-model",
        workspace=tmp_path / "workspace",
        max_steps=8,
        max_context_messages=20,
        max_model_retries=0,
        max_consecutive_errors=3,
    )
