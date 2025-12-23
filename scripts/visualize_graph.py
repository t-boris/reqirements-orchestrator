#!/usr/bin/env python3
"""
Generate visual representation of the LangGraph workflow.

Usage:
    python scripts/visualize_graph.py
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

# Check for required env vars
required_vars = ["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET"]
missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"Error: Missing environment variables: {', '.join(missing)}")
    print("\nEnsure .env file exists with required keys")
    sys.exit(1)

from src.graph.graph import create_graph


def main():
    """Generate graph visualization."""
    print("Creating graph...")
    graph = create_graph(checkpointer=None)

    # Generate Mermaid diagram
    mermaid = graph.get_graph().draw_mermaid()
    print("\n=== Mermaid Diagram ===")
    print(mermaid)

    # Save to file
    mermaid_path = Path(__file__).parent.parent / "docs" / "workflow.mmd"
    mermaid_path.parent.mkdir(exist_ok=True)
    mermaid_path.write_text(mermaid)
    print(f"\nSaved to: {mermaid_path}")

    # Try to generate PNG if graphviz is available
    try:
        png_path = Path(__file__).parent.parent / "docs" / "workflow.png"
        graph.get_graph().draw_png(str(png_path))
        print(f"PNG saved to: {png_path}")
    except Exception as e:
        print(f"\nNote: PNG generation requires graphviz. Install with: brew install graphviz")
        print(f"Error: {e}")

    print("\nTip: Paste Mermaid code into https://mermaid.live/ to visualize online")


if __name__ == "__main__":
    main()
