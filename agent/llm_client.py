from typing import Any

from openai import OpenAI

from .config import AgentConfig


class LLMClient:
    """
    Thin wrapper around the model provider client.

    This module is responsible only for sending requests
    to the model.

    Conversation history, response parsing, retry policy,
    and agent termination are deliberately handled elsewhere.
    """

    def __init__(
        self,
        config: AgentConfig,
    ) -> None:

        self.config = config

        self._client = OpenAI(
            api_key=(
                config.api_key
            ),
            base_url=(
                config.base_url
            ),
        )

    # ========================================================
    # Model call
    # ========================================================

    def create_completion(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> Any:
        """
        Send one chat-completion request.

        The raw SDK response is returned and converted
        by ResponseParser afterwards.
        """

        return (
            self._client
            .chat
            .completions
            .create(
                model=(
                    self.config.model
                ),
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
        )