# Hermes custom endpoint + DeerFlow MCP compatibility bundle

This repo contains the Hermes-side changes and helper files I use locally for two separate but related workflows:

1. a custom-endpoint `User-Agent` fix for OpenAI-compatible gateways that reject the default OpenAI Python SDK header
2. a DeerFlow MCP bridge bundle so Hermes can talk to DeerFlow reliably, plus an optional Hermes profile patch that keeps the DeerFlow MCP server available in newly created profiles

Everything here is currently exported from a local Hermes Agent `main` checkout at commit `1acf81fd84f3677db95ff9d6bafe5fdf1d6bf838`.

The patch filenames still keep the original `v0.8.0` label so existing local scripts do not need to change.

## Repository layout

- `patches/hermes-v0.8.0-custom-ua.patch`
  - makes Hermes send `User-Agent: HermesAgent/1.0` for generic custom OpenAI-compatible endpoints
- `patches/hermes-v0.8.0-deerflow-profile-mcp.patch`
  - patches Hermes profile creation so `mcp_servers` from the default profile are merged into new profiles
- `deerflow-mcp/deerflow_mcp.py`
  - FastMCP wrapper around `deerflow.client.DeerFlowClient`
- `deerflow-mcp/run_deerflow_mcp.sh`
  - launcher that runs the wrapper inside the DeerFlow backend via `uv`
- `deerflow-mcp/tests/test_deerflow_mcp_wrapper.py`
  - lightweight wrapper tests adapted to this repo layout
- `install_deerflow_mcp.sh`
  - copies the DeerFlow MCP wrapper/launcher into `~/.hermes/scripts/`
- `apply.sh`
  - applies one of the Hermes patches to a Hermes checkout

## DeerFlow MCP tools currently exposed

The bundled wrapper currently exposes these 19 tools:

- `deerflow_chat`
- `deerflow_chat_mode`
- `deerflow_chat_agent`
- `deerflow_stream`
- `deerflow_list_threads`
- `deerflow_get_thread`
- `deerflow_thread_history`
- `deerflow_list_models`
- `deerflow_list_skills`
- `deerflow_get_skill`
- `deerflow_list_agents`
- `deerflow_get_agent`
- `deerflow_create_agent`
- `deerflow_update_agent`
- `deerflow_delete_agent`
- `deerflow_get_memory`
- `deerflow_update_skill`
- `deerflow_install_skill`
- `deerflow_upload_files`

## DeerFlow MCP runtime controls

The chat/stream tools in this bundle now support explicit runtime controls so Hermes can choose how much DeerFlow should think and whether the run should use a named DeerFlow agent.

Supported controls:

- `reasoning_effort`
  - accepted values: `low`, `medium`, `high`
  - forwarded into DeerFlow runtime config for models that support reasoning effort
- `use_agent` + `agent_name`
  - on `deerflow_chat` and `deerflow_stream`
  - set `use_agent: true` and provide `agent_name` to route the run through a named DeerFlow agent
  - passing `agent_name` alone also enables named-agent routing
- `subagent_enabled`
  - if `true`, the wrapper force-enables DeerFlow `ultra` semantics:
    - `thinking_enabled = true`
    - `plan_mode = true`
    - `subagent_enabled = true`
  - this keeps subagent usage aligned with the DeerFlow mode model

Practical mapping:

- simple direct run: `deerflow_chat(..., reasoning_effort="low")`
- deeper direct run: `deerflow_chat(..., reasoning_effort="high")`
- named custom agent: `deerflow_chat(..., use_agent=true, agent_name="researcher")`
- explicit ultra/subagent run: `deerflow_chat_mode(..., mode="ultra", reasoning_effort="high")`

## Apply the patches

These patches are meant to be applied on top of a recent Hermes `main` checkout.

Recommended flow:

```bash
git clone git@github.com:NousResearch/hermes-agent.git ~/.hermes/hermes-agent
cd ~/.hermes/hermes-agent
git status --short
```

Make sure the checkout is clean before applying patches.

Then from this bundle repo:

```bash
./apply.sh ~/.hermes/hermes-agent all
```

Or apply each patch separately:

```bash
./apply.sh ~/.hermes/hermes-agent ua
./apply.sh ~/.hermes/hermes-agent deerflow-profile
```

If you only want to verify applicability first:

```bash
git -C ~/.hermes/hermes-agent apply --check patches/hermes-v0.8.0-custom-ua.patch
git -C ~/.hermes/hermes-agent apply --check patches/hermes-v0.8.0-deerflow-profile-mcp.patch
```

## Quick start on another machine

### 1. Clone this repo

```bash
git clone https://github.com/CatIIIIIIII/hermes-custom-endpoint-ua-fix.git
cd hermes-custom-endpoint-ua-fix
```

### 2. Install the DeerFlow MCP wrapper into Hermes

```bash
./install_deerflow_mcp.sh
```

That copies:

- `deerflow-mcp/deerflow_mcp.py` -> `~/.hermes/scripts/deerflow_mcp.py`
- `deerflow-mcp/run_deerflow_mcp.sh` -> `~/.hermes/scripts/run_deerflow_mcp.sh`

If you want a different Hermes home:

```bash
./install_deerflow_mcp.sh /path/to/hermes-home
```

### 3. Patch Hermes

```bash
./apply.sh ~/.hermes/hermes-agent all
```

### 4. Add the DeerFlow MCP server to your Hermes config

Add something like this to the active profile's `config.yaml`:

```yaml
mcp_servers:
  deerflow:
    command: /Users/yourname/.hermes/scripts/run_deerflow_mcp.sh
    args: []
    timeout: 300
    connect_timeout: 60
    env:
      DEERFLOW_BACKEND_DIR: /Users/yourname/Documents/deer-flow/backend
      DEER_FLOW_CONFIG_PATH: /Users/yourname/Documents/deer-flow/backend/config.yaml
      DEER_FLOW_EXTENSIONS_CONFIG_PATH: /Users/yourname/Documents/deer-flow/backend/extensions_config.json
```

Notes:

- Hermes MCP config uses `mcp_servers`
- DeerFlow extensions config uses `mcpServers`
- Hermes passes a filtered environment to MCP subprocesses, so put DeerFlow-specific paths under `mcp_servers.deerflow.env` if you need them
- if your DeerFlow backend is already at one of these default locations, `DEERFLOW_BACKEND_DIR` can be omitted:
  - `~/Documents/deer-flow/backend`
  - `~/deer-flow/backend`

### 5. Verify

```bash
hermes mcp test deerflow
hermes mcp list
```

If you are using profiles, remember that `hermes mcp list` reads the active profile's config.

## What the DeerFlow profile patch changes

The `deerflow-profile` patch updates Hermes profile creation so that:

- MCP servers configured on the default profile are copied into newly created named profiles
- existing profile-specific MCP server definitions are preserved and not overwritten
- DeerFlow MCP stays available without re-adding the same `mcp_servers.deerflow` block every time you create a new profile

Files touched by that Hermes patch:

- `hermes_cli/profiles.py`
- `tests/hermes_cli/test_profiles.py`

## What the custom endpoint UA patch changes

The `ua` patch makes Hermes send a neutral header for generic custom OpenAI-compatible endpoints:

```text
User-Agent: HermesAgent/1.0
```

It keeps the existing provider-specific special cases for:

- OpenRouter
- GitHub Copilot
- Kimi
- Qwen Portal

Files touched by that Hermes patch:

- `run_agent.py`
- `agent/auxiliary_client.py`

## Manual patch application

### DeerFlow profile patch

```bash
git -C ~/.hermes/hermes-agent apply patches/hermes-v0.8.0-deerflow-profile-mcp.patch
```

### Custom endpoint UA patch

```bash
git -C ~/.hermes/hermes-agent apply patches/hermes-v0.8.0-custom-ua.patch
```

## Test / sanity-check commands

### Verify the DeerFlow wrapper files are at least syntactically valid

```bash
python3 -m py_compile deerflow-mcp/deerflow_mcp.py
bash -n deerflow-mcp/run_deerflow_mcp.sh
```

### Run wrapper tests from this repo

Use the Hermes virtualenv if your shell does not already have `pytest` and the `mcp` package:

```bash
~/.hermes/hermes-agent/venv/bin/python -m pytest deerflow-mcp/tests/test_deerflow_mcp_wrapper.py
```

### Verify the Hermes profile patch applies cleanly

```bash
git -C ~/.hermes/hermes-agent apply --check patches/hermes-v0.8.0-deerflow-profile-mcp.patch
```

## Practical notes

- The DeerFlow wrapper is intentionally high-level; it exposes DeerFlow as a research/agent engine instead of mirroring every low-level DeerFlow internal tool.
- The wrapper uses lazy client creation to avoid import-time failures during inspection.
- The wrapper now exposes explicit `reasoning_effort` control for chat and stream operations.
- The generic chat/stream tools can optionally route through a named DeerFlow agent instead of forcing you to switch tools first.
- Any request that enables subagents is normalized to DeerFlow `ultra` mode semantics.
- Thread listing/history is derived from DeerFlow's checkpointer so it still works when some `DeerFlowClient` thread helpers are missing.
- The wrapper also includes custom-agent CRUD tools by writing DeerFlow agent configs directly when needed.
