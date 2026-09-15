"""Smoke-test the maritime MCP server as a real MCP client would use it.

Spawns the server over stdio, lists its tools and resources, reads the
vessels://all resource, and calls search_vessels.

    ./.venv/bin/python mcp_client_check.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "maritime_mcp_server.server"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("tools:", ", ".join(t.name for t in tools.tools))

            resources = await session.list_resources()
            print("resources:", ", ".join(str(r.uri) for r in resources.resources))

            result = await session.read_resource("vessels://all")
            payload = json.loads(result.contents[0].text)
            print("resource data.source:", payload["data"]["source"])
            print("resource vessel count:", len(payload["vessels"]))
            first = payload["vessels"][0]
            print("first vessel:", first.get("name"), first.get("mmsi"), first.get("type"))

            call = await session.call_tool("search_vessels", {"vessel_type": "tanker"})
            tanks = json.loads(call.content[0].text)
            print("search_vessels(tanker) matches:", tanks["matches"])

            near = await session.call_tool("vessels_near_port", {"port": "Port Klang", "radius_nm": 50})
            nearby = json.loads(near.content[0].text)
            print("vessels_near_port(Port Klang, 50nm):", nearby["matches"])

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
