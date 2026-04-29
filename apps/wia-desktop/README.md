# wia-desktop

The WIA desktop application — Python + FastAPI in a pywebview (WebView2) window.

## Run (dev)

```pwsh
# from repo root
uv sync
uv run wia-desktop
```

## Run the exposed WIA MCP server (stdio)

```pwsh
uv run wia-mcp
```

Register in VS Code Copilot via `mcp.json`:

```json
{
  "servers": {
    "wia": { "command": "uv", "args": ["run", "wia-mcp"] }
  }
}
```

## Layout

```
src/wia/
├─ main.py             # pywebview + FastAPI entry
├─ config.py           # settings
├─ api/                # FastAPI routers
├─ core/               # orchestrator, grouping, categorization
├─ mcp_clients/workiq.py
├─ mcp_server/server.py
├─ auth/msal_wam.py
├─ storage/            # SQLModel + repo
└─ ui/                 # static HTML/JS/CSS
```
