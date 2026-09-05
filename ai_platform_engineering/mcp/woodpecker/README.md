# Woodpecker CI MCP Server

MCP server exposing Woodpecker CI's REST API as tools, so agents can check
CI/deploy status and restart pipelines across Kendra Labs repos.

## Tools

- `list_repos` — repos the configured token can see.
- `get_repo` — details for one repo.
- `list_pipelines` — recent pipeline runs for a repo.
- `get_pipeline` — full detail (per-step status) for one pipeline run.
- `get_latest_pipeline` — most recent run, optionally filtered by branch —
  the quickest way to answer "did the last CI run / deploy succeed?".
- `restart_pipeline` — re-run a pipeline (equivalent to the UI's Restart button).

## Configuration

See `.env.example`. Required:

- `WOODPECKER_API_URL` — e.g. `https://kctl.kendralabs.com:9443`.
- `WOODPECKER_API_TOKEN` — a personal token from the Woodpecker UI
  (user avatar → Settings → generate token), or a per-request token
  supplied via the `Authorization: Bearer` header when running behind
  `mcp-agent-auth`.

## Running

```bash
make copy-env   # then fill in .env
make run
```

## Testing

```bash
make test
```
