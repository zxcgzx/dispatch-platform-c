"""FastAPI 入口：/api 路由 + 托管前端构建产物（backend/app/static/）。

开发：uvicorn app.main:app --reload --port 8000（前端 npm run dev，Vite 代理 /api）
演示：python run.py → http://localhost:8000（不需要 Node）
"""
from __future__ import annotations

import importlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR
from .api.routes_base import router as base_router

app = FastAPI(title="课题 4 建模工作台", version="0.1.0")
app.include_router(base_router, prefix="/api")

# 后续里程碑的路由：存在才挂载，避免骨架阶段缺模块时整体起不来
for _mod in ("routes_tasks", "routes_solve", "routes_test", "routes_measure"):
    try:
        _m = importlib.import_module(f"{__package__}.api.{_mod}")
    except ModuleNotFoundError as e:  # 仅当模块本身不存在时忽略；模块内部依赖缺失要暴露
        if e.name and e.name.endswith(_mod):
            continue
        raise
    app.include_router(_m.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.exception_handler(ValueError)
async def value_error_handler(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """前端为 SPA（history 路由）：非 /api 的路径都回 index.html，/embed/workbench 同理。"""
        if full_path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        f = (STATIC_DIR / full_path).resolve()
        if full_path and f.is_file() and STATIC_DIR in f.parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def no_frontend():
        return JSONResponse(
            {"message": "前端尚未构建。开发：cd frontend && npm run dev；或 npm run build 输出到 backend/app/static/。",
             "api_docs": "/docs"}
        )
