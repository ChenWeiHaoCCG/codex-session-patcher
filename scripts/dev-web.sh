#!/bin/bash
# 开发模式启动（前后端分离，支持热更新）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

echo "🚀 Codex Session Patcher Web UI (开发模式)"
echo "=========================================="

# 检查依赖
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 未安装"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "❌ Node.js 未安装"
    exit 1
fi

# 安装 Python 依赖
echo "📦 安装 Python 依赖..."
cd "$PROJECT_DIR"
pip install -e ".[web]" -q

# 安装前端依赖
echo "📦 安装前端依赖..."
cd "$PROJECT_DIR/web/frontend"
if [ ! -d "node_modules" ]; then
    npm install
fi

# 启动后端（后台）
echo "🔧 启动后端服务 (端口 ${BACKEND_PORT})..."
cd "$PROJECT_DIR"
python -m uvicorn web.backend.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
BACKEND_PID=$!

# 等待后端启动
sleep 2

# 启动前端开发服务器
echo "🎨 启动前端开发服务器 (端口 ${FRONTEND_PORT})..."
cd "$PROJECT_DIR/web/frontend"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

echo ""
echo "✅ 服务已启动"
echo "   前端: http://localhost:${FRONTEND_PORT}"
echo "   后端: http://localhost:${BACKEND_PORT}"
echo "   API 文档: http://localhost:${BACKEND_PORT}/docs"
echo "   远程访问: http://<服务器IP>:${FRONTEND_PORT} (开发模式) 或 http://<服务器IP>:${BACKEND_PORT} (生产模式)"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号
trap "echo '停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# 等待
wait
