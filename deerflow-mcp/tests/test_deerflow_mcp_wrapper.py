from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

WRAPPER_PATH = Path(__file__).resolve().parents[1] / "deerflow_mcp.py"


def load_wrapper_module():
    spec = importlib.util.spec_from_file_location("deerflow_mcp", WRAPPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeEvent:
    def __init__(self, event_type, data):
        self.type = event_type
        self.data = data


class FakeClient:
    def __init__(self):
        self.calls = []
        self.skill_map = {
            "demo": {
                "name": "demo",
                "description": "demo skill",
                "enabled": True,
                "category": "public",
                "license": "MIT",
            }
        }
        self.stream_events = []

    def chat(self, message, **kwargs):
        self.calls.append(("chat", message, kwargs))
        return "ok"

    def list_skills(self, enabled_only=False):
        self.calls.append(("list_skills", enabled_only))
        return {"skills": [{"name": "demo", "enabled": enabled_only}]}

    def upload_files(self, thread_id, files):
        self.calls.append(("upload_files", thread_id, files))
        return {"success": True, "thread_id": thread_id, "count": len(files)}

    def get_skill(self, name):
        self.calls.append(("get_skill", name))
        return self.skill_map.get(name)

    def install_skill(self, skill_path):
        self.calls.append(("install_skill", skill_path))
        return {"success": True, "skill_name": Path(skill_path).stem}

    def stream(self, message, **kwargs):
        self.calls.append(("stream", message, kwargs))
        yield from self.stream_events



def test_deerflow_chat_forwards_args_and_returns_answer(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    monkeypatch.setattr(module, "_make_client", lambda agent_name=None: fake)

    result = module.deerflow_chat(
        message="hello",
        thread_id="thread-123",
        model_name="model-x",
        thinking_enabled=False,
        plan_mode=True,
        subagent_enabled=True,
    )

    assert result == {"thread_id": "thread-123", "answer": "ok"}
    assert fake.calls == [
        (
            "chat",
            "hello",
            {
                "thread_id": "thread-123",
                "model_name": "model-x",
                "thinking_enabled": False,
                "plan_mode": True,
                "subagent_enabled": True,
            },
        )
    ]



def test_deerflow_chat_generates_thread_id_when_missing(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    monkeypatch.setattr(module, "_make_client", lambda agent_name=None: fake)
    monkeypatch.setattr(module.uuid, "uuid4", lambda: "generated-id")

    result = module.deerflow_chat(message="hello")

    assert result == {"thread_id": "generated-id", "answer": "ok"}
    assert fake.calls[0][2]["thread_id"] == "generated-id"



def test_list_skills_passes_enabled_only(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    monkeypatch.setattr(module, "_make_client", lambda agent_name=None: fake)

    result = module.deerflow_list_skills(enabled_only=False)

    assert result == {"skills": [{"name": "demo", "enabled": False}]}
    assert fake.calls == [("list_skills", False)]



def test_upload_files_converts_strings_to_paths(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    monkeypatch.setattr(module, "_make_client", lambda agent_name=None: fake)

    result = module.deerflow_upload_files("thread-1", ["/tmp/a.txt", "/tmp/b.txt"])

    assert result == {"success": True, "thread_id": "thread-1", "count": 2}
    _, thread_id, files = fake.calls[0]
    assert thread_id == "thread-1"
    assert files == [Path("/tmp/a.txt"), Path("/tmp/b.txt")]



def test_deerflow_get_skill_returns_found_and_missing(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    monkeypatch.setattr(module, "_make_client", lambda agent_name=None: fake)

    found = module.deerflow_get_skill("demo")
    missing = module.deerflow_get_skill("missing")

    assert found["found"] is True
    assert found["name"] == "demo"
    assert missing == {"name": "missing", "found": False}
    assert fake.calls == [("get_skill", "demo"), ("get_skill", "missing")]



def test_deerflow_install_skill_converts_path(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    monkeypatch.setattr(module, "_make_client", lambda agent_name=None: fake)

    result = module.deerflow_install_skill("/tmp/demo.skill")

    assert result == {"success": True, "skill_name": "demo"}
    assert fake.calls == [("install_skill", Path("/tmp/demo.skill"))]



def test_deerflow_chat_mode_maps_presets(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    monkeypatch.setattr(module, "_make_client", lambda agent_name=None: fake)

    result = module.deerflow_chat_mode("research this", mode="ultra", thread_id="t-1")

    assert result == {"thread_id": "t-1", "mode": "ultra", "answer": "ok"}
    assert fake.calls == [
        (
            "chat",
            "research this",
            {
                "thread_id": "t-1",
                "model_name": None,
                "thinking_enabled": True,
                "plan_mode": True,
                "subagent_enabled": True,
            },
        )
    ]



def test_deerflow_chat_mode_rejects_unknown_mode():
    module = load_wrapper_module()

    with pytest.raises(ValueError):
        module.deerflow_chat_mode("hello", mode="weird")



def test_deerflow_chat_agent_uses_named_client(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    seen = []

    def fake_make_client(agent_name=None):
        seen.append(agent_name)
        return fake

    monkeypatch.setattr(module, "_make_client", fake_make_client)

    result = module.deerflow_chat_agent("hello", agent_name="researcher", thread_id="agent-thread")

    assert result == {"thread_id": "agent-thread", "agent_name": "researcher", "answer": "ok"}
    assert seen == ["researcher"]
    assert fake.calls == [
        (
            "chat",
            "hello",
            {
                "thread_id": "agent-thread",
                "model_name": None,
                "thinking_enabled": True,
                "plan_mode": False,
                "subagent_enabled": False,
            },
        )
    ]



def test_deerflow_stream_collects_events_and_reports_truncation(monkeypatch):
    module = load_wrapper_module()
    fake = FakeClient()
    fake.stream_events = [
        FakeEvent("messages-tuple", {"type": "ai", "content": "a"}),
        FakeEvent("values", {"messages": []}),
        FakeEvent("end", {"usage": {}}),
    ]
    monkeypatch.setattr(module, "_make_client", lambda agent_name=None: fake)

    result = module.deerflow_stream("hello", thread_id="stream-thread", max_events=2)

    assert result["thread_id"] == "stream-thread"
    assert result["truncated"] is True
    assert result["events"] == [
        {"type": "messages-tuple", "data": {"type": "ai", "content": "a"}},
        {"type": "values", "data": {"messages": []}},
    ]
    assert fake.calls == [
        (
            "stream",
            "hello",
            {
                "thread_id": "stream-thread",
                "model_name": None,
                "thinking_enabled": True,
                "plan_mode": False,
                "subagent_enabled": False,
            },
        )
    ]



def test_deerflow_thread_history_uses_helper(monkeypatch):
    module = load_wrapper_module()
    seen = []

    def fake_history(thread_id, limit=10, before=None):
        seen.append((thread_id, limit, before))
        return [{"checkpoint_id": "cp-1"}]

    monkeypatch.setattr(module, "_get_thread_history_data", fake_history)

    result = module.deerflow_thread_history("thread-x", limit=5, before="cp-9")

    assert result == {"thread_id": "thread-x", "history": [{"checkpoint_id": "cp-1"}]}
    assert seen == [("thread-x", 5, "cp-9")]



def test_deerflow_list_threads_uses_helper(monkeypatch):
    module = load_wrapper_module()
    monkeypatch.setattr(module, "_list_threads_data", lambda limit=10: {"thread_list": [{"thread_id": "t1"}], "limit": limit})

    assert module.deerflow_list_threads(limit=7) == {"thread_list": [{"thread_id": "t1"}], "limit": 7}



def test_deerflow_get_thread_uses_helper(monkeypatch):
    module = load_wrapper_module()
    monkeypatch.setattr(module, "_get_thread_data", lambda thread_id: {"thread_id": thread_id, "checkpoints": []})

    assert module.deerflow_get_thread("thread-y") == {"thread_id": "thread-y", "checkpoints": []}



def test_deerflow_list_agents_uses_helper(monkeypatch):
    module = load_wrapper_module()
    monkeypatch.setattr(module, "_list_agents_data", lambda: {"agents": [{"name": "researcher"}]})

    assert module.deerflow_list_agents() == {"agents": [{"name": "researcher"}]}



def test_deerflow_get_agent_uses_helper(monkeypatch):
    module = load_wrapper_module()
    monkeypatch.setattr(module, "_get_agent_data", lambda name: {"name": name, "soul": "hi"})

    assert module.deerflow_get_agent("researcher") == {"name": "researcher", "soul": "hi"}



def test_deerflow_create_agent_uses_helper(monkeypatch):
    module = load_wrapper_module()
    seen = []

    def fake_create(name, description="", model=None, tool_groups=None, soul=""):
        seen.append((name, description, model, tool_groups, soul))
        return {"name": name, "description": description, "model": model, "tool_groups": tool_groups, "soul": soul}

    monkeypatch.setattr(module, "_create_agent_data", fake_create)

    result = module.deerflow_create_agent(
        name="researcher",
        description="research helper",
        model="ikuncode-gpt-5-4",
        tool_groups=["web", "file"],
        soul="be helpful",
    )

    assert result["name"] == "researcher"
    assert seen == [("researcher", "research helper", "ikuncode-gpt-5-4", ["web", "file"], "be helpful")]



def test_deerflow_update_agent_uses_helper(monkeypatch):
    module = load_wrapper_module()
    seen = []

    def fake_update(name, description=None, model=None, tool_groups=None, soul=None):
        seen.append((name, description, model, tool_groups, soul))
        return {"name": name, "description": description, "model": model, "tool_groups": tool_groups, "soul": soul}

    monkeypatch.setattr(module, "_update_agent_data", fake_update)

    result = module.deerflow_update_agent(
        name="researcher",
        description="updated",
        model="new-model",
        tool_groups=["web"],
        soul="new soul",
    )

    assert result["name"] == "researcher"
    assert seen == [("researcher", "updated", "new-model", ["web"], "new soul")]



def test_deerflow_delete_agent_uses_helper(monkeypatch):
    module = load_wrapper_module()
    seen = []

    def fake_delete(name):
        seen.append(name)
        return {"success": True, "name": name}

    monkeypatch.setattr(module, "_delete_agent_data", fake_delete)

    result = module.deerflow_delete_agent("researcher")

    assert result == {"success": True, "name": "researcher"}
    assert seen == ["researcher"]
