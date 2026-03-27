from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.analyzer.js_ts import analyze_directory


def main() -> None:
    p = argparse.ArgumentParser(description="Codebase Execution Simulator CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Analyze a directory and print graph summary")
    a.add_argument("path", type=Path, help="Root directory of the codebase")
    a.add_argument("--json", action="store_true", help="Print full graph JSON")

    args = p.parse_args()
    if args.cmd == "analyze":
        root = args.path.resolve()
        if not root.is_dir():
            print(f"Not a directory: {root}", file=sys.stderr)
            sys.exit(1)
        store = analyze_directory(root)
        data = store.to_dict()
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"Nodes: {len(data['nodes'])}  Edges: {len(data['edges'])}")
            for n in data["nodes"][:20]:
                print(f"  - {n.get('kind')} {n.get('name')} ({n.get('filePath', '')})")
            if len(data["nodes"]) > 20:
                print(f"  ... and {len(data['nodes']) - 20} more")


if __name__ == "__main__":
    main()
