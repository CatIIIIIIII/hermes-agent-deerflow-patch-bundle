from __future__ import annotations

from contextlib import contextmanager
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
_REASONING_EFFORTS = {"low", "medium", "high"}


def _get_config_path() -> str | None:
    return os.getenv("DEER_FLOW_CONFIG_PATH") or None


def _normalize_skills(skills: list[str] | None) -> list[str] | None:
    if skills is None:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        name = str(skill).strip()
        if not name or name in seen:
            continue
        normalized.append(name)
        seen.add(name)
    return normalized



def _make_client(agent_name: str | None = None, skills: list[str] | None = None):
    from deerflow.client import DeerFlowClient

    config_path = _get_config_path()
    kwargs: dict[str, Any] = {}
    if config_path:
        kwargs["config_path"] = config_path
    normalized_skills = _normalize_skills(skills)
    if normalized_skills is not None:
        kwargs["available_skills"] = set(normalized_skills)
    if agent_name is not None:
        kwargs["agent_name"] = agent_name
    if agent_name is not None or normalized_skills is not None:
        return DeerFlowClient(**kwargs)

    global _CLIENT
    if _CLIENT is None:
        _CLIENT = DeerFlowClient(**kwargs)
    return _CLIENT


def _normalize_reasoning_effort(reasoning_effort: str | None) -> str | None:
    if reasoning_effort is None:
        return None

    normalized = reasoning_effort.strip().lower()
    if not normalized:
        return None
    if normalized not in _REASONING_EFFORTS:
        raise ValueError(
            f"Unknown reasoning_effort: {reasoning_effort}. Use one of: {', '.join(sorted(_REASONING_EFFORTS))}"
        )
    return normalized


def _resolve_agent_name(agent_name: str | None, use_agent: bool) -> str | None:
    normalized = (agent_name or "").strip()
    if normalized:
        return normalized
    if use_agent:
        raise ValueError("use_agent=True requires a non-empty agent_name")
    return None


def _normalize_runtime_flags(
    *,
    thinking_enabled: bool,
    plan_mode: bool,
    subagent_enabled: bool,
) -> dict[str, bool]:
    if subagent_enabled:
        return {
            "thinking_enabled": True,
            "plan_mode": True,
            "subagent_enabled": True,
        }
    return {
        "thinking_enabled": bool(thinking_enabled),
        "plan_mode": bool(plan_mode),
        "subagent_enabled": False,
    }


@contextmanager
def _inject_reasoning_effort(client, reasoning_effort: str | None):
    if reasoning_effort is None or not hasattr(client, "_get_runnable_config"):
        yield
        return

    original = client._get_runnable_config

    def _patched_get_runnable_config(thread_id: str, *args, **overrides):
        config = original(thread_id, *args, **overrides)
        configurable = config.setdefault("configurable", {})
        configurable["reasoning_effort"] = reasoning_effort
        return config

    client._get_runnable_config = _patched_get_runnable_config
    try:
        yield
    finally:
        client._get_runnable_config = original


def _chat_with_runtime_overrides(
    client,
    message: str,
    *,
    reasoning_effort: str | None = None,
    **kwargs,
) -> str:
    with _inject_reasoning_effort(client, reasoning_effort):
        return client.chat(
            message,
            reasoning_effort=reasoning_effort,
            **kwargs,
        )


def _stream_with_runtime_overrides(
    client,
    message: str,
    *,
    reasoning_effort: str | None = None,
    **kwargs,
):
    with _inject_reasoning_effort(client, reasoning_effort):
        yield from client.stream(
            message,
            reasoning_effort=reasoning_effort,
            **kwargs,
        )


def _resolve_config_file() -> Path | None:
    config_path = _get_config_path()
    if config_path:
        path = Path(config_path).expanduser()
        return path if path.exists() else None

    backend_dir = Path.cwd()
    for candidate in (backend_dir / "config.yaml", backend_dir.parent / "config.yaml"):
        if candidate.exists():
            return candidate
    return None


def _load_sandbox_mounts() -> list[tuple[Path, str]]:
    config_file = _resolve_config_file()
    if config_file is None:
        return []

    try:
        data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    raw_mounts = ((data.get("sandbox") or {}).get("mounts") or [])
    mounts: list[tuple[Path, str]] = []
    for mount in raw_mounts:
        if not isinstance(mount, dict):
            continue
        host_path = str(mount.get("host_path") or "").strip()
        container_path = str(mount.get("container_path") or "").strip()
        if not host_path or not container_path or not container_path.startswith("/"):
            continue
        mounts.append((Path(host_path).expanduser().resolve(), container_path.rstrip("/") or "/"))

    mounts.sort(key=lambda item: len(str(item[0])), reverse=True)
    return mounts


def _translate_host_path(host_path: Path, mappings: list[tuple[Path, str]]) -> str | None:
    for root_path, visible_root in mappings:
        try:
            relative = host_path.relative_to(root_path)
        except ValueError:
            continue

        relative_str = relative.as_posix()
        if relative_str in ("", "."):
            return visible_root
        return f"{visible_root}/{relative_str}"
    return None


def _resolve_visible_cwd(cwd: str | None, thread_id: str | None) -> dict[str, str | bool] | None:
    if cwd is None:
        return None

    raw_cwd = str(cwd).strip()
    if not raw_cwd:
        return None

    input_path = Path(raw_cwd).expanduser()
    if not input_path.is_absolute():
        return {
            "host_cwd": raw_cwd,
            "visible_cwd": "",
            "accessible": False,
            "reason": "Relative cwd is ambiguous here. Pass an absolute host path.",
        }

    host_path = input_path.resolve()
    if thread_id:
        from deerflow.config.paths import get_paths

        paths = get_paths()
        thread_mappings = [
            (paths.sandbox_work_dir(thread_id).resolve(), "/mnt/user-data/workspace"),
            (paths.sandbox_uploads_dir(thread_id).resolve(), "/mnt/user-data/uploads"),
            (paths.sandbox_outputs_dir(thread_id).resolve(), "/mnt/user-data/outputs"),
        ]
        visible = _translate_host_path(host_path, thread_mappings)
        if visible is not None:
            return {
                "host_cwd": str(host_path),
                "visible_cwd": visible,
                "accessible": True,
                "reason": "Mapped through DeerFlow thread workspace paths.",
            }

    visible = _translate_host_path(host_path, _load_sandbox_mounts())
    if visible is not None:
        return {
            "host_cwd": str(host_path),
            "visible_cwd": visible,
            "accessible": True,
            "reason": "Mapped through configured DeerFlow sandbox mounts.",
        }

    reason = "This host path is not in the current DeerFlow thread workspace or any configured sandbox mount."
    if not host_path.exists():
        reason = f"{reason} The host path also does not exist."
    return {
        "host_cwd": str(host_path),
        "visible_cwd": "",
        "accessible": False,
        "reason": reason,
    }


def _apply_hermes_context(
    message: str,
    *,
    cwd: str | None,
    thread_id: str | None,
    skills: list[str] | None,
) -> str:
    visible_cwd = _resolve_visible_cwd(cwd, thread_id)
    normalized_skills = _normalize_skills(skills)

    lines: list[str] = []
    if visible_cwd is not None:
        lines.append("[Hermes context]")
        lines.append(f"Host cwd: {visible_cwd['host_cwd']}")
        if visible_cwd["accessible"]:
            lines.append(f"DeerFlow-visible cwd: {visible_cwd['visible_cwd']}")
            lines.append("Use the DeerFlow-visible path above for file access. Do not use the host path directly.")
        else:
            lines.append("DeerFlow-visible cwd: unavailable")
            lines.append(str(visible_cwd["reason"]))
            lines.append("Do not assume this host path is accessible. Use uploads or add a sandbox mount first.")

    if normalized_skills is not None:
        if not lines:
            lines.append("[Hermes context]")
        lines.append("Requested skills: " + (", ".join(normalized_skills) if normalized_skills else "(none)"))

    if not lines:
        return message

    return "\n".join(lines) + "\n\n" + message



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
    cwd: str | None = None,
    skills: list[str] | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
    thinking_enabled: bool = True,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
    agent_name: str | None = None,
    use_agent: bool = False,
) -> dict[str, Any]:
    resolved_agent_name = _resolve_agent_name(agent_name, use_agent)
    runtime_flags = _normalize_runtime_flags(
        thinking_enabled=thinking_enabled,
        plan_mode=plan_mode,
        subagent_enabled=subagent_enabled,
    )
    normalized_effort = _normalize_reasoning_effort(reasoning_effort)
    client = _make_client(agent_name=resolved_agent_name, skills=skills)
    thread_id = thread_id or str(uuid.uuid4())
    message = _apply_hermes_context(message, cwd=cwd, thread_id=thread_id, skills=skills)
    answer = _chat_with_runtime_overrides(
        client,
        message,
        thread_id=thread_id,
        model_name=model_name,
        thinking_enabled=runtime_flags["thinking_enabled"],
        plan_mode=runtime_flags["plan_mode"],
        subagent_enabled=runtime_flags["subagent_enabled"],
        reasoning_effort=normalized_effort,
    )
    result = {"thread_id": thread_id, "answer": answer}
    if resolved_agent_name is not None:
        result["agent_name"] = resolved_agent_name
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
    cwd: str | None = None,
    skills: list[str] | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
    thinking_enabled: bool = True,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
    use_agent: bool = False,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Run DeerFlow with explicit effort and optional named-agent routing.

    Use ``reasoning_effort`` to control model effort (``low``/``medium``/``high``)
    when the selected DeerFlow model supports it. Set ``use_agent=true`` with
    ``agent_name`` to route the run through a named DeerFlow agent. If
    ``subagent_enabled`` is true, this wrapper forces ultra semantics by also
    enabling thinking and plan mode.
    """
    return _run_chat(
        message,
        thread_id=thread_id,
        cwd=cwd,
        skills=skills,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        thinking_enabled=thinking_enabled,
        plan_mode=plan_mode,
        subagent_enabled=subagent_enabled,
        use_agent=use_agent,
        agent_name=agent_name,
    )


@mcp.tool()
def deerflow_chat_mode(
    message: str,
    mode: str,
    thread_id: str | None = None,
    cwd: str | None = None,
    skills: list[str] | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
    use_agent: bool = False,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Run DeerFlow with a preset mode.

    Modes map to:
    - ``flash``: no thinking, no plan mode, no subagents
    - ``standard``: thinking only
    - ``pro``: thinking + plan mode
    - ``ultra``: thinking + plan mode + subagents
    """
    flags = _resolve_mode_flags(mode)
    result = _run_chat(
        message,
        thread_id=thread_id,
        cwd=cwd,
        skills=skills,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        use_agent=use_agent,
        agent_name=agent_name,
        **flags,
    )
    result["mode"] = mode.strip().lower()
    return result


@mcp.tool()
def deerflow_chat_agent(
    message: str,
    agent_name: str,
    thread_id: str | None = None,
    cwd: str | None = None,
    skills: list[str] | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
    thinking_enabled: bool = True,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
) -> dict[str, Any]:
    """Run DeerFlow through a specific named DeerFlow agent."""
    return _run_chat(
        message,
        thread_id=thread_id,
        cwd=cwd,
        skills=skills,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        thinking_enabled=thinking_enabled,
        plan_mode=plan_mode,
        subagent_enabled=subagent_enabled,
        agent_name=agent_name,
    )


@mcp.tool()
def deerflow_stream(
    message: str,
    thread_id: str | None = None,
    cwd: str | None = None,
    skills: list[str] | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
    thinking_enabled: bool = True,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
    use_agent: bool = False,
    agent_name: str | None = None,
    max_events: int = 200,
) -> dict[str, Any]:
    """Stream DeerFlow events with the same runtime controls as ``deerflow_chat``."""
    resolved_agent_name = _resolve_agent_name(agent_name, use_agent)
    runtime_flags = _normalize_runtime_flags(
        thinking_enabled=thinking_enabled,
        plan_mode=plan_mode,
        subagent_enabled=subagent_enabled,
    )
    normalized_effort = _normalize_reasoning_effort(reasoning_effort)
    client = _make_client(agent_name=resolved_agent_name, skills=skills)
    thread_id = thread_id or str(uuid.uuid4())
    message = _apply_hermes_context(message, cwd=cwd, thread_id=thread_id, skills=skills)
    events = []
    truncated = False

    for idx, event in enumerate(
        _stream_with_runtime_overrides(
            client,
            message,
            thread_id=thread_id,
            model_name=model_name,
            thinking_enabled=runtime_flags["thinking_enabled"],
            plan_mode=runtime_flags["plan_mode"],
            subagent_enabled=runtime_flags["subagent_enabled"],
            reasoning_effort=normalized_effort,
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
