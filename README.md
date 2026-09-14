# Maritime Vessel Data MCP Server

Ask an AI assistant *"which tankers are anchored near Port Klang?"* and get a
real answer, from ships that are broadcasting their positions right now.

This is a [Model Context Protocol](https://modelcontextprotocol.io/) server. It
listens to live AIS radio traffic over Malaysian waters and exposes it as
standard MCP tools, so any MCP compatible client can ask about vessels without a
bespoke integration.

MIT licensed. Python 3.11 or newer. No account needed to try it, and a free API
key to run it live.

A real response, abbreviated:

```
vessels_near_port("Tanjung Pelepas", 40)

{ "data": { "source": "live", "vessel_count": 63, "oldest_position_age_seconds": 140 },
  "matches": 27,
  "vessels": [
    { "mmsi": "563186500", "name": "ALS CERES", "type": "Cargo", "flag": "Singapore",
      "length_m": 255, "status": "Moored", "destination": "MYTTP",
      "lat": 1.2612, "lon": 103.7895, "distance_nm": 16.1 } ]}
```

## Tools

| Tool | What it answers |
|------|-----------------|
| `search_vessels(vessel_type, flag, status)` | which ships match a type, flag state or navigational status |
| `vessels_near_port(port, radius_nm)` | what is within a radius of a named port, nearest first |
| `vessel_details(query)` | everything known about one ship, by MMSI or name |

Resource `vessels://all` returns the whole current picture.

Ports: Port Klang, Tanjung Pelepas, Penang, Malacca, Langkawi.

## Quick start

```bash
git clone https://github.com/ariefrsee/maritime-mcp-server.git
cd maritime-mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install .
```

That puts a `maritime-mcp-server` command on your PATH inside the environment.
Check it works without touching the network:

```bash
python -m maritime_mcp_server.smoke_test
```

It should end with `All smoke checks passed.`

## Going live

Without an API key the server answers from a bundled sample of 18 vessels and
says so. Get a free key from [aisstream.io](https://aisstream.io), then:

```bash
export AISSTREAM_API_KEY=your-key-here
maritime-mcp-server
```

You should see one line, `AIS stream connected`, and then silence. That is
correct: an MCP server over stdio prints no banner and waits for a client.

**Give it a minute before asking anything.** AIS is a stream, not a database.
The server learns about a ship only when that ship transmits, so it starts
knowing nothing and fills up over the following minutes. During testing it held
0 vessels at 3 seconds, 40 at 150 seconds and 63 at five minutes. There is no
backfill to request; the feed does not replay what you missed.

Coverage is Malaysian waters, roughly 0.5N to 7.5N and 98.5E to 105.5E, which
spans the Strait of Malacca and both coasts of the peninsula.

## Use it from Claude Desktop

Add the server to `claude_desktop_config.json`. On macOS that lives at
`~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Run `pwd` in the project directory to get the absolute path. Restart Claude
Desktop fully, then ask it something like *"which vessels are near Tanjung
Pelepas right now?"* and it will call these tools for you.

Exporting the variable in your terminal does not reach a client launched
process, so it has to go in the `env` block.

## Where the data comes from

Every response opens with a `data` block naming its source.

```json
"data": { "source": "snapshot", "vessel_count": 18, "snapshot_date": "2026-07-20",
          "note": "Live AIS is unavailable, so this is the bundled sample dataset." }
```

`source` is either `live` or `snapshot`. Nothing about how you call the tools
changes between the two, and a snapshot answer is never mistakable for a live
one.

AIS does not transmit everything these tools report. Flag state is derived from
the MMSI country digits, length from the transmitted hull dimensions, and
nearest port is computed here. **Anything AIS has not reported is `null`, never
guessed.** A ship broadcasts its position every few seconds and its identity
roughly once in ten of those, so a freshly seen vessel often has a position and
no name, type or size until it next sends static data.

The feed also carries objects that are not ships, such as navigation buoys and
base stations. Those are classified by their MMSI prefix and excluded.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

140 tests, well under a second. No API key, no network, no dependence on the
clock. The translation layer runs against 199 real AIS messages captured over
the Strait of Malacca and committed as a fixture, so it is checked against
traffic that genuinely occurred rather than against invented input.

## How it is built

| Piece | Where |
|-------|-------|
| MCP tools and the source seam | `maritime_mcp_server/server.py` |
| AIS translation and lookup tables | `maritime_mcp_server/ais_mapping.py` |
| Vessel store, merging and expiry | `maritime_mcp_server/store.py` |
| Websocket client and reconnect | `maritime_mcp_server/collector.py` |
| Bundled fallback dataset | `maritime_mcp_server/data/vessels.json` |

Built with the official [`mcp`](https://pypi.org/project/mcp/) SDK, currently
pinned below 2.0 while the code targets the 1.x FastMCP API.

Every decision, test result and mistake made while building this is written down
under `.shipline/`, one folder per piece of work, including the plans, manual
test scripts, retrospectives and runbooks.

## Extending it

- Widen the bounding box in `collector.py` to cover somewhere other than Malaysia.
- Add ports to `PORT_COORDS` in `server.py`.
- Add tools such as route ETA or anchorage occupancy. Clients discover them automatically.
- Switch `run()` to the HTTP or SSE transport for remote clients, and add authentication.

## Licence

MIT. See [LICENSE](LICENSE).
