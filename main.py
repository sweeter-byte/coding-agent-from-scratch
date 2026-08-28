import argparse
import sys

from agent import AgentConfig, CodingAgent


# ============================================================
# Command-line arguments
# ============================================================

def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line options.

    Examples:

        python main.py

        python main.py "Implement bubble sort in Python"

        python main.py \
            "Fix the existing C++ program" \
            --workspace workspace \
            --max-steps 15
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
            "Programming task for the agent. "
            "If omitted, the program will ask "
            "for the task interactively."
        ),
    )

    parser.add_argument(
        "--workspace",
        default="workspace",
        help=(
            "Workspace directory available "
            "to the coding agent. "
            "Default: workspace"
        ),
    )

    parser.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help=(
            "Maximum number of autonomous "
            "agent steps. Default: 12"
        ),
    )

    parser.add_argument(
        "--max-context-messages",
        type=int,
        default=40,
        help=(
            "Maximum number of non-system "
            "messages kept in model context. "
            "Default: 40"
        ),
    )

    return parser.parse_args()


# ============================================================
# User task
# ============================================================

def get_user_task(
    task_parts: list[str],
) -> str:
    """
    Obtain the programming task either from command-line arguments
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
# Program entry
# ============================================================

def main() -> int:
    """
    CLI entry point.

    main.py deliberately contains no agent runtime logic.

    Its responsibilities are only:

    1. read CLI arguments;
    2. obtain the user task;
    3. construct configuration;
    4. create CodingAgent;
    5. run the task;
    6. display the final result.
    """

    args = parse_arguments()

    try:
        # ----------------------------------------------------
        # Obtain task
        # ----------------------------------------------------

        user_task = get_user_task(
            args.task
        )

        # ----------------------------------------------------
        # Build runtime configuration
        # ----------------------------------------------------

        config = (
            AgentConfig.from_env(
                workspace=(
                    args.workspace
                ),
                max_steps=(
                    args.max_steps
                ),
                max_context_messages=(
                    args.max_context_messages
                ),
            )
        )

        # ----------------------------------------------------
        # Construct agent
        # ----------------------------------------------------

        agent = CodingAgent(
            config=config
        )

        # ----------------------------------------------------
        # Run autonomous agent loop
        # ----------------------------------------------------

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