"""Repository locations; platform paths are discovered separately."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"config"
ENTRY=ROOT/"rime.py"
