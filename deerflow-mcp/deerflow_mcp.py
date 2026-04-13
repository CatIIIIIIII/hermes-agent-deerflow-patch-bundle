from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("deerflow")

_CLIENT = None
_MODE_FLAGS = {
    "flash": {
        "thinking_enabled": False,
        "plan_mode": False,
        "subagent_enabled": False,
    },
    "standard": {
        "thinking_enabled": True,
        "plan_mode": False,
        "subagent_enabled": False,
    },
    "pro": {
        "thinking_enabled": True,
        "plan_mode": True,
        "subagent_enabled": False,
    },
    "ultra": {
        "thinking_enabled": True,
        "plan_mode": True,
        "subagent_enabled": True,
    },
}


def _get_config_path() -> str | None:
    return os.getenv("DEER_FLOW_CONFIG_PATH") or None



def _make_client(agent_name: str | None = None):
    from deerflow.client import DeerFlowClient

    config_path = _get_config_path()
    kwargs: dict[str, Any] = {}
    if config_path:
        kwargs["config_path"] = config_path
    if agent_name is not None:
        kwargs["agent_name"] = agent_name
        return DeerFlowClient(**kwargs)

    global _CLIENT
    if _CLIENT is None:
        _CLIENT = DeerFlowClient(**kwargs)
    return _CLIENT



def _get_checkpointer():
    from deerflow.agents.checkpointer.provider import get_checkpointer

    return get_checkpointer()



def _serialize_channel_values(channel_values: dict[str, Any]) -> dict[str, Any]:
    from deerflow.runtime import serialize_channel_values

    return serialize_channel_values(dict(channel_values or {}))



def _serialize_stream_event(event) -> dict[str, Any]:
    return {"type": event.type, "data": event.data}



def _run_chat(
    message: str,
    *,
    thread_id: str | None = None,
    model_name: str | None = None,
    thinking_enabled: bool = True,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
    agent_name: str | None = None,
) -> dict[str, Any]:
    client = _make_client(agent_name=agent_name)
    thread_id = thread_id or str(uuid.uuid4())
    answer = client.chat(
        message,
        thread_id=thread_id,
        model_name=model_name,
        thinking_enabled=thinking_enabled,
        plan_mode=plan_mode,
        subagent_enabled=subagent_enabled,
    )
    result = {"thread_id": thread_id, "answer": answer}
    if agent_name is not None:
        result["agent_name"] = agent_name
    return result



def _list_threads_data(limit: int = 10) -> dict[str, Any]:
    checkpointer = _get_checkpointer()
    thread_info_map: dict[str, dict[str, Any]] = {}
    checkpoint_limit = max(limit * 20, 50)

    for cp in checkpointer.list(config=None, limit=checkpoint_limit):
        cfg = getattr(cp, "config", {}) or {}
        configurable = cfg.get("configurable", {}) or {}
        thread_id = configurable.get("thread_id")
        if not thread_id:
            continue
        if configurable.get("checkpoint_ns"):
            continue

        checkpoint = getattr(cp, "checkpoint", {}) or {}
        ts = checkpoint.get("ts")
        checkpoint_id = configurable.get("checkpoint_id")

        if thread_id not in thread_info_map:
            channel_values = checkpoint.get("channel_values", {}) or {}
            thread_info_map[thread_id] = {
                "thread_id": thread_id,
                "created_at": ts,
                "updated_at": ts,
                "latest_checkpoint_id": checkpoint_id,
                "title": channel_values.get("title"),
            }
        else:
            current = thread_info_map[thread_id]
            if ts is not None:
                current_created = current["created_at"]
                if current_created is None or ts < current_created:
                    current["created_at"] = ts

                current_updated = current["updated_at"]
                if current_updated is None or ts > current_updated:
                    current["updated_at"] = ts
                    current["latest_checkpoint_id"] = checkpoint_id
                    channel_values = checkpoint.get("channel_values", {}) or {}
                    current["title"] = channel_values.get("title")

    threads = list(thread_info_map.values())
    threads.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {"thread_list": threads[:limit]}



def _get_thread_data(thread_id: str) -> dict[str, Any]:
    checkpointer = _get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    checkpoints = []

    for cp in checkpointer.list(config):
        checkpoint = getattr(cp, "checkpoint", {}) or {}
        channel_values = _serialize_channel_values(checkpoint.get("channel_values", {}) or {})
        cfg = getattr(cp, "config", {}) or {}
        configurable = cfg.get("configurable", {}) or {}
        parent_cfg = getattr(cp, "parent_config", None) or {}
        parent_configurable = parent_cfg.get("configurable", {}) if parent_cfg else {}

        checkpoints.append(
            {
                "checkpoint_id": configurable.get("checkpoint_id"),
                "parent_checkpoint_id": parent_configurable.get("checkpoint_id"),
                "ts": checkpoint.get("ts"),
                "metadata": getattr(cp, "metadata", {}) or {},
                "values": channel_values,
                "pending_writes": [
                    {"task_id": write[0], "channel": write[1], "value": write[2]}
                    for write in (getattr(cp, "pending_writes", []) or [])
                ],
            }
        )

    checkpoints.sort(key=lambda item: item["ts"] if item["ts"] else "")
    return {"thread_id": thread_id, "checkpoints": checkpoints}



def _get_thread_history_data(thread_id: str, limit: int = 10, before: str | None = None) -> list[dict[str, Any]]:
    checkpointer = _get_checkpointer()
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if before:
        config["configurable"]["checkpoint_id"] = before

    entries = []
    for cp in checkpointer.list(config, limit=limit):
        cfg = getattr(cp, "config", {}) or {}
        configurable = cfg.get("configurable", {}) or {}
        parent_cfg = getattr(cp, "parent_config", None) or {}
        parent_configurable = parent_cfg.get("configurable", {}) if parent_cfg else {}
        metadata = getattr(cp, "metadata", {}) or {}
        checkpoint = getattr(cp, "checkpoint", {}) or {}
        tasks_raw = getattr(cp, "tasks", []) or []

        entries.append(
            {
                "checkpoint_id": configurable.get("checkpoint_id", ""),
                "parent_checkpoint_id": parent_configurable.get("checkpoint_id"),
                "metadata": metadata,
                "values": _serialize_channel_values(checkpoint.get("channel_values", {}) or {}),
                "created_at": str(metadata.get("created_at", "")),
                "next": [task.name for task in tasks_raw if hasattr(task, "name")],
            }
        )

    return entries



def _resolve_mode_flags(mode: str) -> dict[str, bool]:
    normalized = mode.strip().lower()
    if normalized not in _MODE_FLAGS:
        raise ValueError(f"Unknown DeerFlow mode: {mode}. Use one of: {', '.join(sorted(_MODE_FLAGS))}")
    return dict(_MODE_FLAGS[normalized])



def _normalize_agent_name(name: str) -> str:
    return name.lower()



def _validate_agent_name(name: str) -> None:
    from deerflow.config.agents_config import AGENT_NAME_PATTERN

    if not AGENT_NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid agent name '{name}'. Must match {AGENT_NAME_PATTERN.pattern}"
        )



def _agent_config_to_dict(agent_cfg, *, include_soul: bool = True) -> dict[str, Any]:
    soul = None
    if include_soul:
        from deerflow.config.agents_config import load_agent_soul

        soul = load_agent_soul(agent_cfg.name) or ""

    return {
        "name": agent_cfg.name,
        "description": agent_cfg.description,
        "model": agent_cfg.model,
        "tool_groups": agent_cfg.tool_groups,
        "soul": soul,
    }



def _list_agents_data() -> dict[str, Any]:
    from deerflow.config.agents_config import list_custom_agents

    return {"agents": [_agent_config_to_dict(agent) for agent in list_custom_agents()]}



def _get_agent_data(name: str) -> dict[str, Any]:
    from deerflow.config.agents_config import load_agent_config

    _validate_agent_name(name)
    normalized_name = _normalize_agent_name(name)
    agent_cfg = load_agent_config(normalized_name)
    if agent_cfg is None:
        raise FileNotFoundError(f"Agent '{normalized_name}' not found")
    return _agent_config_to_dict(agent_cfg)



def _create_agent_data(
    name: str,
    description: str = "",
    model: str | None = None,
    tool_groups: list[str] | None = None,
    soul: str = "",
) -> dict[str, Any]:
    from deerflow.config.agents_config import load_agent_config
    from deerflow.config.paths import get_paths

    _validate_agent_name(name)
    normalized_name = _normalize_agent_name(name)
    agent_dir = get_paths().agent_dir(normalized_name)
    if agent_dir.exists():
        raise FileExistsError(f"Agent '{normalized_name}' already exists")

    try:
        agent_dir.mkdir(parents=True, exist_ok=True)
        config_data: dict[str, Any] = {"name": normalized_name}
        if description:
            config_data["description"] = description
        if model is not None:
            config_data["model"] = model
        if tool_groups is not None:
            config_data["tool_groups"] = tool_groups

        with open(agent_dir / "config.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f, sort_keys=False, allow_unicode=True)
        (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")
        return _agent_config_to_dict(load_agent_config(normalized_name))
    except Exception:
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        raise



def _update_agent_data(
    name: str,
    description: str | None = None,
    model: str | None = None,
    tool_groups: list[str] | None = None,
    soul: str | None = None,
) -> dict[str, Any]:
    from deerflow.config.agents_config import load_agent_config
    from deerflow.config.paths import get_paths

    _validate_agent_name(name)
    normalized_name = _normalize_agent_name(name)
    agent_cfg = load_agent_config(normalized_name)
    if agent_cfg is None:
        raise FileNotFoundError(f"Agent '{normalized_name}' not found")

    agent_dir = get_paths().agent_dir(normalized_name)
    if any(value is not None for value in [description, model, tool_groups]):
        updated: dict[str, Any] = {
            "name": agent_cfg.name,
            "description": description if description is not None else agent_cfg.description,
        }
        new_model = model if model is not None else agent_cfg.model
        if new_model is not None:
            updated["model"] = new_model
        new_tool_groups = tool_groups if tool_groups is not None else agent_cfg.tool_groups
        if new_tool_groups is not None:
            updated["tool_groups"] = new_tool_groups
        with open(agent_dir / "config.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(updated, f, sort_keys=False, allow_unicode=True)

    if soul is not None:
        (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")

    return _agent_config_to_dict(load_agent_config(normalized_name))



def _delete_agent_data(name: str) -> dict[str, Any]:
    from deerflow.config.paths import get_paths

    _validate_agent_name(name)
    normalized_name = _normalize_agent_name(name)
    agent_dir = get_paths().agent_dir(normalized_name)
    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent '{normalized_name}' not found")
    shutil.rmtree(agent_dir)
    return {"success": True, "name": normalized_name}


@mcp.tool()
def deerflow_chat(
    message: str,
    thread_id: str | None = None,
    model_name: str | None = None,
    thinking_enabled: bool = True,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
) -> dict[str, Any]:
    return _run_chat(
        message,
        thread_id=thread_id,
        model_name=model_name,
        thinking_enabled=thinking_enabled,
        plan_mode=plan_mode,
        subagent_enabled=subagent_enabled,
    )


@mcp.tool()
def deerflow_chat_mode(
    message: str,
    mode: str,
    thread_id: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    flags = _resolve_mode_flags(mode)
    result = _run_chat(
        message,
        thread_id=thread_id,
        model_name=model_name,
        **flags,
    )
    result["mode"] = mode.strip().lower()
    return result


@mcp.tool()
def deerflow_chat_agent(
    message: str,
    agent_name: str,
    thread_id: str | None = None,
    model_name: str | None = None,
    thinking_enabled: bool = True,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
) -> dict[str, Any]:
    return _run_chat(
        message,
        thread_id=thread_id,
        model_name=model_name,
        thinking_enabled=thinking_enabled,
        plan_mode=plan_mode,
        subagent_enabled=subagent_enabled,
        agent_name=agent_name,
    )


@mcp.tool()
def deerflow_stream(
    message: str,
    thread_id: str | None = None,
    model_name: str | None = None,
    thinking_enabled: bool = True,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
    max_events: int = 200,
) -> dict[str, Any]:
    client = _make_client()
    thread_id = thread_id or str(uuid.uuid4())
    events = []
    truncated = False

    for idx, event in enumerate(
        client.stream(
            message,
            thread_id=thread_id,
            model_name=model_name,
            thinking_enabled=thinking_enabled,
            plan_mode=plan_mode,
            subagent_enabled=subagent_enabled,
        )
    ):
        if idx >= max_events:
            truncated = True
            break
        events.append(_serialize_stream_event(event))

    return {"thread_id": thread_id, "events": events, "truncated": truncated}


@mcp.tool()
def deerflow_list_threads(limit: int = 10) -> dict[str, Any]:
    return _list_threads_data(limit=limit)


@mcp.tool()
def deerflow_get_thread(thread_id: str) -> dict[str, Any]:
    return _get_thread_data(thread_id)


@mcp.tool()
def deerflow_thread_history(thread_id: str, limit: int = 10, before: str | None = None) -> dict[str, Any]:
    return {"thread_id": thread_id, "history": _get_thread_history_data(thread_id, limit=limit, before=before)}


@mcp.tool()
def deerflow_list_models() -> dict[str, Any]:
    return _make_client().list_models()


@mcp.tool()
def deerflow_list_skills(enabled_only: bool = True) -> dict[str, Any]:
    return _make_client().list_skills(enabled_only=enabled_only)


@mcp.tool()
def deerflow_get_skill(name: str) -> dict[str, Any]:
    skill = _make_client().get_skill(name)
    if skill is None:
        return {"name": name, "found": False}
    return {"found": True, **skill}


@mcp.tool()
def deerflow_list_agents() -> dict[str, Any]:
    return _list_agents_data()


@mcp.tool()
def deerflow_get_agent(name: str) -> dict[str, Any]:
    return _get_agent_data(name)


@mcp.tool()
def deerflow_create_agent(
    name: str,
    description: str = "",
    model: str | None = None,
    tool_groups: list[str] | None = None,
    soul: str = "",
) -> dict[str, Any]:
    return _create_agent_data(
        name=name,
        description=description,
        model=model,
        tool_groups=tool_groups,
        soul=soul,
    )


@mcp.tool()
def deerflow_update_agent(
    name: str,
    description: str | None = None,
    model: str | None = None,
    tool_groups: list[str] | None = None,
    soul: str | None = None,
) -> dict[str, Any]:
    return _update_agent_data(
        name=name,
        description=description,
        model=model,
        tool_groups=tool_groups,
        soul=soul,
    )


@mcp.tool()
def deerflow_delete_agent(name: str) -> dict[str, Any]:
    return _delete_agent_data(name)


@mcp.tool()
def deerflow_get_memory() -> dict[str, Any]:
    return _make_client().get_memory()


@mcp.tool()
def deerflow_update_skill(name: str, enabled: bool) -> dict[str, Any]:
    return _make_client().update_skill(name, enabled=enabled)


@mcp.tool()
def deerflow_install_skill(skill_path: str) -> dict[str, Any]:
    return _make_client().install_skill(Path(skill_path))


@mcp.tool()
def deerflow_upload_files(thread_id: str, files: list[str]) -> dict[str, Any]:
    return _make_client().upload_files(thread_id, [Path(path) for path in files])


if __name__ == "__main__":
    mcp.run()
