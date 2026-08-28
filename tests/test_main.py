from pathlib import Path

from storage.session_store import SessionStore

import main


def test_print_session_list_shows_status_step_and_task(
    tmp_path: Path,
    capsys,
):
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create_session(
        metadata={
            "task": "implement quicksort",
            "status": "failed",
            "workspace": str(tmp_path / "workspace"),
        }
    )
    store.save(
        session_id,
        messages=[{"role": "user", "content": "task"}],
        state={"step": 3},
    )

    main.print_session_list(store)

    output = capsys.readouterr().out

    assert session_id in output
    assert "failed" in output
    assert "3" in output
    assert "implement quicksort" in output


def test_resolve_resume_workspace_uses_stored_workspace(
    tmp_path: Path,
):
    store = SessionStore(tmp_path / "sessions")
    workspace = tmp_path / "stored-workspace"
    session_id = store.create_session(
        metadata={
            "task": "demo",
            "status": "failed",
            "workspace": str(workspace),
        }
    )

    resolved = main.resolve_resume_workspace(
        store=store,
        session_id=session_id,
        requested_workspace=None,
    )

    assert resolved == str(workspace)


def test_resolve_resume_workspace_prefers_explicit_cli_value(
    tmp_path: Path,
):
    store = SessionStore(tmp_path / "sessions")
    session_id = store.create_session(
        metadata={
            "task": "demo",
            "status": "failed",
            "workspace": str(tmp_path / "stored"),
        }
    )

    resolved = main.resolve_resume_workspace(
        store=store,
        session_id=session_id,
        requested_workspace="custom-workspace",
    )

    assert resolved == "custom-workspace"
