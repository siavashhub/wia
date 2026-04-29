# Using WIA from GitHub Copilot Chat (via MCP)

WIA ships an MCP (Model Context Protocol) server called **`wia-mcp`** that exposes
your weekly briefing and time entries as tools any MCP-compatible client can call.
This guide walks you through wiring it up to **GitHub Copilot Chat in VS Code** so
you can ask Copilot things like *"summarize my week from WIA and draft a status
email"*.

---

## What you get

Once configured, Copilot Chat (in **Agent mode**) gains three tools:

| Tool | Purpose |
| --- | --- |
| `get_weekly_briefing` | Generate or fetch the WIA weekly briefing. Optional `week_of` (any ISO date in the target week) and `refresh` (force a fresh Work IQ pull). |
| `list_time_entries` | List the editable time entries for a given week. |
| `export_entries_csv` | Return the week's entries as CSV text. |

These are the same operations the WIA desktop UI uses — Copilot just calls them
directly.

---

## Prerequisites

Before starting, make sure:

1. **WIA is installed and working.** You've run `uv run wia-desktop` at least
   once, signed into Work IQ, and successfully generated a briefing. The MCP
   server reads the same local SQLite database the desktop app writes to
   (`%LOCALAPPDATA%\WIA\WIA\wia.db`).
2. **VS Code 1.99+** (Agent mode + MCP support is GA in recent versions).
3. **GitHub Copilot** and **GitHub Copilot Chat** extensions installed and signed in.
4. You can locate the `wia-mcp` executable. After `uv sync` it lives at:

   ```
   <repo>\.venv\Scripts\wia-mcp.exe
   ```

   (If you installed WIA globally via `pipx` / `uv tool install`, it'll be on
   your `PATH` as just `wia-mcp`.)

---

## Step 1 — Verify `wia-mcp` runs

Open a PowerShell terminal in the WIA repo and activate the venv:

```pwsh
.\.venv\Scripts\Activate.ps1
wia-mcp
```

The process should start silently and wait on stdin (that's MCP's stdio
transport — it's working). Press **Ctrl+C** to exit.

If you see `command not found`, run `uv sync` again or use the full path
`.\.venv\Scripts\wia-mcp.exe`.

---

## Step 2 — Create the MCP configuration for VS Code

VS Code reads MCP server definitions from a file called `mcp.json`. You can
configure it at two scopes:

- **Workspace** (recommended for trying it out): `.vscode/mcp.json` inside the
  folder you open in VS Code.
- **User** (always available): run the command **MCP: Open User Configuration**
  from the Command Palette (`Ctrl+Shift+P`).

Add the following entry. Replace the `command` path with the absolute path to
your `wia-mcp.exe`:

```jsonc
{
  "servers": {
    "wia": {
      "type": "stdio",
      "command": "C:\\<wia-repo-path>\\.venv\\Scripts\\wia-mcp.exe"
    }
  }
}
```

If `wia-mcp` is on your `PATH` (e.g. via `uv tool install`), you can shorten it:

```jsonc
{
  "servers": {
    "wia": {
      "type": "stdio",
      "command": "wia-mcp"
    }
  }
}
```

Save the file. VS Code will offer to **Start** the server inline; click it, or
use the Command Palette: **MCP: List Servers → wia → Start**.

---

## Step 3 — Confirm the tools are discovered

1. Open Copilot Chat (`Ctrl+Alt+I`).
2. Switch the chat mode dropdown to **Agent**.
3. Click the 🛠️ **Tools** button above the input box.
4. You should see a `wia` group containing `get_weekly_briefing`,
   `list_time_entries`, and `export_entries_csv`. Make sure they're checked.

If the group is missing, run **MCP: List Servers** from the Command Palette and
check the server's output log for errors (most often: wrong path, or the venv
not having `wia` installed).

---

## Step 4 — Try it

In Agent-mode chat, ask things like:

- *"Use the wia tools to summarize what I worked on last week and produce a
  3-bullet status update."*
- *"Pull this week's WIA time entries and group them by category. Flag any
  category over 10 hours."*
- *"Export my WIA entries for the week of 2026-04-20 as CSV and save it to
  `timesheet.csv` in the workspace."*
- *"Compare this week's WIA briefing to last week's and tell me what changed."*

Copilot will request your approval the first time it invokes a tool. You can
approve once or always-allow per tool.

To force a fresh Work IQ pull rather than reading cached data:

> *"Run `get_weekly_briefing` with `refresh: true` and summarize the result."*

---

## Step 5 — (Optional) Add it to other clients

The same `wia-mcp` binary works with any MCP-compatible client. The
configuration shape varies slightly:

### Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wia": {
      "command": "C:\\<wia-repo-path>\\.venv\\Scripts\\wia-mcp.exe"
    }
  }
}
```

Restart Claude Desktop.

### Cursor

Settings → **MCP** → Add new server, type `stdio`, command pointed at
`wia-mcp.exe`. Same shape as VS Code.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Server fails to start in VS Code | Wrong path in `mcp.json` | Use the absolute path to `wia-mcp.exe` inside the WIA venv. |
| Tools list is empty | Server started but crashed | Open **MCP: List Servers → wia → Show Output** and check the log. |
| `get_weekly_briefing` returns empty data | DB is empty or no Work IQ pull has run | Open the WIA desktop app once and generate a briefing, or call with `refresh: true`. |
| Conflicts with the desktop app running | Both processes touching SQLite | Safe in normal use (WAL mode), but avoid running `refresh: true` in both at the same time. |
| Copilot doesn't pick the right tool | Ambiguous prompt | Reference WIA explicitly: *"using the wia briefing tool, …"*. |

---

## Security notes

- `wia-mcp` is **stdio-only** — it has no network listener. Only processes you
  launch (your MCP client) can talk to it.
- It reads/writes your local WIA SQLite DB. There is no separate auth layer;
  trust is inherited from the client process.
- It does **not** hold M365 credentials. Refresh calls go through the same
  `@microsoft/workiq` CLI the desktop app uses, which owns its own auth.
- Do **not** expose `wia-mcp` over a TCP/HTTP transport without adding
  authentication.

---

## Reference

- WIA MCP server source: [`apps/wia-desktop/src/wia/mcp_server/server.py`](../apps/wia-desktop/src/wia/mcp_server/server.py)
- Architecture overview: [ARCHITECTURE.md](ARCHITECTURE.md)
- VS Code MCP docs: <https://code.visualstudio.com/docs/copilot/chat/mcp-servers>
- Model Context Protocol spec: <https://modelcontextprotocol.io>
