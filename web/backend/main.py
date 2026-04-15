"""
FastAPI main entrypoint.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle hooks."""
    print("Codex Session Patcher Web UI starting...")
    yield
    print("Codex Session Patcher Web UI stopped")


app = FastAPI(
    title="Codex Session Patcher",
    description="Clean AI refusal responses and restore session continuity.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")


def run_server(host: str = "127.0.0.1", port: int = 47832):
    """Start the web server."""
    import uvicorn

    print(f"Web UI address: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
