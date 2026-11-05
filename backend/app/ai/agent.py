"""
Assistant loop: call the model, run permitted tools, pause on confirmations.

A tool call in "confirm" mode is stored as a tool message with status
"pending". The loop stops there and resumes once every pending call of the
conversation has been approved or rejected, so the model always sees a result
for each of its calls.
"""
import json
import logging
from datetime import datetime, timezone
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.ai import llm
from backend.app.ai.tools import DEFAULT_MODES, TOOLS, TOOLS_BY_NAME, ToolContext, ToolError
from backend.app.models import AIConversation, AIMessage, AISettings, User, Workspace, WorkspaceAIPermission

logger = logging.getLogger(__name__)

MAX_STEPS = 8
MAX_TOOL_RESULT_CHARS = 12000

SYSTEM_PROMPT = """You are the assistant of the Pi'op collaborative workspace "{workspace}".
You are talking to {user}. Today is {today}.
Answer in the language the user writes in. Be concise.
Use the tools to look things up instead of guessing; search the workspace before answering questions about its content and mention which tasks, documents or messages your answer is based on.
Some actions require the user's confirmation: if a tool result says the user rejected it, do not retry it unless asked.
Only the tools you are given are allowed in this workspace."""


async def get_ai_settings(session: AsyncSession) -> AISettings:
    cfg = await session.get(AISettings, 1)
    if not cfg:
        cfg = AISettings(id=1)
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return cfg


def is_configured(cfg: AISettings) -> bool:
    return bool(cfg.enabled and cfg.base_url and cfg.model)


async def get_modes(session: AsyncSession, workspace_id: int) -> dict[str, str]:
    rows = (await session.execute(
        select(WorkspaceAIPermission).where(WorkspaceAIPermission.workspace_id == workspace_id)
    )).scalars().all()
    stored = {r.action: r.mode for r in rows}
    return {t.name: stored.get(t.name, DEFAULT_MODES[t.kind]) for t in TOOLS}


def _history_to_openai(rows: list[AIMessage]) -> list[dict]:
    out = []
    for m in rows:
        if m.role == "user":
            out.append({"role": "user", "content": m.content or ""})
        elif m.role == "assistant":
            msg = {"role": "assistant", "content": m.content}
            if m.tool_calls:
                msg["tool_calls"] = json.loads(m.tool_calls)
            out.append(msg)
        elif m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""})
    return out


def _result_text(result) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + '…"truncated"'
    return text


async def execute_tool(ctx: ToolContext, name: str, args: dict) -> tuple[str, str]:
    """Run a tool and return (status, result text)."""
    try:
        result = await TOOLS_BY_NAME[name].handler(ctx, args)
        return "done", _result_text(result)
    except ToolError as exc:
        await ctx.session.rollback()
        return "error", _result_text({"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 — report any failure to the model instead of crashing the chat
        logger.exception("AI tool %s failed", name)
        await ctx.session.rollback()
        return "error", _result_text({"error": f"internal error: {type(exc).__name__}"})


async def _load_rows(session: AsyncSession, conversation_id: int) -> list[AIMessage]:
    return list((await session.execute(
        select(AIMessage).where(AIMessage.conversation_id == conversation_id).order_by(AIMessage.id)
    )).scalars().all())


async def has_pending(session: AsyncSession, conversation_id: int) -> bool:
    row = (await session.execute(
        select(AIMessage.id).where(AIMessage.conversation_id == conversation_id, AIMessage.status == "pending")
    )).first()
    return row is not None


async def run_agent(session: AsyncSession, conv: AIConversation, user: User, workspace: Workspace) -> None:
    # Plain values up front: a tool failure rolls back the session and expires ORM objects
    conv_id, workspace_id = conv.id, workspace.id
    cfg = await get_ai_settings(session)
    modes = await get_modes(session, workspace_id)
    tools = [t.schema() for t in TOOLS if modes[t.name] != "off"]
    ctx = ToolContext(session=session, user_id=user.id, workspace_id=workspace_id)
    system = SYSTEM_PROMPT.format(
        workspace=workspace.name, user=user.username, today=datetime.now(timezone.utc).date().isoformat()
    )

    for _ in range(MAX_STEPS):
        history = _history_to_openai(await _load_rows(session, conv_id))
        reply = await llm.chat_completion(cfg, [{"role": "system", "content": system}] + history, tools)
        calls = reply.get("tool_calls") or []
        session.add(AIMessage(
            conversation_id=conv_id, role="assistant", content=reply.get("content"),
            tool_calls=json.dumps(calls, ensure_ascii=False) if calls else None,
        ))
        await session.commit()
        if not calls:
            break

        waiting = False
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            row = AIMessage(conversation_id=conv_id, role="tool", tool_call_id=call.get("id"), tool_name=name)
            try:
                args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(args, dict):
                    raise ValueError
            except ValueError:
                args = {}
                row.status, row.content = "error", _result_text({"error": "arguments must be a JSON object"})
            row.tool_args = json.dumps(args, ensure_ascii=False)

            mode = modes.get(name, "off")
            if row.status:
                pass
            elif name not in TOOLS_BY_NAME or mode == "off":
                row.status, row.content = "error", _result_text({"error": f"action {name} is not permitted"})
            elif mode == "confirm":
                row.status = "pending"
                waiting = True
            else:
                row.status, row.content = await execute_tool(ctx, name, args)
            session.add(row)
            await session.commit()

        if waiting:
            break

    conv = await session.get(AIConversation, conv_id)
    conv.updated_at = datetime.now(timezone.utc)
    session.add(conv)
    await session.commit()


async def resolve_action(
    session: AsyncSession, conv: AIConversation, row: AIMessage, approve: bool,
    user: User, workspace: Workspace,
) -> None:
    """Approve or reject a pending call; continue the loop once nothing is pending."""
    conv_id, workspace_id, user_id = conv.id, workspace.id, user.id
    row_id, tool_name, args = row.id, row.tool_name, json.loads(row.tool_args or "{}")
    modes = await get_modes(session, workspace_id)

    if approve and modes.get(tool_name, "off") == "off":
        status, content = "error", _result_text({"error": "action was disabled before approval"})
    elif approve:
        ctx = ToolContext(session=session, user_id=user_id, workspace_id=workspace_id)
        status, content = await execute_tool(ctx, tool_name, args)
    else:
        status, content = "rejected", _result_text({"error": "the user rejected this action"})

    # Re-fetch: a failed tool rolls back the session and expires loaded objects
    row = await session.get(AIMessage, row_id)
    row.status, row.content = status, content
    session.add(row)
    await session.commit()

    if not await has_pending(session, conv_id):
        await run_agent(
            session,
            await session.get(AIConversation, conv_id),
            await session.get(User, user_id),
            await session.get(Workspace, workspace_id),
        )
