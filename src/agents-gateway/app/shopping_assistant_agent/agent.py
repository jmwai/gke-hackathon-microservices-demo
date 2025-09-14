from __future__ import annotations
from google.adk.agents import LlmAgent
from .prompts import recommendation
from .tools import user_context_tool, text_search_tool


GEMINI_MODEL = "gemini-2.5-flash"


# Recommendation Agent (ADK LlmAgent)
# Provides personalized product recommendations.
root_agent = LlmAgent(
    name="shopping_assistant_agent",
    description="Provides personalized product recommendations by first fetching user context and then searching for relevant products.",
    instruction=recommendation.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[user_context_tool, text_search_tool],
)
