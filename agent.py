import json
import os
import platform

from dotenv import load_dotenv
from openai import OpenAI

from tools import LocalTools


# ============================================================
# Load configuration from .env
# ============================================================

load_dotenv()


# ============================================================
# Tool definitions exposed to the LLM
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a new source code file inside the workspace. "
                "You may rewrite a file that you created earlier in this task "
                "when fixing compilation or runtime errors."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative path of the file to create, "
                            "for example 'quick_sort.cpp' or 'solution.py'."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "The complete source code that should be written "
                            "to the file."
                        ),
                    },
                },
                "required": [
                    "path",
                    "content",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a compiler, interpreter, generated executable, "
                "or test command inside the workspace. "
                "The command must be represented as an argv array "
                "rather than a shell command string."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                        "description": (
                            "Command arguments. "
                            "For example: "
                            '["g++", "main.cpp", "-o", "main"]'
                        ),
                    },
                    "purpose": {
                        "type": "string",
                        "enum": [
                            "compile",
                            "run",
                            "test",
                        ],
                        "description": (
                            "The purpose of executing this command."
                        ),
                    },
                    "stdin": {
                        "type": "string",
                        "description": (
                            "Optional standard input supplied to the program."
                        ),
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": (
                            "Maximum execution time in seconds."
                        ),
                        "default": 20,
                    },
                },
                "required": [
                    "argv",
                    "purpose",
                ],
            },
        },
    },
]


# ============================================================
# System prompt
# ============================================================

SYSTEM_PROMPT = """
You are a minimal autonomous coding agent.

Your task is to create a NEW source-code file according to the user's request,
verify that the generated program actually works, and then report the result.

You currently have exactly two local tools:

1. write_file
2. run_command

You do NOT have a read-file tool.

============================================================
LANGUAGE SELECTION
============================================================

Carefully infer the requested programming language from the user's request.

Examples:

- "C++", "cpp", "用C++实现" -> use C++
- "Python", "python", "py" -> use Python

If the user explicitly specifies a language, you MUST use that language.

If the user does not specify a language, prefer Python unless the task
clearly implies another language.

============================================================
WORKFLOW
============================================================

You MUST follow this workflow:

1. Understand the programming task.
2. Determine the programming language.
3. Determine an appropriate source file name.
4. Generate complete source code.
5. Call write_file to create the file.
6. Validate the program using run_command.
7. Inspect stdout, stderr, and return code.
8. If validation fails, fix the file using write_file.
9. Validate the new version again.
10. Only finish after successful validation.

Do NOT merely generate code and claim that it works.

You MUST actually execute validation tools.

============================================================
C++ VALIDATION
============================================================

For C++ programs:

1. Compile the source code using g++ or clang++.
2. If compilation fails:
   - inspect stderr
   - fix the source code
   - compile again

3. If compilation succeeds:
   - run the generated executable
   - provide representative stdin when appropriate
   - inspect stdout and stderr

Compilation success alone is NOT enough.

The executable must also be run successfully.

============================================================
PYTHON VALIDATION
============================================================

For Python programs:

Run the generated Python program using Python.

Provide representative stdin when the program expects input.

Inspect:

- stdout
- stderr
- return code

If execution fails, fix the source code and execute it again.

============================================================
COMMAND RULES
============================================================

The run_command tool receives argv as an ARRAY.

Correct example:

["g++", "main.cpp", "-o", "main"]

Incorrect example:

["g++ main.cpp -o main && ./main"]

Do NOT use shell syntax such as:

&&
||
|
>
<

Compilation and execution must be separate tool calls.

============================================================
FILE RULES
============================================================

Only create files required for the user's task.

Do not attempt to access files outside the workspace.

Do not attempt to modify pre-existing user files.

You may rewrite a file that YOU created earlier in this same task
when fixing errors.

============================================================
FINAL RESPONSE
============================================================

Only after successful validation, briefly tell the user:

- which file was created
- which language was used
- how it was validated
- whether validation succeeded

Do not include unnecessary long explanations.
"""


# ============================================================
# Coding Agent
# ============================================================

class CodingAgent:

    def __init__(
        self,
        workspace: str = "workspace",
        max_steps: int = 12,
    ):
        """
        Initialize the coding agent.

        Configuration is read from environment variables:

        QWEN_API_KEY
        QWEN_BASE_URL
        QWEN_MODEL

        DASHSCOPE_API_KEY can also be used instead of QWEN_API_KEY.
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
        # Validate configuration
        # ----------------------------------------------------

        if not api_key:
            raise RuntimeError(
                "Missing API key.\n"
                "Please configure QWEN_API_KEY "
                "or DASHSCOPE_API_KEY in your .env file."
            )

        if not base_url:
            raise RuntimeError(
                "Missing QWEN_BASE_URL.\n"
                "Please configure QWEN_BASE_URL "
                "in your .env file."
            )

        if not model:
            raise RuntimeError(
                "Missing QWEN_MODEL."
            )

        # ----------------------------------------------------
        # OpenAI-compatible Qwen client
        # ----------------------------------------------------

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        self.model = model

        # ----------------------------------------------------
        # Local tool executor
        # ----------------------------------------------------

        self.local_tools = LocalTools(
            workspace=workspace
        )

        self.max_steps = max_steps

    # ========================================================
    # Convert SDK message into dictionary
    # ========================================================

    def _assistant_message_to_dict(
        self,
        message,
    ) -> dict:
        """
        Convert the response object returned by the OpenAI SDK
        into a standard message dictionary.

        We do this because the full conversation history is
        maintained by our own agent.
        """

        result = {
            "role": "assistant",
            "content": message.content or "",
        }

        if message.tool_calls:
            result["tool_calls"] = []

            for tool_call in message.tool_calls:
                result["tool_calls"].append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": (
                                tool_call.function.name
                            ),
                            "arguments": (
                                tool_call.function.arguments
                            ),
                        },
                    }
                )

        return result

    # ========================================================
    # Execute a local tool
    # ========================================================

    def _execute_tool(
        self,
        name: str,
        arguments: dict,
    ) -> str:
        """
        Dispatch a tool call generated by the LLM
        to our own local implementation.
        """

        if name == "write_file":
            return self.local_tools.write_file(
                path=arguments["path"],
                content=arguments["content"],
            )

        if name == "run_command":
            return self.local_tools.run_command(
                argv=arguments["argv"],
                purpose=arguments["purpose"],
                stdin=arguments.get(
                    "stdin",
                    "",
                ),
                timeout_seconds=arguments.get(
                    "timeout_seconds",
                    20,
                ),
            )

        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"Unknown tool requested: {name}"
                ),
            },
            ensure_ascii=False,
        )

    # ========================================================
    # Main Agent Loop
    # ========================================================

    def run(
        self,
        user_task: str,
    ) -> str:
        """
        Run the coding-agent loop.

        Core process:

        User task
            ↓
        LLM
            ↓
        tool call
            ↓
        local execution
            ↓
        tool result
            ↓
        LLM
            ↓
        continue or finish
        """

        current_os = platform.system()

        system_prompt = (
            SYSTEM_PROMPT
            + "\n\n"
            + f"Current operating system: {current_os}\n"
        )

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_task,
            },
        ]

        # ----------------------------------------------------
        # Agent runtime state
        # ----------------------------------------------------

        # Every successful write increments this version.
        #
        # Example:
        #
        # first write -> version 1
        # fix code    -> version 2
        #
        write_version = 0

        # Records which source-code version has successfully
        # passed runtime validation.
        validated_version = -1

        # ----------------------------------------------------
        # Agent Loop
        # ----------------------------------------------------

        for step in range(
            1,
            self.max_steps + 1,
        ):

            print()
            print(
                "========================================"
            )
            print(
                f"Agent Step {step}/{self.max_steps}"
            )
            print(
                "========================================"
            )

            # ------------------------------------------------
            # Ask Qwen what to do next
            # ------------------------------------------------

            response = (
                self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )
            )

            assistant_message = (
                response.choices[0].message
            )

            # Save model response into our own context.
            messages.append(
                self._assistant_message_to_dict(
                    assistant_message
                )
            )

            tool_calls = (
                assistant_message.tool_calls
            )

            # ------------------------------------------------
            # Case 1:
            # model did NOT request a tool
            #
            # The model wants to finish.
            # ------------------------------------------------

            if not tool_calls:

                # --------------------------------------------
                # Runtime guard:
                # a file must have been created.
                # --------------------------------------------

                if write_version == 0:

                    print(
                        "[Runtime Guard]"
                    )
                    print(
                        "The model attempted to finish "
                        "without creating a file."
                    )

                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[Agent runtime feedback]\n"
                                "You have not created the "
                                "requested source file yet.\n"
                                "Continue the task by using "
                                "the available tools."
                            ),
                        }
                    )

                    continue

                # --------------------------------------------
                # Runtime guard:
                # latest source version must be validated.
                # --------------------------------------------

                if (
                    validated_version
                    != write_version
                ):

                    print(
                        "[Runtime Guard]"
                    )
                    print(
                        "The latest source-code version "
                        "has not passed runtime validation."
                    )

                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[Agent runtime feedback]\n"
                                "The latest source-code "
                                "version has not yet passed "
                                "successful runtime "
                                "validation.\n"
                                "Continue using run_command "
                                "to validate it."
                            ),
                        }
                    )

                    continue

                # --------------------------------------------
                # All requirements satisfied.
                # Agent can finish.
                # --------------------------------------------

                return (
                    assistant_message.content
                    or "Task completed successfully."
                )

            # ------------------------------------------------
            # Case 2:
            # model requested one or more tools
            # ------------------------------------------------

            for tool_call in tool_calls:

                tool_name = (
                    tool_call.function.name
                )

                print()
                print(
                    f"[Tool Call] {tool_name}"
                )

                # --------------------------------------------
                # Parse tool arguments
                # --------------------------------------------

                try:
                    arguments = json.loads(
                        tool_call.function.arguments
                    )

                except json.JSONDecodeError as e:

                    tool_result = json.dumps(
                        {
                            "ok": False,
                            "error": (
                                "Invalid JSON arguments "
                                "generated by the model: "
                                + str(e)
                            ),
                        },
                        ensure_ascii=False,
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": (
                                tool_call.id
                            ),
                            "content": tool_result,
                        }
                    )

                    continue

                print(
                    json.dumps(
                        arguments,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

                # --------------------------------------------
                # Execute tool locally
                # --------------------------------------------

                try:
                    tool_result = (
                        self._execute_tool(
                            tool_name,
                            arguments,
                        )
                    )

                except Exception as e:

                    tool_result = json.dumps(
                        {
                            "ok": False,
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

                print()
                print(
                    "[Tool Result]"
                )
                print(
                    tool_result
                )

                # --------------------------------------------
                # Decode result for runtime state tracking
                # --------------------------------------------

                try:
                    result_data = json.loads(
                        tool_result
                    )

                except json.JSONDecodeError:

                    result_data = {
                        "ok": False,
                    }

                # --------------------------------------------
                # File successfully written
                # --------------------------------------------

                if (
                    tool_name == "write_file"
                    and result_data.get("ok")
                ):

                    write_version += 1

                    # A newly written version invalidates
                    # previous validation.
                    #
                    # Example:
                    #
                    # version 1 passed
                    # ↓
                    # model rewrites code
                    # ↓
                    # version 2 must be tested again
                    #
                    # validated_version remains 1.
                    #
                    # Therefore:
                    #
                    # validated_version != write_version
                    #
                    # and the agent cannot finish yet.

                # --------------------------------------------
                # Successful runtime validation
                # --------------------------------------------

                if (
                    tool_name == "run_command"
                    and result_data.get("ok")
                ):

                    purpose = arguments.get(
                        "purpose"
                    )

                    argv = arguments.get(
                        "argv",
                        [],
                    )

                    # Compile success is NOT final validation.
                    #
                    # We only consider a successful run/test
                    # as final runtime validation.
                    if (
                        purpose in {
                            "run",
                            "test",
                        }
                        and argv
                    ):

                        executable = argv[0]

                        # Do not accidentally count compiler
                        # execution as runtime validation.
                        if (
                            executable
                            not in LocalTools.COMPILERS
                        ):
                            validated_version = (
                                write_version
                            )

                # --------------------------------------------
                # Put the tool result back into conversation
                # context.
                #
                # This is what allows the LLM to observe:
                #
                # stdout
                # stderr
                # return code
                # errors
                #
                # and decide what to do next.
                # --------------------------------------------

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": (
                            tool_call.id
                        ),
                        "content": tool_result,
                    }
                )

        # ----------------------------------------------------
        # Loop termination condition
        # ----------------------------------------------------

        raise RuntimeError(
            "Agent reached the maximum number "
            f"of steps ({self.max_steps}) "
            "without completing the task."
        )