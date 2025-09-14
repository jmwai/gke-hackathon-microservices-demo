from __future__ import annotations
from google.adk.agents import LlmAgent
from .prompts import product_discovery
from .tools import text_search_tool, image_search_tool

GEMINI_MODEL = "gemini-2.5-flash"

# Product Discovery Agent (ADK LlmAgent)
# Responds to natural language queries about products.
root_agent = LlmAgent(
    name="product_discovery_agent",
    description="Responds to natural language queries about products by using text-based search or image-based vector search.",
    instruction=product_discovery.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[text_search_tool],
)
