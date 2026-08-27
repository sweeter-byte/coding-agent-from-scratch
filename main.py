from agent import CodingAgent


def main():
    print("Minimal Coding Agent")
    print("--------------------")

    task = input(
        "Please describe your programming task:\n> "
    ).strip()

    if not task:
        print("Task cannot be empty.")
        return

    agent = CodingAgent(
        workspace="workspace",
        max_steps=12,
    )

    try:
        result = agent.run(task)

        print()
        print("========================================")
        print("Final Answer")
        print("========================================")
        print(result)

    except KeyboardInterrupt:
        print()
        print("Agent interrupted by user.")

    except Exception as e:
        print()
        print("Agent failed:")
        print(e)


if __name__ == "__main__":
    main()