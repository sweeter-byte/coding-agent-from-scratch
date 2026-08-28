import argparse
import sys

from agent import AgentConfig, CodingAgent
from storage import SessionStore


# ============================================================
# Command-line arguments
# ============================================================

def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line options.

    Examples:

        python main.py

        python main.py "Implement bubble sort in Python"

        python main.py --list-sessions

        python main.py --resume 20260828_103015_a12b34cd

        python main.py \
            --resume 20260828_103015_a12b34cd \
            --max-steps 20
    """

    parser = argparse.ArgumentParser(
        description=(
            "A minimal autonomous coding agent "
            "implemented from scratch."
        )
    )

    parser.add_argument(
        "task",
        nargs="*",
        help=(
            "Programming task for a new session. "
            "If omitted, the program will ask "
            "for the task interactively."
        ),
    )

    mode_group = (
        parser.add_mutually_exclusive_group()
    )

    mode_group.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help=(
            "Resume an existing running, interrupted "
            "or failed session."
        ),
    )

    mode_group.add_argument(
        "--list-sessions",
        action="store_true",
        help=(
            "List persisted sessions and exit. "
            "This operation does not call the model."
        ),
    )

    parser.add_argument(
        "--workspace",
        default=None,
        help=(
            "Workspace directory available to the coding agent. "
            "For a new task the default is 'workspace'. "
            "For --resume, the stored workspace is used when "
            "this option is omitted."
        ),
    )

    parser.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help=(
            "Maximum cumulative number of autonomous agent steps. "
            "Default: 12"
        ),
    )

    parser.add_argument(
        "--max-context-messages",
        type=int,
        default=40,
        help=(
            "Maximum number of non-system messages kept in "
            "model context. Default: 40"
        ),
    )

    args = parser.parse_args()

    if args.resume and args.task:
        parser.error(
            "A new task cannot be supplied together with --resume."
        )

    if args.list_sessions and args.task:
        parser.error(
            "A task cannot be supplied together with --list-sessions."
        )

    return args


# ============================================================
# User task
# ============================================================

def get_user_task(
    task_parts: list[str],
) -> str:
    """
    Obtain a new programming task either from command-line arguments
    or from interactive terminal input.
    """

    if task_parts:
        task = " ".join(
            task_parts
        ).strip()

    else:
        print(
            "Minimal Coding Agent"
        )

        print(
            "--------------------"
        )

        print(
            "Please describe your programming task:"
        )

        task = input(
            "> "
        ).strip()

    if not task:
        raise ValueError(
            "Programming task cannot be empty."
        )

    return task


# ============================================================
# Session-list display
# ============================================================

def print_session_list(
    store: SessionStore,
) -> None:
    """
    Print a concise local summary of persisted sessions.

    No API configuration or model call is required.
    """

    sessions = (
        store.list_sessions()
    )

    if not sessions:
        print(
            "No saved sessions found."
        )
        return

    print(
        "Saved Sessions"
    )

    print(
        "=" * 100
    )

    print(
        f"{'Session ID':<30} "
        f"{'Status':<12} "
        f"{'Step':<6} "
        f"{'Task'}"
    )

    print(
        "-" * 100
    )

    for session in sessions:

        if "error" in session:
            print(
                f"{session.get('session_id', '<unknown>'):<30} "
                f"{'damaged':<12} "
                f"{'-':<6} "
                f"{session['error']}"
            )
            continue

        metadata = session.get(
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        state = session.get(
            "state",
            {},
        )

        if not isinstance(
            state,
            dict,
        ):
            state = {}

        session_id = str(
            session.get(
                "session_id",
                "<unknown>",
            )
        )

        status = str(
            metadata.get(
                "status",
                "unknown",
            )
        )

        step = str(
            state.get(
                "step",
                0,
            )
        )

        task = str(
            metadata.get(
                "task",
                "",
            )
        )

        if len(task) > 48:
            task = (
                task[:45]
                + "..."
            )

        print(
            f"{session_id:<30} "
            f"{status:<12} "
            f"{step:<6} "
            f"{task}"
        )


# ============================================================
# Resume workspace resolution
# ============================================================

def resolve_resume_workspace(
    store: SessionStore,
    session_id: str,
    requested_workspace: str | None,
) -> str:
    """
    Choose the workspace used to construct AgentConfig for resume.

    When --workspace is omitted, reuse the workspace stored in the
    session metadata. CodingAgent.resume() performs the final strict
    workspace-consistency check before any model call is made.
    """

    if requested_workspace is not None:
        return requested_workspace

    session = store.load(
        session_id
    )

    metadata = session.get(
        "metadata",
        {},
    )

    if isinstance(
        metadata,
        dict,
    ):
        stored_workspace = (
            metadata.get(
                "workspace"
            )
        )

        if (
            isinstance(
                stored_workspace,
                str,
            )
            and stored_workspace.strip()
        ):
            return stored_workspace

    # Compatibility fallback for very old session files that may not
    # contain workspace metadata.
    return "workspace"


# ============================================================
# Program entry
# ============================================================

def main() -> int:
    """
    CLI entry point.

    main.py deliberately contains no autonomous agent-loop logic.

    Its responsibilities are only:

    1. read CLI arguments;
    2. list local sessions, start a new task, or select a session;
    3. construct configuration;
    4. create CodingAgent;
    5. run/resume the task;
    6. display the final result.
    """

    args = parse_arguments()

    try:
        # ----------------------------------------------------
        # Local-only session listing
        # ----------------------------------------------------

        if args.list_sessions:
            print_session_list(
                SessionStore()
            )
            return 0

        # ----------------------------------------------------
        # Resume an existing session
        # ----------------------------------------------------

        if args.resume:
            store = SessionStore()

            workspace = (
                resolve_resume_workspace(
                    store=store,
                    session_id=args.resume,
                    requested_workspace=(
                        args.workspace
                    ),
                )
            )

            config = (
                AgentConfig.from_env(
                    workspace=workspace,
                    max_steps=(
                        args.max_steps
                    ),
                    max_context_messages=(
                        args.max_context_messages
                    ),
                )
            )

            agent = CodingAgent(
                config=config
            )

            # Use the same store instance that was used to inspect the
            # session. This is mostly useful for tests/custom stores and
            # keeps one consistent persistence boundary.
            agent.session_store = store

            result = agent.resume(
                args.resume
            )

        # ----------------------------------------------------
        # Start a new task
        # ----------------------------------------------------

        else:
            user_task = get_user_task(
                args.task
            )

            workspace = (
                args.workspace
                or "workspace"
            )

            config = (
                AgentConfig.from_env(
                    workspace=workspace,
                    max_steps=(
                        args.max_steps
                    ),
                    max_context_messages=(
                        args.max_context_messages
                    ),
                )
            )

            agent = CodingAgent(
                config=config
            )

            result = agent.run(
                user_task
            )

        # ----------------------------------------------------
        # Final output
        # ----------------------------------------------------

        print()

        print(
            "========================================"
        )

        print(
            "Agent Result"
        )

        print(
            "========================================"
        )

        print(
            result
        )

        return 0

    # ========================================================
    # User interruption
    # ========================================================

    except KeyboardInterrupt:

        print()

        print(
            "Agent interrupted by user.",
            file=sys.stderr,
        )

        return 130

    # ========================================================
    # Top-level fatal error
    # ========================================================

    except Exception as exc:

        print()

        print(
            "[Fatal Error]",
            file=sys.stderr,
        )

        print(
            str(exc),
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
