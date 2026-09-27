"""repo2demo — turn any GitHub repo into an interactive guided demo."""
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("R2D_PORT", "8766"))
    uvicorn.run("backend.server:app", host="127.0.0.1", port=port, reload=False)
