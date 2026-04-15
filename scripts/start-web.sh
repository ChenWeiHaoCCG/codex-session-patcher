#!/bin/bash
# Codex Session Patcher Web UI 管理脚本

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RUN_DIR="${PROJECT_DIR}/.run"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
NPM_BIN="${NPM_BIN:-npm}"
TAIL_LINES="${TAIL_LINES:-50}"
NO_INSTALL="${NO_INSTALL:-0}"
NO_BUILD="${NO_BUILD:-0}"
CONDA_BIN_OVERRIDE="${CONDA_BIN:-}"
CONDA_ENV_PATH="${CONDA_ENV_PATH:-${PROJECT_DIR}/.conda/web}"
CONDA_PYTHON_VERSION="${CONDA_PYTHON_VERSION:-3.11}"
CONDA_CHANNELS="${CONDA_CHANNELS:-conda-forge}"

PID_FILE_OVERRIDE="${PID_FILE:-}"
LOG_FILE_OVERRIDE="${LOG_FILE:-}"
PID_FILE=""
LOG_FILE=""
CONDA_BIN=""
ENV_PYTHON=""
CONDA_CREATE_CHANNEL_ARGS=()
FRONTEND_DIST_DIR="${PROJECT_DIR}/web/frontend/dist"
FRONTEND_INDEX_FILE="${FRONTEND_DIST_DIR}/index.html"

ACTION="run"
if [ $# -gt 0 ]; then
    case "$1" in
        start|stop|restart|status|run|logs|help)
            ACTION="$1"
            shift
            ;;
        -h|--help)
            ACTION="help"
            shift
            ;;
    esac
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --host=*)
            HOST="${1#*=}"
            shift
            ;;
        --host)
            HOST="${2:-}"
            shift 2
            ;;
        --port=*)
            PORT="${1#*=}"
            shift
            ;;
        --port)
            PORT="${2:-}"
            shift 2
            ;;
        --conda-env-path=*)
            CONDA_ENV_PATH="${1#*=}"
            shift
            ;;
        --conda-env-path)
            CONDA_ENV_PATH="${2:-}"
            shift 2
            ;;
        --python-version=*)
            CONDA_PYTHON_VERSION="${1#*=}"
            shift
            ;;
        --python-version)
            CONDA_PYTHON_VERSION="${2:-}"
            shift 2
            ;;
        --conda-channel=*)
            CONDA_CHANNELS="${1#*=}"
            shift
            ;;
        --conda-channel)
            CONDA_CHANNELS="${2:-}"
            shift 2
            ;;
        --no-install)
            NO_INSTALL="1"
            shift
            ;;
        --no-build)
            NO_BUILD="1"
            shift
            ;;
        --tail)
            TAIL_LINES="${2:-}"
            shift 2
            ;;
        -h|--help)
            ACTION="help"
            shift
            ;;
        [0-9]*)
            PORT="$1"
            shift
            ;;
        *)
            echo "❌ 未知参数: $1" >&2
            ACTION="help"
            break
            ;;
    esac
done

print_header() {
    echo "🚀 Codex Session Patcher Web UI"
    echo "================================"
}

usage() {
    print_header
    cat <<EOF
用法:
  ./scripts/start-web.sh [run|start|stop|restart|status|logs] [端口] [选项]

命令:
  run       前台运行，按 Ctrl+C 停止（默认）
  start     后台启动
  stop      停止后台服务
  restart   重启后台服务
  status    查看运行状态
  logs      查看日志（默认 tail -f）

选项:
  --host <host>     监听地址，默认: ${HOST}
  --port <port>     监听端口，默认: ${PORT}
  --conda-env-path  Conda 环境目录，默认: ${CONDA_ENV_PATH}
  --python-version  Conda Python 版本，默认: ${CONDA_PYTHON_VERSION}
  --conda-channel   Conda 渠道，默认: ${CONDA_CHANNELS}
  --no-install      跳过依赖安装
  --no-build        跳过前端构建
  --tail <lines>    logs 模式显示的日志行数，默认: ${TAIL_LINES}

示例:
  ./scripts/start-web.sh start 9090
  ./scripts/start-web.sh restart --port 9090
  ./scripts/start-web.sh status 9090
  ./scripts/start-web.sh start --conda-env-path ./.conda/web-py311
  ./scripts/start-web.sh start --conda-channel conda-forge

环境变量:
  HOST / PORT / NPM_BIN / CONDA_BIN / CONDA_ENV_PATH / CONDA_PYTHON_VERSION / CONDA_CHANNELS
  PID_FILE / LOG_FILE / NO_INSTALL / NO_BUILD
EOF
}

require_cmd() {
    local cmd="$1"
    local message="$2"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "❌ ${message}" >&2
        exit 1
    fi
}

ensure_run_dir() {
    mkdir -p "$RUN_DIR"
}

validate_port() {
    case "$PORT" in
        ''|*[!0-9]*)
            echo "❌ 端口必须是数字: $PORT" >&2
            exit 1
            ;;
    esac
}

refresh_runtime_paths() {
    local pid_file_default="${RUN_DIR}/codex-patcher-web-${PORT}.pid"
    local log_file_default="${RUN_DIR}/codex-patcher-web-${PORT}.log"

    PID_FILE="${PID_FILE_OVERRIDE:-$pid_file_default}"
    LOG_FILE="${LOG_FILE_OVERRIDE:-$log_file_default}"
    ENV_PYTHON="${CONDA_ENV_PATH}/bin/python"
}

resolve_conda_bin() {
    if [ -n "$CONDA_BIN_OVERRIDE" ] && [ -x "$CONDA_BIN_OVERRIDE" ]; then
        CONDA_BIN="$CONDA_BIN_OVERRIDE"
        return
    fi

    if [ -n "${CONDA_EXE:-}" ] && [ -x "${CONDA_EXE}" ]; then
        CONDA_BIN="${CONDA_EXE}"
        return
    fi

    if command -v conda >/dev/null 2>&1; then
        CONDA_BIN="$(command -v conda)"
        return
    fi

    for candidate in \
        "$HOME/miniconda3/bin/conda" \
        "$HOME/anaconda3/bin/conda" \
        "$HOME/mambaforge/bin/conda" \
        "/opt/conda/bin/conda" \
        "/usr/local/miniconda3/bin/conda"; do
        if [ -x "$candidate" ]; then
            CONDA_BIN="$candidate"
            return
        fi
    done

    echo "❌ 未找到 conda，请先安装 Conda 或通过 CONDA_BIN 指定 conda 路径" >&2
    exit 1
}

build_conda_channel_args() {
    local channels_raw="$CONDA_CHANNELS"
    local channel

    CONDA_CREATE_CHANNEL_ARGS=(--override-channels)

    if [ -z "$channels_raw" ]; then
        echo "❌ CONDA_CHANNELS 不能为空" >&2
        exit 1
    fi

    channels_raw="${channels_raw//,/ }"
    for channel in $channels_raw; do
        CONDA_CREATE_CHANNEL_ARGS+=(-c "$channel")
    done
}

ensure_conda_env() {
    if [ -x "$ENV_PYTHON" ]; then
        echo "🐍 Conda 环境已就绪: $CONDA_ENV_PATH"
        return
    fi

    if [ "$NO_INSTALL" = "1" ]; then
        echo "❌ 已指定 --no-install，但 Conda 环境不存在: $CONDA_ENV_PATH" >&2
        exit 1
    fi

    echo "🐍 创建 Conda 环境: $CONDA_ENV_PATH"
    if ! "$CONDA_BIN" create -y -p "$CONDA_ENV_PATH" "${CONDA_CREATE_CHANNEL_ARGS[@]}" "python=${CONDA_PYTHON_VERSION}" pip; then
        cat >&2 <<EOF
❌ Conda 环境创建失败
当前渠道: ${CONDA_CHANNELS}

如果你仍然看到 ToS 错误，可以继续使用不依赖 defaults 的渠道，例如:
  ./scripts/start-web.sh start ${PORT} --conda-channel conda-forge

如果你就是要使用 defaults，请先手动接受 ToS:
  conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
  conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
EOF
        exit 1
    fi
}

read_pid() {
    if [ -f "$PID_FILE" ]; then
        tr -d '[:space:]' < "$PID_FILE"
    fi
}

pid_matches_service() {
    local pid="$1"
    local cmdline
    cmdline="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    case "$cmdline" in
        *"uvicorn web.backend.main:app"*|*"web.backend.main:app"*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_running() {
    local pid
    pid="$(read_pid)"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && pid_matches_service "$pid"
}

cleanup_stale_pid() {
    if [ -f "$PID_FILE" ] && ! is_running; then
        echo "⚠️  发现失效的 PID 文件，已清理"
        rm -f "$PID_FILE"
    fi
}

install_python_deps() {
    ensure_conda_env

    if [ "$NO_INSTALL" = "1" ]; then
        echo "⏭️  已跳过 Python 依赖安装（Conda 环境保留）"
        return
    fi

    echo "📦 安装 Python 依赖到 Conda 环境..."
    cd "$PROJECT_DIR"
    "$ENV_PYTHON" -m pip install -e ".[web]" -q
}

install_frontend_deps() {
    cd "$PROJECT_DIR/web/frontend"

    if [ -d "node_modules" ]; then
        echo "📦 前端依赖已就绪"
        return
    fi

    if [ "$NO_INSTALL" = "1" ]; then
        echo "❌ 已指定 --no-install，但缺少 web/frontend/node_modules" >&2
        exit 1
    fi

    echo "📦 安装前端依赖..."
    "$NPM_BIN" install
}

build_frontend() {
    if [ "$NO_BUILD" = "1" ]; then
        echo "⏭️  已跳过前端构建"
        return
    fi

    echo "🔨 构建前端..."
    cd "$PROJECT_DIR/web/frontend"
    "$NPM_BIN" run build
}

verify_frontend_build() {
    if [ ! -f "$FRONTEND_INDEX_FILE" ]; then
        cat >&2 <<EOF
❌ 前端构建产物不存在: $FRONTEND_INDEX_FILE

这意味着后端虽然能启动，但访问 / 时不会有前端页面。
请检查前端构建日志，或手动执行:
  cd web/frontend
  ${NPM_BIN} install
  ${NPM_BIN} run build
EOF
        exit 1
    fi
}

prepare_runtime() {
    print_header
    validate_port
    refresh_runtime_paths
    ensure_run_dir
    cleanup_stale_pid
    resolve_conda_bin
    build_conda_channel_args
    require_cmd node "Node.js 未安装，请先安装 Node.js"
    require_cmd "$NPM_BIN" "npm 未安装，请先安装 npm"
    require_cmd ps "缺少 ps 命令，无法管理后台进程"

    install_python_deps
    install_frontend_deps
    build_frontend
    verify_frontend_build
}

start_service() {
    validate_port
    refresh_runtime_paths
    cleanup_stale_pid
    if is_running; then
        local pid
        pid="$(read_pid)"
        print_header
        echo "ℹ️  服务已在运行"
        echo "PID: $pid"
        echo "地址: http://${HOST}:${PORT}"
        echo "日志: $LOG_FILE"
        echo "Conda 环境: $CONDA_ENV_PATH"
        echo "Conda 渠道: $CONDA_CHANNELS"
        return
    fi

    prepare_runtime

    echo "🌐 后台启动服务..."
    cd "$PROJECT_DIR"
    nohup "$ENV_PYTHON" -m uvicorn web.backend.main:app --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        echo "✅ 服务已启动"
        echo "PID: $pid"
        echo "地址: http://${HOST}:${PORT}"
        echo "日志: $LOG_FILE"
        echo "Conda 环境: $CONDA_ENV_PATH"
        echo "Conda 渠道: $CONDA_CHANNELS"
        echo "停止命令: ./scripts/start-web.sh stop"
    else
        rm -f "$PID_FILE"
        echo "❌ 启动失败，请查看日志: $LOG_FILE" >&2
        exit 1
    fi
}

stop_service() {
    print_header
    validate_port
    refresh_runtime_paths
    cleanup_stale_pid

    if ! is_running; then
        echo "ℹ️  服务未运行"
        return
    fi

    local pid
    pid="$(read_pid)"
    echo "🛑 停止服务 (PID: $pid)..."
    kill "$pid" 2>/dev/null || true

    for _ in $(seq 1 20); do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            echo "✅ 服务已停止"
            return
        fi
        sleep 0.5
    done

    echo "⚠️  服务未及时退出，尝试强制停止..."
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "✅ 服务已强制停止"
}

status_service() {
    print_header
    validate_port
    refresh_runtime_paths
    cleanup_stale_pid

    if is_running; then
        local pid
        pid="$(read_pid)"
        echo "✅ 服务运行中"
        echo "PID: $pid"
        echo "地址: http://${HOST}:${PORT}"
        echo "日志: $LOG_FILE"
        echo "Conda 环境: $CONDA_ENV_PATH"
        echo "Conda 渠道: $CONDA_CHANNELS"
    else
        echo "ℹ️  服务未运行"
        echo "Conda 环境: $CONDA_ENV_PATH"
        echo "Conda 渠道: $CONDA_CHANNELS"
        echo "可执行: ./scripts/start-web.sh start"
    fi
}

logs_service() {
    print_header
    validate_port
    refresh_runtime_paths
    ensure_run_dir

    if [ ! -f "$LOG_FILE" ]; then
        echo "ℹ️  暂无日志文件: $LOG_FILE"
        return
    fi

    echo "📄 实时查看日志: $LOG_FILE"
    tail -n "$TAIL_LINES" -f "$LOG_FILE"
}

run_foreground() {
    prepare_runtime
    echo "🌐 前台启动服务..."
    echo "访问地址: http://${HOST}:${PORT}"
    echo "按 Ctrl+C 停止服务"
    echo ""
    echo "Conda 环境: $CONDA_ENV_PATH"
    echo "Conda 渠道: $CONDA_CHANNELS"

    cd "$PROJECT_DIR"
    exec "$ENV_PYTHON" -m uvicorn web.backend.main:app --host "$HOST" --port "$PORT"
}

restart_service() {
    stop_service
    start_service
}

case "$ACTION" in
    run)
        run_foreground
        ;;
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        status_service
        ;;
    logs)
        logs_service
        ;;
    help)
        usage
        ;;
    *)
        usage
        exit 1
        ;;
esac
