"""FastAPI 应用入口 — CORS + 路由挂载。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.app.routers import auth, tasks, download, preview

app = FastAPI(title="招标文件分析系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Phase 6 收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(download.router)
app.include_router(preview.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
