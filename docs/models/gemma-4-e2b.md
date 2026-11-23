# Gemma 4 E2B (self-hosted)

Self-hosted multimodal LLM running on the Kendra Infra VPS via llama.cpp.

## Summary

| Field | Value |
|---|---|
| Model ID | `gemma-4-e2b` |
| Name | Gemma 4 E2B (self-hosted) |
| Provider | Google (self-hosted via llama.cpp) |
| Type | LLM (multimodal: vision + audio) |
| Lifecycle | Production |
| Parameters | E2B, Q4_K_M quantization |
| Context window | 8192 tokens |
| Cost | $0 / 1k tokens (self-hosted) |
| Endpoint | `https://srv1892964.hstgr.cloud:8666/v1/` |

## Runtime

Served by `llama-server` (llama.cpp), running as a systemd/standalone process
on the VPS, fronted by nginx (`gemma-llm-nginx` container) for TLS
termination on port 8666.

```
/opt/llama.cpp/llama-b10359/llama-server \
  --model /opt/models/gemma4-e2b/gemma-4-E2B-it-Q4_K_M.gguf \
  --mmproj /opt/models/gemma4-e2b/mmproj-F16.gguf \
  --ctx-size 8192 \
  ...
```

- Model weights: `/opt/models/gemma4-e2b/gemma-4-E2B-it-Q4_K_M.gguf`
- Multimodal projector: `/opt/models/gemma4-e2b/mmproj-F16.gguf`
- API surface: OpenAI-compatible `/v1/` endpoint

## Where it's registered

- **Kendra Infra (CAIPE UI) "LLM Models" tab** — added manually via the UI
  (MongoDB-backed, OpenFGA-RBAC-protected). Document id: `gemma-4-e2b`.
- **Backstage model catalog** (`kendra-infra/plugins/model-catalog-backend`) —
  added to the static `MOCK_MODELS` list in `src/router.ts` (uncommitted).

## Usage

Point any OpenAI-compatible client at the endpoint above with model name
`gemma-4-e2b`. No API key required for internal use; access is controlled at
the network/nginx layer.
