from pathlib import Path

import pytest

from agent.config import AgentConfig


def test_config_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("QWEN_API_KEY", "abc")
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("QWEN_MODEL", "test-model")

    config = AgentConfig.from_env(
        workspace=str(tmp_path / "workspace"),
        max_steps=5,
        max_context_messages=10,
        max_model_retries=1,
        max_consecutive_errors=2,
    )

    assert config.api_key == "abc"
    assert config.base_url == "https://example.com/v1"
    assert config.model == "test-model"
    assert config.workspace == (tmp_path / "workspace").resolve()
    assert config.max_steps == 5
    assert config.max_context_messages == 10
    assert config.max_model_retries == 1
    assert config.max_consecutive_errors == 2


def test_config_accepts_dashscope_api_key(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.com/v1")

    config = AgentConfig.from_env(
        workspace=str(tmp_path / "workspace")
    )

    assert config.api_key == "dash-key"


def test_config_rejects_missing_api_key(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.com/v1")

    with pytest.raises(RuntimeError, match="Missing API key"):
        AgentConfig.from_env(
            workspace=str(tmp_path / "workspace")
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_steps": 0}, "max_steps"),
        ({"max_context_messages": 1}, "max_context_messages"),
        ({"max_model_retries": -1}, "max_model_retries"),
        ({"max_consecutive_errors": 0}, "max_consecutive_errors"),
    ],
)
def test_config_rejects_invalid_runtime_values(
    monkeypatch,
    tmp_path: Path,
    kwargs,
    message,
):
    monkeypatch.setenv("QWEN_API_KEY", "abc")
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.com/v1")

    with pytest.raises(ValueError, match=message):
        AgentConfig.from_env(
            workspace=str(tmp_path / "workspace"),
            **kwargs,
        )
