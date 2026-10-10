"""``python -m crucible.mcp_server``: serve over stdio."""

from crucible.mcp_server.server import main

if __name__ == "__main__":  # a module walker (tools.docgen) imports this file: it must not serve
    raise SystemExit(main())
