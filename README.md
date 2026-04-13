# Hermes Custom Endpoint UA Fix

Minimal patch for Hermes Agent `v0.8.0` to support OpenAI-compatible gateways that block the default OpenAI Python SDK `User-Agent`.

## Problem

Some custom gateways accept Hermes request bodies and both:

- `POST /v1/chat/completions`
- `POST /v1/responses`

but still reject requests sent through the OpenAI Python SDK with:

```text
403 Your request was blocked.
```

In the tested environment, the gateway accepted the same request via `curl` but rejected it when the request included:

```text
User-Agent: OpenAI/Python 2.31.0
```

## What This Patch Changes

It makes Hermes send a neutral header for `provider == custom`:

```text
User-Agent: HermesAgent/1.0
```

It preserves existing special-case headers for:

- OpenRouter
- GitHub Copilot
- Kimi
- Qwen Portal

## Files Changed

- `run_agent.py`
- `agent/auxiliary_client.py`

## Tested Against

- Hermes Agent commit: `15b1a3aa69da339124f6fbbfd08c2cc27c00bc2e`
- Hermes version observed locally: `v0.8.0`

## Apply On Another Device

Clone this repo:

```bash
git clone https://github.com/CatIIIIIIII/hermes-custom-endpoint-ua-fix.git
cd hermes-custom-endpoint-ua-fix
```

Apply the patch to your Hermes checkout:

```bash
./apply.sh ~/.hermes/hermes-agent
```

If your Hermes repo lives somewhere else:

```bash
./apply.sh /path/to/hermes-agent
```

## Manual Apply

If you prefer:

```bash
git -C ~/.hermes/hermes-agent apply patches/hermes-v0.8.0-custom-ua.patch
```

## Verify

After applying:

```bash
~/.hermes/hermes-agent/venv/bin/python -m py_compile \
  ~/.hermes/hermes-agent/run_agent.py \
  ~/.hermes/hermes-agent/agent/auxiliary_client.py
```

Then restart Hermes and test your custom provider again.
