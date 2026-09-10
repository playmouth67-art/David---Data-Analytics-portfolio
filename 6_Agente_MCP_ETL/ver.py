#!/usr/bin/env python3
"""Imprime la salida de una herramienta, para inspección manual."""
import asyncio
import json
import sys

import server


async def main() -> None:
    tool = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    r = await server.mcp._tool_manager.call_tool(tool, {"params": args})
    texto = getattr(r[0], "text", str(r[0])) if isinstance(r, list) else str(r)
    with open("/tmp/salida_tool.md", "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"({len(texto)} caracteres escritos en /tmp/salida_tool.md)")


asyncio.run(main())
