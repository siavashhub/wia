# Authentication

**WIA does not perform M365 sign-in itself.** It does not register an Entra app, request scopes, store tokens, or call MSAL.

All authentication is delegated to the **`@microsoft/workiq` CLI**, which uses Microsoft's first-party Work IQ Entra application. The user's tenant administrator consents to that application **once** (a Microsoft-published app — not yours). After that, any Copilot-licensed user in the tenant can run Work IQ and sign in with their existing Windows / M365 identity.

This mirrors how [FlightDeck](https://github.com/kpoineal/FlightDeck) and other Work IQ clients work.

## What WIA does

1. Detects whether the `workiq` CLI is on `PATH` (`/api/workiq/status`).
2. Provides an **Enable Work IQ** button that runs the CLI once to trigger its own first-run sign-in (`/api/workiq/enable`).
3. Spawns the CLI in MCP server mode (`workiq mcp`) over stdio for every briefing query.

WIA never sees a token, never stores credentials, and has no `.env` secrets.

## Prerequisites

| | |
|---|---|
| Node.js | 18+ on PATH |
| `@microsoft/workiq` | invoked via `npx -y @microsoft/workiq` (no global install required) |
| Microsoft Copilot license | required by Work IQ for M365 access |
| Tenant admin consent | granted once for the Work IQ Entra app — not for WIA |

## First-run flow

1. User launches WIA → window opens, status badge shows **Enable Work IQ**.
2. User clicks the button → WIA spawns `workiq ask -q "ping"`.
3. Work IQ prints a sign-in URL / device code (or pops its own browser flow) — the user signs in with their existing M365 account.
4. Work IQ caches its own token. Subsequent WIA launches see `ready: true` immediately.

## Sign-out

Use the Work IQ CLI directly: `npx @microsoft/workiq logout` (or the equivalent command from the Work IQ docs). WIA does not own the token, so it cannot sign you out.
