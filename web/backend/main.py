"""
FastAPI 主入口
"""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

from .api import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时
    print("🚀 Codex Session Patcher Web UI 启动中...")
    yield
    # 关闭时
    print("👋 Codex Session Patcher Web UI 已关闭")


app = FastAPI(
    title="Codex Session Patcher",
    description="清理 AI 拒绝回复，恢复会话",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(router, prefix="/api")

# 静态文件（前端构建产物）
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")
else:
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def frontend_not_built():
        return HTMLResponse(
            """
            <!DOCTYPE html>
            <html lang="zh-CN">
            <head>
              <meta charset="UTF-8" />
              <meta name="viewport" content="width=device-width, initial-scale=1.0" />
              <title>Codex Session Patcher</title>
              <style>
                body {
                  margin: 0;
                  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                  background: #0f172a;
                  color: #e2e8f0;
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  min-height: 100vh;
                }
                .card {
                  max-width: 720px;
                  margin: 24px;
                  padding: 28px 32px;
                  border-radius: 16px;
                  background: #111827;
                  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
                }
                h1 { margin-top: 0; font-size: 24px; }
                p, li { line-height: 1.6; color: #cbd5e1; }
                code {
                  background: #1e293b;
                  padding: 2px 6px;
                  border-radius: 6px;
                }
              </style>
            </head>
            <body>
              <div class="card">
                <h1>前端页面未构建</h1>
                <p>后端服务已启动，但 <code>web/frontend/dist</code> 不存在，因此 Web UI 页面无法访问。</p>
                <p>请先构建前端：</p>
                <ul>
                  <li><code>cd web/frontend</code></li>
                  <li><code>npm install</code></li>
                  <li><code>npm run build</code></li>
                </ul>
                <p>然后重新启动服务，或直接使用项目脚本：<code>./scripts/start-web.sh restart</code></p>
              </div>
            </body>
            </html>
            """
        )


def run_server(host: str = "0.0.0.0", port: int = 47832):
    """启动服务器"""
    import uvicorn
    print(f"📍 访问地址: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
