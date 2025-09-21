from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from .state import (
    set_last_results,
    set_last_results_for_user,
    resolve_index_to_product_id,
)


logger = logging.getLogger("agents.shopping.callbacks")


def _extract_user_id(ctx: Any) -> Optional[str]:
    """Extract user_id from context.

    Priority:
    1) ctx.user_id (if set by caller)
    2) ctx.session_id (frontend uses sessionID as user key)
    3) session_state/state dicts: user.id, user.user_id, or user_id
    """
    try:
        uid_attr = getattr(ctx, "user_id", None)
        if isinstance(uid_attr, str) and uid_attr:
            return uid_attr
        sid = getattr(ctx, "session_id", None)
        if isinstance(sid, str) and sid:
            return sid
        # Try session object attributes if available
        session = getattr(ctx, "session", None)
        if session is not None:
            try:
                sid2 = getattr(session, "id", None) or getattr(
                    session, "session_id", None)
                if isinstance(sid2, str) and sid2:
                    return sid2
                uid2 = getattr(session, "user_id", None)
                if isinstance(uid2, str) and uid2:
                    return uid2
            except Exception:
                pass
        state = getattr(ctx, "session_state", None) or getattr(
            ctx, "state", {}) or {}
        user = state.get("user") if isinstance(state, dict) else None
        if isinstance(user, dict):
            uid = user.get("id") or user.get("user_id")
            if isinstance(uid, str) and uid:
                return uid
        uid = state.get("user_id") if isinstance(state, dict) else None
        if isinstance(uid, str) and uid:
            return uid
        return None
    except Exception:
        return None


def before_model_callback(callback_context: Any = None, **kwargs) -> Optional[Any]:
    """Inject summary of last search results into the model prompt."""
    try:
        if callback_context is None:
            callback_context = kwargs.get(
                "callback_context") or kwargs.get("tool_context")
        state = callback_context.session_state or {}
        shopping = state.get("shopping", {})
        last_results = shopping.get("last_results")
        if last_results:
            items = last_results.get("items", [])
            summary = "\n".join(
                f'{i+1}. {p.get("name")} (ID: {p.get("id")})' for i, p in enumerate(items)
            )
            return f"Context: The last search returned these 5 items:\n{summary}"
    except Exception:
        pass
    return None


def before_tool_callback(callback_context: Any = None, tool: Any = None, tool_args: Optional[Dict[str, Any]] = None, **kwargs) -> Optional[Any]:
    """Resolve ordinal references for add_to_cart when product_id is missing.

    Accepts ADK's keyword style: tool=<tool or name>, tool_args=<dict>.
    """
    try:
        # Accept context via kwargs if not provided positionally
        if callback_context is None:
            callback_context = kwargs.get(
                "callback_context") or kwargs.get("tool_context")
        if callback_context is None:
            return None
        tool_name = getattr(tool, "name", tool)
        if not isinstance(tool_name, str):
            tool_name = str(tool_name)
        tool_args = tool_args or {}
        logger.debug("callbacks: before_tool start tool=%s args=%s",
                     tool_name, tool_args)

        # Guard: prevent premature finalization without proper payload
        try:
            agent_name = getattr(callback_context, "agent_name", "") or ""
        except Exception:
            agent_name = ""
        if tool_name == "set_model_response":
            try:
                # If the LLM tried to finalize with a bare string, wrap it
                if isinstance(tool_args, str) and tool_args.strip():
                    logger.debug(
                        "callbacks: wrapping bare string into schema for set_model_response")
                    return {"action": "message", "summary": tool_args.strip()}
                # On cart_agent, allow all set_model_response calls since the agent handles structure
                if agent_name == "cart_agent":
                    logger.debug(
                        f"callbacks: cart_agent set_model_response allowed (no validation) args: {tool_args}")
                    # Let cart_agent handle its own response structure
                    return None
            except Exception:
                logger.debug(
                    "callbacks: blocking set_model_response due to invalid payload shape")
                return {
                    "status": "error",
                    "error_message": "Invalid final response payload. Include a 'cart' with items after cart tools.",
                }

        # IMPORTANT: For add_to_cart, pass-through without mutating args so {'number': N} reaches the tool intact
        if tool_name == "add_to_cart":
            logger.debug(
                "callbacks: pass-through add_to_cart; not mutating args")
            return None

        # Robustly extract args if empty (pull from the last model function_call)
        if (tool_args is None or not tool_args) and hasattr(callback_context, "session"):
            try:
                # Walk history backwards to find the most recent function_call for this tool
                for evt in reversed(list(callback_context.session.history)):
                    if not getattr(evt, "content", None) or not getattr(evt.content, "parts", None):
                        continue
                    for part in reversed(list(evt.content.parts)):
                        fc = getattr(part, "function_call", None)
                        if fc and getattr(fc, "name", None) == tool_name:
                            fc_args = getattr(fc, "args", None)
                            if isinstance(fc_args, dict) and fc_args:
                                tool_args = dict(fc_args)
                                logger.debug(
                                    "callbacks: extracted args from session history for %s: %s", tool_name, tool_args)
                                break
                    if tool_args:
                        break
            except Exception:
                pass
        tool_args = tool_args or {}

        # Inject user_id for cart-related tools if missing (excluding add_to_cart)
        if tool_name in ("get_cart", "place_order") and not tool_args.get("user_id"):
            uid = _extract_user_id(callback_context) or "anonymous"
            tool_args["user_id"] = uid
            logger.debug(
                "callbacks: before_tool injected user_id=%s for tool=%s", uid, tool_name)

        # Non add_to_cart tools: pass-through
        logger.debug(
            "callbacks: before_tool end (non-add_to_cart) args=%s", tool_args)
        return tool_args if tool_args else None
    except Exception:
        return None


def after_tool_callback(callback_context: Any = None, tool: Any = None, tool_response: Any = None, **kwargs) -> Optional[Any]:
    """Persist search results to session state after a search tool is called."""
    try:
        if callback_context is None:
            callback_context = kwargs.get(
                "callback_context") or kwargs.get("tool_context")
        tool_name = getattr(tool, "name", tool)
        if not isinstance(tool_name, str):
            tool_name = str(tool_name)

        if tool_name not in ("text_search_tool", "image_search_tool"):
            logger.debug("callbacks: after_tool tool=%s no-op", tool_name)
            return None

        # Extract items from tool_response and save minimal state (avoid reading session history)
        items = tool_response if isinstance(tool_response, list) else []
        compact_items = [
            {"id": p.get("id"), "name": p.get("name"),
             "brief": (p.get("description") or "")[:80]}
            for p in items[:5]
        ]
        set_last_results(callback_context, compact_items, query="")
        # Also persist per-user fallback to survive session re-creation
        uid = _extract_user_id(callback_context) or "anonymous"
        set_last_results_for_user(uid, compact_items, query="")
        logger.debug(
            "callbacks: after_tool saved %s results to state", len(compact_items))
    except Exception:
        logger.debug("callbacks: after_tool failed to save state")
    return None
