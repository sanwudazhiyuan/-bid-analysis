"""FastAPI 应用入口 — CORS + 路由挂载。"""

import time
from collections import defaultdict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from server.app.routers import auth, tasks, download, preview, annotations, users, files

app = FastAPI(title="招标文件分析系统", version="1.0.0")

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


@app.get("/api/health")
async def health():
    return {"status": "ok"}
