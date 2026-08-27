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

        print("\n========== Final Answer ==========")
        print(result)

    except Exception as e:
        print("\nAgent failed:")
        print(e)


if __name__ == "__main__":
    main()