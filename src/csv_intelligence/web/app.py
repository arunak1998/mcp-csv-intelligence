"""FastAPI app: upload with PII review, streaming chat, dashboards.  Run:  csv-intelligence-web"""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from csv_intelligence.agents.chat import answer_question
from csv_intelligence.agents.dashboard_agent import build_dashboard
from csv_intelligence.agents.dataset import active_dataset
from csv_intelligence.agents.llm import create_llm
from csv_intelligence.agents.mcp_client import McpClient, McpUnavailableError
from csv_intelligence.dashboards.render import render_dashboard
from csv_intelligence.data.datasets import remove_all_datasets
from csv_intelligence.settings import load_settings
from csv_intelligence.web.uploads import UnknownUploadError, ingest_staged, stage_upload

STATIC_DIR = Path(__file__).parent / "static"


class ColumnChoice(BaseModel):
    mask: bool = False
    rename: str | None = None


class IngestRequest(BaseModel):
    upload_id: str
    choices: dict[str, ColumnChoice] = {}


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    privacy_mode: Literal["standard", "strict"] | None = None


class DashboardRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def effective_privacy_mode(requested: str | None, configured: str) -> str:
    """PRIVACY_MODE=strict in the environment can't be relaxed from the browser."""
    return "strict" if configured == "strict" else requested or configured


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


router = APIRouter()


@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/api/status")
async def status(request: Request) -> dict[str, Any]:
    mcp = request.app.state.mcp
    settings = load_settings()
    try:
        dataset = await active_dataset(mcp)
    except McpUnavailableError:
        dataset = None
    return {
        "mcp_connected": getattr(mcp, "connected", True),
        "privacy_mode": settings.privacy_mode,
        "privacy_mode_locked": settings.privacy_mode == "strict",
        "dataset": dataset[1] if dataset else None,
    }


@router.post("/api/upload")
async def upload(file: UploadFile) -> dict[str, Any]:
    content = await file.read()
    try:
        return await asyncio.to_thread(
            stage_upload, load_settings().upload_dir, file.filename or "data.csv", content
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/ingest")
async def ingest(body: IngestRequest) -> dict[str, Any]:
    choices = {column: choice.model_dump() for column, choice in body.choices.items()}
    try:
        return await asyncio.to_thread(ingest_staged, load_settings().upload_dir, body.upload_id, choices)
    except UnknownUploadError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/api/dataset")
async def remove_dataset() -> dict[str, bool]:
    remove_all_datasets(load_settings().upload_dir)
    return {"removed": True}


async def chat_events(request: Request, body: ChatRequest) -> AsyncIterator[str]:
    settings = load_settings()
    mode = effective_privacy_mode(body.privacy_mode, settings.privacy_mode)
    try:
        llm = request.app.state.llm_factory()
        async for event in answer_question(
            body.question, request.app.state.mcp, llm, mode, settings.insight_max_rows
        ):
            yield sse(event)
    except Exception as error:  # surface setup problems (no API key, MCP down) in the chat itself
        yield sse({"type": "error", "message": str(error), "audit": [], "timings_ms": {}})


@router.post("/api/chat")
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    """Server-sent events, one JSON object per line: sql, table, privacy, insight..., done (or error)."""
    return StreamingResponse(
        chat_events(request, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/dashboard")
async def dashboard(request: Request, body: DashboardRequest) -> dict[str, Any]:
    try:
        result = await build_dashboard(body.question, request.app.state.mcp, request.app.state.llm_factory())
    except McpUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "html": render_dashboard(result["spec"]),
        "audit": result["audit"],
        "timings_ms": result["timings_ms"],
    }


def create_app(mcp: Any = None, llm_factory: Callable[[], BaseChatModel] = create_llm) -> FastAPI:
    """mcp: an already-connected client (tests); by default one McpClient lives as long as the app."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if mcp is not None:
            app.state.mcp = mcp
            yield
            return
        client = McpClient(load_settings().mcp_url)
        await client.start()
        app.state.mcp = client
        try:
            yield
        finally:
            await client.stop()

    app = FastAPI(title="MCP CSV Intelligence", lifespan=lifespan)
    app.state.llm_factory = llm_factory
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    print(f"[web] open http://{'localhost' if host == '127.0.0.1' else host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
