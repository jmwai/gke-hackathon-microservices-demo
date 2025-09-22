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
    1) ctx.user_id (stable user id provided by caller/front-end)
    2) ctx.session.user_id (if available on ADK session)
    3) session_state/state dicts: user.id, user.user_id, or user_id
    4) ctx.session_id (only as a last resort)
    5) invocation_id-derived fallback
    """
    try:
        # Debug: log all available attributes on the context
        available_attrs = [attr for attr in dir(
            ctx) if not attr.startswith('_')]
        logger.debug(
            f"callbacks: _extract_user_id context attributes: {available_attrs}")

        # Check if user_content contains user information
        user_content = getattr(ctx, "user_content", None)
        logger.debug(
            f"callbacks: _extract_user_id ctx.user_content = {user_content}")
        if hasattr(user_content, '__dict__'):
            logger.debug(
                f"callbacks: _extract_user_id user_content.__dict__ = {user_content.__dict__}")

        # 1) Prefer a stable user id directly from context (sent from frontend)
        uid_attr = getattr(ctx, "user_id", None)
        logger.info(f"callbacks: _extract_user_id ctx.user_id = {uid_attr}")
        if isinstance(uid_attr, str) and uid_attr:
            logger.info(
                f"callbacks: _extract_user_id using frontend userId: {uid_attr}")
            return uid_attr

        # 1b) Check other potential locations for frontend-provided user ID
        request_data = getattr(ctx, "request_data", None) or getattr(
            ctx, "message", None)
        if request_data and hasattr(request_data, '__dict__'):
            request_uid = getattr(request_data, "user_id", None) or getattr(
                request_data, "userId", None)
            logger.info(
                f"callbacks: _extract_user_id request_data.user_id = {request_uid}")
            if isinstance(request_uid, str) and request_uid:
                logger.info(
                    f"callbacks: _extract_user_id using request userId: {request_uid}")
                return request_uid

        # 2) Try session.user_id if session is attached
        session = getattr(ctx, "session", None)
        if session is not None:
            try:
                # Debug: log session attributes
                session_attrs = [attr for attr in dir(
                    session) if not attr.startswith('_')]
                logger.debug(
                    f"callbacks: _extract_user_id session attributes: {session_attrs}")

                uid2 = getattr(session, "user_id", None)
                logger.debug(
                    f"callbacks: _extract_user_id session.user_id = {uid2}")
                if isinstance(uid2, str) and uid2:
                    return uid2

                # Also check session.name for resource information
                session_name = getattr(session, "name", None)
                logger.debug(
                    f"callbacks: _extract_user_id session.name = {session_name}")
            except Exception as e:
                logger.debug(
                    f"callbacks: _extract_user_id session access failed: {e}")

        # 3) Check state/session_state dictionaries
        invocation_id = getattr(ctx, "invocation_id", None)
        logger.debug(
            f"callbacks: _extract_user_id ctx.invocation_id = {invocation_id}")
        state = getattr(ctx, "session_state", None) or getattr(
            ctx, "state", {}) or {}
        logger.debug(f"callbacks: _extract_user_id state content: {state}")
        logger.debug(f"callbacks: _extract_user_id state type: {type(state)}")

        # Handle ADK State object
        if hasattr(state, '__dict__'):
            try:
                state_dict = state.__dict__
                logger.debug(
                    f"callbacks: _extract_user_id state.__dict__: {state_dict}")
                if isinstance(state_dict, dict):
                    uid = state_dict.get("user_id")
                    if isinstance(uid, str) and uid:
                        logger.debug(
                            f"callbacks: _extract_user_id found user_id in state.__dict__: {uid}")
                        return uid
            except Exception as e:
                logger.debug(
                    f"callbacks: _extract_user_id error accessing state.__dict__: {e}")

        # Handle if state has get method (dict-like)
        if hasattr(state, 'get'):
            try:
                user = state.get("user") if callable(
                    getattr(state, 'get', None)) else None
                if isinstance(user, dict):
                    uid = user.get("id") or user.get("user_id")
                    if isinstance(uid, str) and uid:
                        logger.debug(
                            f"callbacks: _extract_user_id found user_id in state.user: {uid}")
                        return uid
                uid = state.get("user_id") if callable(
                    getattr(state, 'get', None)) else None
                if isinstance(uid, str) and uid:
                    logger.debug(
                        f"callbacks: _extract_user_id found user_id in state: {uid}")
                    return uid
            except Exception as e:
                logger.debug(
                    f"callbacks: _extract_user_id error accessing state via get: {e}")

        # Traditional dict access
        if isinstance(state, dict):
            user = state.get("user")
            if isinstance(user, dict):
                uid = user.get("id") or user.get("user_id")
                if isinstance(uid, str) and uid:
                    logger.debug(
                        f"callbacks: _extract_user_id found user_id in dict state.user: {uid}")
                    return uid
            uid = state.get("user_id")
            if isinstance(uid, str) and uid:
                logger.debug(
                    f"callbacks: _extract_user_id found user_id in dict state: {uid}")
                return uid

        # 4) Do not use ctx.session_id because it may not match frontend session.
        sid = getattr(ctx, "session_id", None)
        logger.debug(
            f"callbacks: _extract_user_id ctx.session_id = {sid} (ignored)")

        # 5) Extract from session object if available (more stable than invocation_id)
        if hasattr(ctx, "session") and ctx.session:
            try:
                session_resource_name = getattr(ctx.session, "name", "")
                if session_resource_name and isinstance(session_resource_name, str):
                    # Extract session ID from resource name like "projects/.../sessions/SESSION_ID"
                    if "/sessions/" in session_resource_name:
                        session_id = session_resource_name.split(
                            "/sessions/")[-1]
                        if session_id:
                            logger.info(
                                f"callbacks: _extract_user_id using session_id: {session_id}")
                            # Return the session ID directly to match frontend format
                            return session_id
            except Exception as e:
                logger.debug(
                    f"callbacks: _extract_user_id session extraction failed: {e}")

        # 6) No fallback to invocation_id. If we cannot find a stable user id provided by the frontend,
        # return None so tools avoid writing under an incorrect cart key.

        logger.debug(
            "callbacks: _extract_user_id falling back to 'anonymous.'")
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
        inv_id = getattr(callback_context, "invocation_id", None)
        ag_name = getattr(callback_context, "agent_name", None)
        logger.debug("callbacks: before_tool start inv_id=%s agent=%s tool=%s args=%s",
                     inv_id, ag_name, tool_name, tool_args)

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

                # Enforce at most 5 recommendations for search_agent
                if agent_name == "search_agent":
                    try:
                        payload = tool_args if isinstance(
                            tool_args, dict) else {}
                        container = payload.get("shopping_recommendations") if isinstance(
                            payload.get("shopping_recommendations"), dict) else payload
                        recs = container.get("recommendations") if isinstance(
                            container, dict) else None
                        if isinstance(recs, list) and len(recs) > 5:
                            logger.debug(
                                "callbacks: clamped recommendations from %s to 5", len(recs))
                            container["recommendations"] = recs[:5]
                            return payload
                    except Exception:
                        pass
            except Exception:
                logger.debug(
                    "callbacks: blocking set_model_response due to invalid payload shape")
                return {
                    "status": "error",
                    "error_message": "Invalid final response payload. Include a 'cart' with items after cart tools.",
                }

        # For add_to_cart: ensure a stable user_id is available via state so the tool can extract it
        if tool_name == "add_to_cart":
            try:
                uid = _extract_user_id(callback_context)
                if not uid and hasattr(callback_context, "session") and getattr(callback_context.session, "history", None):
                    # Try recent add_to_cart/get_cart function responses for cart_id
                    for evt in reversed(list(callback_context.session.history)):
                        content = getattr(evt, "content", None)
                        if not content or not getattr(content, "parts", None):
                            continue
                        for part in reversed(list(content.parts)):
                            fr = getattr(part, "function_response", None)
                            if fr and getattr(fr, "name", None) in ("add_to_cart", "get_cart"):
                                resp = getattr(fr, "response", None)
                                if isinstance(resp, dict):
                                    cid = resp.get(
                                        "cart_id") or resp.get("user_id")
                                    if isinstance(cid, str) and cid:
                                        uid = cid
                                        break
                        if uid:
                            break
                if uid and hasattr(callback_context, "state") and isinstance(callback_context.state, dict):
                    callback_context.state["user_id"] = uid
                    logger.debug(
                        "callbacks: seeded state.user_id=%s for add_to_cart inv_id=%s", uid, inv_id)
            except Exception:
                pass
            # Keep pass-through for args so {'number': N} is preserved
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
            uid = _extract_user_id(callback_context)
            # Fallback: derive from recent add_to_cart function_response cart_id in history
            if not uid and hasattr(callback_context, "session") and getattr(callback_context.session, "history", None):
                try:
                    for evt in reversed(list(callback_context.session.history)):
                        content = getattr(evt, "content", None)
                        if not content or not getattr(content, "parts", None):
                            continue
                        for part in reversed(list(content.parts)):
                            fr = getattr(part, "function_response", None)
                            if fr and getattr(fr, "name", None) == "add_to_cart":
                                resp = getattr(fr, "response", None)
                                if isinstance(resp, dict):
                                    cid = resp.get("cart_id")
                                    if isinstance(cid, str) and cid:
                                        uid = cid
                                        break
                        if uid:
                            break
                except Exception:
                    pass
            if uid:
                tool_args["user_id"] = uid
                logger.debug(
                    "callbacks: before_tool injected user_id=%s for tool=%s inv_id=%s", uid, tool_name, inv_id)
            else:
                logger.warning(
                    "callbacks: before_tool could not determine user_id for tool=%s inv_id=%s; leaving args unchanged",
                    tool_name, inv_id,
                )

        # For search tools: proactively clear previous last_results to avoid
        # the model concatenating stale results with new ones in the same turn
        if tool_name in ("text_search_tool", "image_search_tool"):
            try:
                state = getattr(callback_context, "state", None)
                if isinstance(state, dict):
                    shopping_state = state.get("shopping", {})
                    shopping_state["last_results"] = {
                        "items": [], "query": "", "created_at": state.get("timestamp", "")}
                    state["shopping"] = shopping_state
                    logger.debug(
                        "callbacks: before_tool cleared prior last_results for new search")
                else:
                    # Fallback to session_state if present
                    session_state = getattr(
                        callback_context, "session_state", None)
                    if isinstance(session_state, dict):
                        shopping_state = session_state.get("shopping", {})
                        shopping_state["last_results"] = {
                            "items": [], "query": "", "created_at": ""}
                        session_state["shopping"] = shopping_state
                        setattr(callback_context,
                                "session_state", session_state)
                        logger.debug(
                            "callbacks: before_tool cleared prior last_results in session_state for new search")
            except Exception:
                pass

        # Non add_to_cart tools: pass-through
        logger.debug(
            "callbacks: before_tool end inv_id=%s tool=%s args=%s", inv_id, tool_name, tool_args)
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

        inv_id = getattr(callback_context, "invocation_id", None)
        if tool_name not in ("text_search_tool", "image_search_tool"):
            logger.debug(
                "callbacks: after_tool inv_id=%s tool=%s no-op", inv_id, tool_name)
            return None

        # Extract items from tool_response and save minimal state
        items = tool_response if isinstance(tool_response, list) else []
        compact_items = [
            {"id": p.get("id"), "name": p.get("name"),
             "brief": (p.get("description") or "")[:80]}
            for p in items[:5]
        ]

        # Save to session state if context has state access (like ToolContext)
        if hasattr(callback_context, "state") and hasattr(callback_context.state, "get"):
            try:
                # Use the standard ADK state pattern: tool_context.state["key"] = value
                shopping_state = callback_context.state.get("shopping", {})
                shopping_state["last_results"] = {
                    "items": compact_items,
                    "query": "",
                    "created_at": callback_context.state.get("timestamp", "")
                }
                callback_context.state["shopping"] = shopping_state
                logger.debug(
                    "callbacks: after_tool saved %d results to tool_context.state", len(compact_items))
            except Exception as e:
                logger.debug(
                    "callbacks: after_tool failed to save to tool_context.state: %s", e)

        # Also use legacy state management as fallback
        set_last_results(callback_context, compact_items, query="")
        # Also persist per-user fallback to survive session re-creation
        uid = _extract_user_id(callback_context)
        if isinstance(uid, str) and uid and uid != "anonymous":
            set_last_results_for_user(uid, compact_items, query="")
            logger.debug(
                "callbacks: after_tool inv_id=%s saved %s results to per-user store for uid=%s", inv_id, len(compact_items), uid)
        else:
            logger.debug(
                "callbacks: after_tool skipping per-user store (missing or anonymous uid)")
    except Exception:
        logger.debug(
            "callbacks: after_tool failed to save state (invocation_id missing?)")
    return None
