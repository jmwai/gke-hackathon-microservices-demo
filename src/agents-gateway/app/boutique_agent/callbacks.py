from __future__ import annotations

import logging
from typing import Any, Dict, List

from agentkit.callbacks import BaseCallbackHandler
from agentkit.runners import AgentResponse, ToolResponse


# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ModerationCallbackHandler(BaseCallbackHandler):
    """A callback handler that performs simple content moderation."""

    def on_agent_run_start(
        self, agent_name: str, inputs: Dict[str, Any]
    ) -> None:
        """Check input text for unsafe content before the agent runs."""
        text = ""
        if "text" in inputs and isinstance(inputs["text"], str):
            text = inputs["text"]
        elif "message" in inputs and isinstance(inputs["message"], str):
            text = inputs["message"]

        if "unsafe" in text.lower():
            raise ValueError("Input contains unsafe content and was blocked.")
        logger.info(f"[{agent_name}] Input passed moderation.")


class LoggingCallbackHandler(BaseCallbackHandler):
    """A simple callback handler that logs agent and tool activity."""

    def on_agent_run_start(
        self, agent_name: str, inputs: Dict[str, Any]
    ) -> None:
        logger.info(f"[{agent_name}] Run starting with inputs: {inputs}")

    def on_tool_use(
        self, agent_name: str, tool_name: str, inputs: Dict[str, Any]
    ) -> None:
        logger.info(
            f"[{agent_name}] Using tool '{tool_name}' with inputs: {inputs}")

    def on_tool_result(
        self, agent_name: str, tool_name: str, response: ToolResponse
    ) -> None:
        logger.info(
            f"[{agent_name}] Tool '{tool_name}' result: {response.output}")

    def on_agent_run_finish(
        self, agent_name: str, response: AgentResponse
    ) -> None:
        logger.info(
            f"[{agent_name}] Run finished. Final output: {response.output}")

    def on_error(
        self, agent_name: str, error: Exception
    ) -> None:
        logger.error(f"[{agent_name}] An error occurred: {error}")
