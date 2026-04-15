"""FastAPI 应用入口 — CORS + 路由挂载。"""

import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from server.app.database import engine, Base, async_session_factory
from server.app.routers import auth, tasks, download, preview, annotations, users, files, reviews, config as config_router
import server.app.models.review_task  # noqa: F401 — ensure table is created


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables if missing, init config, then yield to app."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize system_config from settings.yaml if not exists
    async with async_session_factory() as db:
        from server.app.services.model_config_service import ModelConfigService
        await ModelConfigService.initialize_on_startup(db)
        await db.commit()

    yield


app = FastAPI(title="招标文件分析系统", version="1.0.0", lifespan=lifespan)

# Simple in-memory rate limiting
_rate_limits: dict[str, list[float]] = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/api/tasks" and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()
            _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < 60]
            if len(_rate_limits[client_ip]) >= 10:
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
            _rate_limits[client_ip].append(now)
        return await call_next(request)


# RateLimitMiddleware is added FIRST so it wraps outermost (checked before CORS)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:80"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(download.router)
app.include_router(preview.router)
app.include_router(annotations.router)
app.include_router(users.router)
app.include_router(files.router)
app.include_router(reviews.router)
app.include_router(config_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
