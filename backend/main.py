"""Lab Research Agent v1 API skeleton.

Launch from the project root:
    python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""

from fastapi import FastAPI

app = FastAPI(title="Lab Research Agent API", version="1.0.0-dev")


@app.get("/api/health")
def health() -> dict[str, str]:
    """Check that the local API is responding (does not read the PDF database)."""
    return {
        "status": "ok",
        "application": "Lab Research Agent",
        "version": "1.0.0-dev",
    }
