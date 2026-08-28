import json
from pathlib import Path

from storage.trace_logger import TraceLogger


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_trace_logger_writes_jsonl_record(tmp_path: Path):
    logger = TraceLogger(
        directory=tmp_path / "traces",
        run_id="test-run",
    )

    logger.log("custom_event", step=2, value=123)

    records = read_jsonl(logger.get_log_path())
    assert len(records) == 1
    assert records[0]["run_id"] == "test-run"
    assert records[0]["event"] == "custom_event"
    assert records[0]["step"] == 2
    assert records[0]["data"]["value"] == 123


def test_trace_logger_redacts_sensitive_fields(tmp_path: Path):
    logger = TraceLogger(
        directory=tmp_path / "traces",
        run_id="test-run",
    )

    logger.log(
        "secret_test",
        api_key="secret-key",
        nested={
            "openai_api_key": "another-secret",
            "safe": "visible",
        },
    )

    record = read_jsonl(logger.get_log_path())[0]
    assert record["data"]["api_key"] == "[REDACTED]"
    assert record["data"]["nested"]["openai_api_key"] == "[REDACTED]"
    assert record["data"]["nested"]["safe"] == "visible"


def test_trace_logger_truncates_large_strings(tmp_path: Path):
    logger = TraceLogger(
        directory=tmp_path / "traces",
        run_id="test-run",
        max_string_length=5,
    )

    logger.log("large", content="abcdefghij")

    record = read_jsonl(logger.get_log_path())[0]
    content = record["data"]["content"]
    assert content.startswith("abcde")
    assert "TRUNCATED" in content


def test_trace_logger_records_session_resume(tmp_path: Path):
    logger = TraceLogger(
        directory=tmp_path / "traces",
        run_id="resume-run",
    )

    logger.log_session_resume(
        restored_step=3,
        next_step=4,
        previous_status="failed",
    )

    record = read_jsonl(logger.get_log_path())[0]

    assert record["event"] == "session_resume"
    assert record["step"] == 3
    assert record["data"]["restored_step"] == 3
    assert record["data"]["next_step"] == 4
    assert record["data"]["previous_status"] == "failed"


def test_trace_logger_redacts_secrets_inside_plain_text_fields(tmp_path: Path):
    logger = TraceLogger(
        directory=tmp_path / "traces",
        run_id="text-secret-run",
    )

    logger.log(
        "tool_result",
        content="OPENAI_API_KEY=definitely-not-a-real-key",
    )

    record = read_jsonl(logger.get_log_path())[0]
    content = record["data"]["content"]

    assert "definitely-not-a-real-key" not in content
    assert "OPENAI_API_KEY=[REDACTED]" in content
