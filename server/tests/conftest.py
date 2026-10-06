"""Server modules import each other by bare name (`import engine_path`), as
uvicorn runs them from inside server/ — put that folder on sys.path."""

import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))
