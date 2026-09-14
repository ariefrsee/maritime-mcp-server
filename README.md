# Maritime Vessel Data — MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that
exposes maritime vessel data as standard MCP **tools** and a **resource**. Any
MCP-compatible client — Claude Desktop, an agent framework, an IDE extension —
can query live vessel data through the protocol instead of a bespoke integration.

Built with Python and the official [`mcp`](https://pypi.org/project/mcp/) SDK
(FastMCP). MIT licensed. Requires Python 3.11 or newer. It is the same tool surface used by the companion
[maritime-vessel-agent](https://github.com/Ariefrse/maritime-vessel-agent)
project, published here as a reusable, protocol-standard server.

## What it demonstrates

| Capability | Where |
|---|---|
| Model Context Protocol (MCP) | `src/server.py` — a FastMCP server over stdio |
| Tool design | `search_vessels`, `vessels_near_port`, `vessel_details` |
| MCP resources | `vessels://all` exposes the dataset as a readable resource |
| Interoperability | works with any MCP client — no client-specific code |

## Tools

| Tool | Purpose |
|---|---|
| `search_vessels(vessel_type, flag, status)` | filter the fleet by type / flag / navigational status |
| `vessels_near_port(port, radius_nm)` | vessels within a radius of a named port, distance-annotated |
| `vessel_details(query)` | look up one vessel by MMSI or name |

Resource `vessels://all` returns the full dataset.

## Setup

Requires Python 3.11 or newer.

```bash
git clone https://github.com/Ariefrse/maritime-mcp-server.git
cd maritime-mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install .
```

That puts a `maritime-mcp-server` command on your PATH inside the environment.

## Verify it works (offline)

```bash
python -m maritime_mcp_server.smoke_test
```

This exercises every tool without needing an MCP client.

## Run the server

```bash
maritime-mcp-server        # serves over stdio (how MCP clients launch it)
```

The dataset ships inside the package, so the server runs correctly from any
working directory.

## Use it from Claude Desktop

Add the server to your `claude_desktop_config.json`
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "maritime-vessel-data": {
      "command": "/absolute/path/to/.venv/bin/maritime-mcp-server"
    }
  }
}
```

No `args` and no `cwd` are needed. If the environment is on your PATH already,
`"command": "maritime-mcp-server"` is enough.

Restart Claude Desktop, then ask it questions like *"Which tankers are at anchor
near Port Klang?"* — it will call the server's tools directly.

## Live AIS

The server answers from a bundled 18 vessel sample until you give it an API key.
With one, it holds a websocket to [aisstream.io](https://aisstream.io) for as
long as it is running and answers from real vessel traffic instead.

Get a free key from aisstream.io, then:

```bash
export AISSTREAM_API_KEY=your-key-here
maritime-mcp-server
```

For an MCP client, put it in the server's environment:

```json
{
  "mcpServers": {
    "maritime-vessel-data": {
      "command": "/absolute/path/to/.venv/bin/maritime-mcp-server",
      "env": { "AISSTREAM_API_KEY": "your-key-here" }
    }
  }
}
```

Without the variable the server still starts, logs one line saying live AIS is
off, and serves the snapshot. That is a supported mode, not a failure.

**What live mode does not promise.** AIS is a stream, not a database. The server
learns about a vessel only when that vessel transmits, so it starts knowing
nothing and fills up over the following minutes. Ask it a question ten seconds
after launch and you will get very little. Ships broadcast their position every
few seconds and their identity roughly once in ten of those, so a vessel often
has a position long before it has a name, type or size. Entries are forgotten
after 30 minutes without a transmission, because a ship that stopped reporting
is not still there.

Coverage is Malaysian waters: the Strait of Malacca and both coasts of the
peninsula, roughly 0.5&deg;N to 7.5&deg;N and 98.5&deg;E to 105.5&deg;E.

## Where the data comes from

Every tool response opens with a `data` block saying where its answer came from.

```json
{
  "data": { "source": "snapshot", "vessel_count": 18, "snapshot_date": "2026-07-20",
            "note": "Live AIS is unavailable, so this is the bundled sample dataset." },
  "matches": 1,
  "vessels": [ ... ]
}
```

`source` is either `live` or `snapshot`, and the block carries how old the
oldest position is. Nothing about how you call these tools changes between the
two modes, and a snapshot answer is never mistakable for a live one.

Live records are built from AIS, which does not transmit everything these tools
report. Flag state is derived from the MMSI, length from the hull dimensions, and
nearest port is computed here. **Anything AIS has not reported yet is `null`,
never guessed.** A vessel usually broadcasts its position far more often than its
identity, so a freshly seen ship may have a position and no name, type or length
until it next sends static data.

## Extending it

- Widen the bounding box in `collector.py` to cover more than Malaysian waters.
- Add tools (route ETA, anchorage occupancy) — clients discover them automatically.
- Add authentication and switch to the HTTP/SSE transport for remote clients.

## Licence

MIT. See [LICENSE](LICENSE).
