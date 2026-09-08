---
name: browser-tooling
description: >-
  Use when a Codex or Claude pane must drive a shared Chrome session or an
  isolated headless browser. Provides inspection through chrome-devtools-mcp.
---

# Add browser tooling

Use `chrome-devtools-mcp` to give each pane navigation, DOM snapshots, screenshots, console access,
network data, evaluation, and performance traces.

## Choose the browser mode

Use `--browserUrl` to attach every pane to one shared Chrome instance. Use this mode for an existing
authenticated profile or a page that an operator can watch.

Omit `--browserUrl` to let the server launch an isolated headless browser. Use this mode when panes
must not share cookies, tabs, or browser state.

## Register Codex

Add this block to the Codex configuration:

```toml
[mcp_servers.chrome-devtools]
command = "npx"
args = ["-y", "chrome-devtools-mcp@latest", "--browserUrl=http://127.0.0.1:9222"]
```

Restart the pane after the configuration changes.

## Register Claude

Run:

```bash
claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest --browserUrl=http://127.0.0.1:9222
```

Restart the pane after registration.

## Cross a blocked firewall direction

If the client cannot connect to the browser, run a reverse relay. Put a hub beside the client. Make
the browser side connect outward to the hub. Relay each client request through that connection.
This direction worked when a firewall blocked inbound connections to the browser side
`[observed: 2026-09-08 operator]`.

## Work within observed limits

- Dense accessibility snapshots reached about 32,000 characters
  `[observed: 2026-09-08 operator]`. Narrow the page before capture.
- `take_screenshot --filePath` can reject paths outside the server roots. Request inline image data
  and decode it inside an allowed path `[observed: 2026-09-08 operator]`.
- The bundled Lighthouse report has no performance category. Use a performance trace for LCP and
  CLS `[observed: 2026-09-08 operator]`.
- Dark-mode emulation changes only apps that read `prefers-color-scheme`. Change the app setting
  when the app owns its theme `[observed: 2026-09-08 operator]`.
