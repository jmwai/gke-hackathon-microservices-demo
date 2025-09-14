from __future__ import annotations

from typing import Any, Dict
from google.adk.tools import FunctionTool

# To avoid code duplication, we import the search tool from the product discovery agent.
# In a real-world scenario with more complex dependencies, a shared `common/tools.py`
# might be a better pattern. For now, this direct import is clean and efficient.
from app.product_discovery_agent.tools import text_search_tool


def get_user_context(user_key: str) -> Dict[str, Any]:
    """
    Retrieves user preferences and context based on a user key.
    In a real implementation, this would fetch data from a session state store
    or a user profile database.
    Args:
        user_key: A unique identifier for the user.
    Returns:
        A dictionary of user preferences, e.g., {'filters': {'category': 'vintage'}}
    """
    # This is a stub. In a real system, you would look up the user_key in a
    # session or memory store (e.g., Redis, Memorystore, or ADK Memory).
    print(f"User key received: {user_key}")  # To satisfy linter
    return {"filters": {"category": "vintage"}}


user_context_tool = FunctionTool(
    get_user_context,
)
