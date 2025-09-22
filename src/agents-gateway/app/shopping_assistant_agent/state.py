from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import logging

STATE_KEY = "shopping"
LAST_RESULTS_KEY = "last_results"
LAST_ADDED_ID_KEY = "last_added_id"

# In-process, per-user fallback store for last search results.
# This supplements session state in cases where a new session is created
# between search and cart turns. Keys are user_id strings.
_user_last_results_store: Dict[str, Dict[str, Any]] = {}

logger = logging.getLogger("agents.shopping.state")


def _get_state_container(ctx: Any) -> Dict[str, Any]:
    """Return a mutable state dict from either CallbackContext (session_state)
    or ToolContext (state). Ensures a dict is present and returned.
    """
    # ToolContext has `state`
    state = getattr(ctx, "state", None)
    if isinstance(state, dict):
        return state

    # CallbackContext has `session_state`
    session_state = getattr(ctx, "session_state", None)
    if not isinstance(session_state, dict):
        session_state = {}
        try:
            setattr(ctx, "session_state", session_state)
        except Exception:
            pass
    return session_state


def _ensure_root(state: Dict[str, Any]) -> Dict[str, Any]:
    if STATE_KEY not in state or not isinstance(state[STATE_KEY], dict):
        state[STATE_KEY] = {}
    return state[STATE_KEY]


def set_last_results(ctx, items: List[Dict[str, Any]], query: str) -> None:
    """Persist compact last-results (max 5) into session state under shopping.last_results.

    items: [{ id: str, name: str, brief: str }]
    """
    state = _get_state_container(ctx)
    shopping = _ensure_root(state)
    shopping[LAST_RESULTS_KEY] = {
        "items": items[:5],
        "query": query,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.debug(
        "state: set_last_results stored %s items (query='%s')",
        len(items[:5]),
        query,
    )
    # Write back for CallbackContext; for ToolContext, `state` is the live dict
    try:
        setattr(ctx, "session_state", state)
    except Exception:
        pass


def set_last_results_for_user(user_id: str, items: List[Dict[str, Any]], query: str) -> None:
    """Persist compact last-results for a specific user id in a process-local store.

    This is a fallback for when session state is not shared across turns.
    """
    if not isinstance(user_id, str) or not user_id:
        return
    _user_last_results_store[user_id] = {
        "items": items[:5],
        "query": query,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.debug(
        "state: set_last_results_for_user user_id=%s stored %s items",
        user_id,
        len(items[:5]),
    )


def get_last_results_for_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve last-results for a user from the fallback store."""
    if not isinstance(user_id, str) or not user_id:
        return None
    lr = _user_last_results_store.get(user_id)
    if not lr or not isinstance(lr, dict):
        return None
    items = lr.get("items")
    if not items or not isinstance(items, list):
        return None
    return lr


def get_last_results(ctx) -> Optional[Dict[str, Any]]:
    state = _get_state_container(ctx)
    shopping = state.get(STATE_KEY) or {}
    lr = shopping.get(LAST_RESULTS_KEY)
    if not lr or not isinstance(lr, dict):
        logger.debug("state: get_last_results found no last_results in session state")
        return None
    items = lr.get("items")
    if not items or not isinstance(items, list):
        logger.debug("state: get_last_results missing or invalid items array in session state")
        return None
    return lr


def resolve_index_to_product_id(ctx, ordinal: int) -> Optional[str]:
    lr = get_last_results(ctx)
    if not lr:
        logger.debug(
            "state: resolve_index_to_product_id no session last_results for ordinal=%s",
            ordinal,
        )
        return None
    items = lr.get("items", [])
    if 1 <= ordinal <= len(items):
        # our compact items are {id, name, brief}
        return items[ordinal - 1].get("id")
    logger.debug(
        "state: resolve_index_to_product_id ordinal out of range ordinal=%s len(items)=%s",
        ordinal,
        len(items),
    )
    return None


def resolve_index_to_product_id_for_user(user_id: str, ordinal: int) -> Optional[str]:
    """Resolve a product id from an ordinal using the user fallback store."""
    lr = get_last_results_for_user(user_id)
    if not lr:
        logger.debug(
            "state: resolve_index_to_product_id_for_user no fallback last_results for user_id=%s ordinal=%s",
            user_id,
            ordinal,
        )
        return None
    items = lr.get("items", [])
    if 1 <= ordinal <= len(items):
        return items[ordinal - 1].get("id")
    logger.debug(
        "state: resolve_index_to_product_id_for_user ordinal out of range user_id=%s ordinal=%s len(items)=%s",
        user_id,
        ordinal,
        len(items),
    )
    return None
