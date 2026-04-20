from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "web" / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"
LOG_DIR = PROJECT_ROOT / "web-logs"
DEFAULT_CONDA_PREFIX = PROJECT_ROOT / ".conda" / "web"

ACTION_NAMES = {"run", "start", "stop", "restart", "status", "logs", "help"}
PYTHON_DEPENDENCY_CHECK = (
    "import fastapi, uvicorn, pydantic, websockets, httpx"
)
DEFAULT_CONDA_CHANNELS = ("conda-forge",)
WEB_RUNTIME_REQUIREMENTS = (
    "fastapi>=0.100.0,<1.0.0",
    "uvicorn>=0.23.0,<1.0.0",
    "pydantic>=2.0.0,<3.0.0",
    "websockets>=11.0,<17.0",
    "httpx>=0.24.0,<1.0.0",
)
LATEST_LAUNCHER_LOG_NAME = "launcher-latest.log"


class LauncherError(RuntimeError):
    """Raised when the launcher cannot complete the requested action."""


class TeeStream:
    def __init__(self, *streams: Any):
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


@dataclass
class LauncherConfig:
    action: str = "start"
    host: str = os.environ.get("HOST", "127.0.0.1")
    port: int = int(os.environ.get("PORT", "9090"))
    python: str | None = os.environ.get("PYTHON_EXECUTABLE")
    conda_env: str | None = os.environ.get("CONDA_ENV")
    conda_env_path: str | None = os.environ.get("CONDA_ENV_PATH") or str(DEFAULT_CONDA_PREFIX)
    python_version: str = os.environ.get("CONDA_PYTHON_VERSION", "3.11")
    conda_channels: list[str] = field(
        default_factory=lambda: parse_conda_channels(
            os.environ.get("CONDA_CHANNELS")
        )
    )
    auto_install: bool = os.environ.get("NO_INSTALL", "0") != "1"
    build_frontend: bool = os.environ.get("NO_BUILD", "0") != "1"
    follow: bool = False
    startup_timeout_sec: int = int(os.environ.get("STARTUP_TIMEOUT_SEC", "45"))
    log_tail_lines: int = int(os.environ.get("LOG_TAIL_LINES", "80"))
    explicit: set[str] = field(default_factory=set)


@dataclass
class PythonSelection:
    executable: str
    source: str
    conda_env: str | None = None
    conda_prefix: str | None = None


@dataclass
class CondaTool:
    executable: str
    flavor: str


def parse_conda_channels(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_CONDA_CHANNELS)

    channels = [item.strip() for item in value.replace(",", " ").split() if item.strip()]
    if not channels:
        return list(DEFAULT_CONDA_CHANNELS)
    return channels


def split_inline_option(token: str) -> tuple[str, str | None]:
    if token.startswith("-") and "=" in token:
        name, value = token.split("=", 1)
        return name, value

    if token.startswith("-") and ":" in token:
        name, value = token.split(":", 1)
        return name, value

    return token, None


def parse_int(value: str, option_name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise LauncherError(f"{option_name} must be an integer, got: {value}") from exc


def take_option_value(
    args: Sequence[str], index: int, inline_value: str | None, option_name: str
) -> tuple[str, int]:
    if inline_value is not None:
        return inline_value, index + 1

    next_index = index + 1
    if next_index >= len(args):
        raise LauncherError(f"{option_name} requires a value.")
    return args[next_index], next_index + 1


def parse_cli_args(raw_args: Sequence[str]) -> LauncherConfig:
    config = LauncherConfig()
    args = list(raw_args)

    if args and args[0] in ACTION_NAMES:
        config.action = args[0]
        args = args[1:]
    elif args and args[0] in {"-h", "--help"}:
        config.action = "help"
        args = args[1:]

    conda_channels_explicit = False
    index = 0

    while index < len(args):
        token = args[index]

        if token in {"-h", "--help"}:
            config.action = "help"
            return config

        if token.isdigit():
            config.port = parse_int(token, "port")
            config.explicit.add("port")
            index += 1
            continue

        option_name, inline_value = split_inline_option(token)

        if option_name in {"--host", "-Host"}:
            value, index = take_option_value(args, index, inline_value, option_name)
            config.host = value
            config.explicit.add("host")
            continue

        if option_name in {"--port", "-Port"}:
            value, index = take_option_value(args, index, inline_value, option_name)
            config.port = parse_int(value, option_name)
            config.explicit.add("port")
            continue

        if option_name in {"--python", "--python-executable", "-Python", "-PythonExecutable"}:
            value, index = take_option_value(args, index, inline_value, option_name)
            config.python = value
            config.explicit.add("python")
            continue

        if option_name in {"--conda-env", "-CondaEnv"}:
            value, index = take_option_value(args, index, inline_value, option_name)
            config.conda_env = value
            config.explicit.add("conda_env")
            continue

        if option_name == "--conda-env-path":
            value, index = take_option_value(args, index, inline_value, option_name)
            config.conda_env_path = value
            config.explicit.add("conda_env_path")
            continue

        if option_name == "--python-version":
            value, index = take_option_value(args, index, inline_value, option_name)
            config.python_version = value
            config.explicit.add("python_version")
            continue

        if option_name == "--conda-channel":
            value, index = take_option_value(args, index, inline_value, option_name)
            if not conda_channels_explicit:
                config.conda_channels = []
                conda_channels_explicit = True
            config.conda_channels.extend(parse_conda_channels(value))
            config.explicit.add("conda_channels")
            continue

        if option_name in {"--startup-timeout", "-StartupTimeoutSec"}:
            value, index = take_option_value(args, index, inline_value, option_name)
            config.startup_timeout_sec = parse_int(value, option_name)
            config.explicit.add("startup_timeout_sec")
            continue

        if option_name in {"--log-tail", "--tail", "-LogTailLines"}:
            value, index = take_option_value(args, index, inline_value, option_name)
            config.log_tail_lines = parse_int(value, option_name)
            config.explicit.add("log_tail_lines")
            continue

        if option_name in {"--follow", "-Follow"}:
            config.follow = True
            config.explicit.add("follow")
            index += 1
            continue

        if option_name in {"--no-install"}:
            config.auto_install = False
            config.explicit.add("auto_install")
            index += 1
            continue

        if option_name in {"--no-build", "--skip-build", "-SkipFrontendBuild"}:
            config.build_frontend = False
            config.explicit.add("build_frontend")
            index += 1
            continue

        if option_name in {"--install-python-deps", "-InstallPythonDeps"}:
            config.auto_install = True
            config.explicit.add("auto_install")
            index += 1
            continue

        raise LauncherError(f"Unknown argument: {token}")

    return config


def resolve_command(command: str) -> str | None:
    expanded = os.path.expanduser(command)
    if os.path.exists(expanded):
        return str(Path(expanded).resolve())

    return shutil.which(command)


def resolve_python_binary_from_prefix(prefix: str | os.PathLike[str]) -> str:
    prefix_path = Path(prefix)
    if os.name == "nt":
        candidate = prefix_path / "python.exe"
    else:
        candidate = prefix_path / "bin" / "python"
    return str(candidate)


def find_conda_tool() -> CondaTool | None:
    conda_exe = os.environ.get("CONDA_EXE")
    if conda_exe and Path(conda_exe).exists():
        flavor = "micromamba" if "micromamba" in Path(conda_exe).name.lower() else "conda"
        return CondaTool(executable=conda_exe, flavor=flavor)

    for candidate in ("conda", "conda.exe", "conda.bat", "mamba", "mamba.exe", "mamba.bat", "micromamba", "micromamba.exe", "micromamba.bat"):
        resolved = shutil.which(candidate)
        if resolved:
            name = Path(resolved).name.lower()
            flavor = "micromamba" if "micromamba" in name else "conda"
            return CondaTool(executable=resolved, flavor=flavor)

    home = Path.home()
    if os.name == "nt":
        extra_candidates = (
            home / "miniconda3" / "Scripts" / "conda.exe",
            home / "anaconda3" / "Scripts" / "conda.exe",
            home / "mambaforge" / "Scripts" / "conda.exe",
            Path("C:/ProgramData/miniconda3/Scripts/conda.exe"),
            Path("C:/ProgramData/anaconda3/Scripts/conda.exe"),
            home / ".codegeex" / "mamba" / "condabin" / "micromamba.bat",
        )
    else:
        extra_candidates = (
            home / "miniconda3" / "bin" / "conda",
            home / "anaconda3" / "bin" / "conda",
            home / "mambaforge" / "bin" / "conda",
            Path("/opt/conda/bin/conda"),
            Path("/usr/local/miniconda3/bin/conda"),
        )

    for candidate in extra_candidates:
        if candidate.exists():
            name = candidate.name.lower()
            flavor = "micromamba" if "micromamba" in name else "conda"
            return CondaTool(executable=str(candidate), flavor=flavor)

    return None


def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        joined = " ".join(args)
        raise LauncherError(f"Command failed with exit code {completed.returncode}: {joined}")
    return completed


def ensure_pip(python_executable: str, *, auto_install: bool) -> None:
    pip_check = subprocess.run(
        [python_executable, "-m", "pip", "--version"],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if pip_check.returncode == 0:
        return

    if not auto_install:
        raise LauncherError(
            f"pip is not available in {python_executable}. Re-run without --no-install."
        )

    run_command([python_executable, "-m", "ensurepip", "--upgrade"])


def get_conda_environment_entries(conda_tool: CondaTool) -> list[dict[str, str]]:
    result = subprocess.run(
        [conda_tool.executable, "env", "list", "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise LauncherError(
            "Unable to query Conda environments. Check that Conda is installed correctly."
        )

    payload = json.loads(result.stdout or "{}")
    entries: list[dict[str, str]] = []
    for prefix in payload.get("envs", []):
        entries.append(
            {
                "name": Path(prefix).name or prefix,
                "prefix": prefix,
            }
        )
    return entries


def resolve_conda_prefix(conda_tool: CondaTool, environment_name: str) -> str:
    if environment_name.lower() == "base":
        result = subprocess.run(
            [conda_tool.executable, "info", "--base"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    for entry in get_conda_environment_entries(conda_tool):
        if entry["name"].lower() == environment_name.lower():
            return entry["prefix"]

    raise LauncherError(f"Conda environment '{environment_name}' was not found.")


def ensure_conda_env_path(
    config: LauncherConfig, conda_tool: CondaTool, env_path: str
) -> PythonSelection:
    python_executable = resolve_python_binary_from_prefix(env_path)
    if Path(python_executable).exists():
        return PythonSelection(
            executable=python_executable,
            source=f"conda prefix {env_path}",
            conda_env=Path(env_path).name,
            conda_prefix=str(Path(env_path).resolve()),
        )

    if not config.auto_install:
        raise LauncherError(
            f"Conda environment path does not exist: {env_path}. Re-run without --no-install."
        )

    channel_args: list[str] = ["--override-channels"]
    for channel in config.conda_channels or list(DEFAULT_CONDA_CHANNELS):
        channel_args.extend(["-c", channel])

    run_command(
        [
            conda_tool.executable,
            "create",
            "-y",
            "-p",
            env_path,
            *channel_args,
            f"python={config.python_version}",
            "pip",
        ]
    )

    if not Path(python_executable).exists():
        raise LauncherError(f"python was not created in Conda environment: {env_path}")

    return PythonSelection(
        executable=python_executable,
        source=f"conda prefix {env_path}",
        conda_env=Path(env_path).name,
        conda_prefix=str(Path(env_path).resolve()),
    )


def resolve_python_selection(config: LauncherConfig) -> PythonSelection:
    if config.python:
        resolved = resolve_command(config.python)
        if not resolved:
            raise LauncherError(f"Python executable was not found: {config.python}")
        return PythonSelection(executable=resolved, source="explicit python")

    if config.conda_env:
        conda_tool = find_conda_tool()
        if not conda_tool:
            raise LauncherError(
                f"Conda was not found, so the requested environment '{config.conda_env}' "
                "cannot be used."
            )
        prefix = resolve_conda_prefix(conda_tool, config.conda_env)
        python_executable = resolve_python_binary_from_prefix(prefix)
        if not Path(python_executable).exists():
            raise LauncherError(
                f"python was not found in Conda environment '{config.conda_env}'."
            )
        return PythonSelection(
            executable=python_executable,
            source=f"conda env {config.conda_env}",
            conda_env=config.conda_env,
            conda_prefix=prefix,
        )

    conda_tool = find_conda_tool()
    if not conda_tool:
        raise LauncherError(
            "Conda was not found. Install Conda first or set CONDA_EXE to the conda executable."
        )

    assert config.conda_env_path is not None
    return ensure_conda_env_path(config, conda_tool, config.conda_env_path)


def has_python_web_dependencies(python_executable: str) -> bool:
    result = subprocess.run(
        [python_executable, "-c", PYTHON_DEPENDENCY_CHECK],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def install_python_web_dependencies(python_executable: str) -> None:
    run_command(
        [
            python_executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ],
        cwd=PROJECT_ROOT,
    )
    run_command(
        [
            python_executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            "--upgrade",
            "--upgrade-strategy",
            "eager",
            *WEB_RUNTIME_REQUIREMENTS,
        ],
        cwd=PROJECT_ROOT,
    )
    run_command(
        [
            python_executable,
            "-m",
            "pip",
            "check",
        ],
        cwd=PROJECT_ROOT,
    )


def resolve_node_command() -> str:
    resolved = shutil.which("node")
    if not resolved:
        raise LauncherError("Node.js was not found. Install Node.js first.")
    return resolved


def resolve_npm_command() -> str:
    candidates = ("npm.cmd", "npm", "npm.exe") if os.name == "nt" else ("npm",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise LauncherError("npm was not found. Install Node.js first.")


def install_frontend_dependencies(npm_command: str, *, auto_install: bool) -> None:
    node_modules_dir = FRONTEND_DIR / "node_modules"
    if node_modules_dir.exists():
        return

    if not auto_install:
        raise LauncherError(
            "Frontend dependencies are missing. Re-run without --no-install."
        )

    run_command([npm_command, "install"], cwd=FRONTEND_DIR)


def build_frontend_assets(npm_command: str, *, build_frontend: bool) -> None:
    if build_frontend:
        run_command([npm_command, "run", "build"], cwd=FRONTEND_DIR)

    if not FRONTEND_INDEX_FILE.exists():
        raise LauncherError(
            f"Frontend build output is missing: {FRONTEND_INDEX_FILE}. "
            "Run npm install and npm run build in web/frontend."
        )


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def state_file_for_port(port: int) -> Path:
    return LOG_DIR / f"web-{port}.state.json"


def launcher_log_path_for_port(port: int) -> Path:
    return LOG_DIR / f"launcher-{port}.log"


def install_launcher_logging(port: int) -> tuple[Path, Any]:
    ensure_directory(LOG_DIR)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"launcher-{port}-{timestamp}.log"
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_handle.write(f"\n===== launcher start {timestamp} =====\n")
    log_handle.flush()
    sys.stdout = TeeStream(sys.stdout, log_handle)
    sys.stderr = TeeStream(sys.stderr, log_handle)
    latest_path = LOG_DIR / LATEST_LAUNCHER_LOG_NAME
    try:
        latest_path.write_text(str(log_path), encoding="utf-8")
    except OSError:
        pass
    return log_path, log_handle


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LauncherError(f"Failed to read state file: {path}") from exc


def save_state(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def remove_state(path: Path) -> None:
    if path.exists():
        path.unlink()


def get_state_pid(state: dict[str, Any] | None) -> int | None:
    if not state:
        return None

    value = state.get("pid")
    if value is None:
        value = state.get("launcherPid")
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_state_host(state: dict[str, Any] | None, fallback: str) -> str:
    if not state:
        return fallback
    return str(state.get("bindHost") or state.get("host") or fallback)


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        import ctypes

        process_handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process_handle:
            return False
        ctypes.windll.kernel32.CloseHandle(process_handle)
        return True

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_pid(pid: int, *, force: bool = False) -> None:
    if os.name == "nt":
        sig = signal.SIGTERM
    else:
        sig = signal.SIGKILL if force and hasattr(signal, "SIGKILL") else signal.SIGTERM
    os.kill(pid, sig)


def probe_host(requested_host: str) -> str:
    if not requested_host or requested_host in {"0.0.0.0", "::", "[::]", "*"}:
        return "127.0.0.1"
    return requested_host


def can_connect(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.75):
            return True
    except OSError:
        return False


def get_port_owner_pid(port: int) -> int | None:
    if os.name == "nt":
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-NetTCPConnection -LocalPort "
                    f"{port} -State Listen -ErrorAction SilentlyContinue | "
                    "Select-Object -First 1 -ExpandProperty OwningProcess"
                ),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        output = (result.stdout or "").strip()
        if output.isdigit():
            return int(output)
    else:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        output = (result.stdout or "").strip().splitlines()
        if output and output[0].isdigit():
            return int(output[0])
    return None


def free_port(port: int, *, preferred_pid: int | None = None) -> int | None:
    pid_to_stop = preferred_pid
    if pid_to_stop is None:
        pid_to_stop = get_port_owner_pid(port)

    if pid_to_stop is None:
        return None

    try:
        terminate_pid(pid_to_stop, force=False)
    except OSError:
        pass

    deadline = time.time() + 8
    while time.time() < deadline:
        if not is_process_running(pid_to_stop):
            return pid_to_stop
        if get_port_owner_pid(port) != pid_to_stop:
            return pid_to_stop
        time.sleep(0.4)

    try:
        terminate_pid(pid_to_stop, force=True)
    except OSError:
        pass

    time.sleep(1)
    if is_process_running(pid_to_stop) and get_port_owner_pid(port) == pid_to_stop:
        raise LauncherError(f"Failed to stop process {pid_to_stop} occupying port {port}.")

    return pid_to_stop


def service_endpoint_ready(host: str, port: int) -> bool:
    url = f"http://{probe_host(host)}:{port}/api/settings"
    try:
        with urlopen(url, timeout=3) as response:
            return 200 <= response.status < 500
    except HTTPError:
        return True
    except URLError:
        return False


def wait_for_service_ready(host: str, port: int, pid: int, timeout_sec: int) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if service_endpoint_ready(host, port):
            return True
        if not is_process_running(pid):
            return False
        time.sleep(0.7)
    return service_endpoint_ready(host, port)


def read_tail(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, maxlen=lines))


def show_recent_logs(stdout_path: Path | None, stderr_path: Path | None, lines: int) -> None:
    if stdout_path and stdout_path.exists():
        print("\n=== Recent Stdout ===")
        for line in read_tail(stdout_path, lines):
            print(line, end="")

    if stderr_path and stderr_path.exists():
        print("\n=== Recent Stderr ===")
        for line in read_tail(stderr_path, lines):
            print(line, end="")


def print_service_status(
    state: dict[str, Any] | None,
    *,
    host: str,
    port: int,
) -> int:
    print("\n=== Service Status ===")

    state_pid = get_state_pid(state)
    state_host = get_state_host(state, host)
    port_in_use = can_connect(probe_host(state_host), port)
    ready = service_endpoint_ready(state_host, port)

    if state and state_pid and is_process_running(state_pid) and ready:
        print("State    : RUNNING")
        print(f"URL      : http://{state_host}:{port}")
        print(f"PID      : {state_pid}")
        if state.get("pythonExecutable"):
            print(f"Python   : {state['pythonExecutable']}")
        if state.get("condaEnv"):
            print(f"Conda    : {state['condaEnv']}")
        print(f"Stdout   : {state.get('stdoutLog', '-')}")
        print(f"Stderr   : {state.get('stderrLog', '-')}")
        return 0

    if state and state_pid and is_process_running(state_pid):
        print("State    : STARTED BUT NOT READY")
        print(f"PID      : {state_pid}")
        print(f"Stdout   : {state.get('stdoutLog', '-')}")
        print(f"Stderr   : {state.get('stderrLog', '-')}")
        return 1

    if state and state_pid and not is_process_running(state_pid):
        print("State    : STOPPED (STALE STATE FILE)")
        print(f"Port     : {port}")
        print(f"Last PID : {state_pid}")
        print(f"Stdout   : {state.get('stdoutLog', '-')}")
        print(f"Stderr   : {state.get('stderrLog', '-')}")
        return 1

    if port_in_use:
        print("State    : PORT IN USE BY ANOTHER PROCESS")
        print(f"Port     : {port}")
        print(f"URL      : http://{state_host}:{port}")
        return 1

    print("State    : STOPPED")
    print(f"Port     : {port}")
    return 0


def merge_restart_defaults(config: LauncherConfig, state: dict[str, Any] | None) -> LauncherConfig:
    if not state:
        return config

    if "host" not in config.explicit:
        config.host = get_state_host(state, config.host)

    if "python" not in config.explicit and state.get("pythonExecutable"):
        config.python = str(state["pythonExecutable"])

    if "conda_env" not in config.explicit and state.get("condaEnv"):
        config.conda_env = str(state["condaEnv"])

    if "conda_env_path" not in config.explicit and state.get("condaPrefix"):
        config.conda_env_path = str(state["condaPrefix"])

    return config


def prepare_runtime(config: LauncherConfig) -> tuple[PythonSelection, str]:
    ensure_directory(LOG_DIR)

    print("\n=== Codex Session Patcher Web UI ===")
    print("[1/6] Resolving Python runtime")
    python_selection = resolve_python_selection(config)
    print(f"      Using {python_selection.executable} ({python_selection.source})")

    print("[2/6] Checking Python package manager")
    ensure_pip(python_selection.executable, auto_install=config.auto_install)

    print("[3/6] Checking Python web dependencies")
    if not has_python_web_dependencies(python_selection.executable):
        if not config.auto_install:
            raise LauncherError(
                "Python web dependencies are missing. Re-run without --no-install."
            )
        install_python_web_dependencies(python_selection.executable)

    print("[4/6] Checking Node.js toolchain")
    resolve_node_command()
    npm_command = resolve_npm_command()

    print("[5/6] Checking frontend dependencies")
    install_frontend_dependencies(npm_command, auto_install=config.auto_install)

    print("[6/6] Building frontend assets")
    build_frontend_assets(npm_command, build_frontend=config.build_frontend)

    return python_selection, npm_command


def build_backend_command(config: LauncherConfig, python_executable: str) -> list[str]:
    return [
        python_executable,
        "-m",
        "uvicorn",
        "web.backend.main:app",
        "--host",
        config.host,
        "--port",
        str(config.port),
    ]


def start_service(config: LauncherConfig) -> int:
    ensure_directory(LOG_DIR)
    state_path = state_file_for_port(config.port)
    state = load_state(state_path)

    existing_pid = get_state_pid(state)
    existing_host = get_state_host(state, config.host)
    if state and existing_pid and is_process_running(existing_pid) and service_endpoint_ready(existing_host, config.port):
        print("\n=== Already Running ===")
        print(f"Service is already running at http://{existing_host}:{config.port}")
        print(f"PID      : {existing_pid}")
        return 0

    if state and existing_pid and not is_process_running(existing_pid):
        remove_state(state_path)
        state = None

    stopped_port_pid = None
    if state and existing_pid and is_process_running(existing_pid) and not service_endpoint_ready(existing_host, config.port):
        stopped_port_pid = free_port(config.port, preferred_pid=existing_pid)
        remove_state(state_path)
        state = None

    if can_connect(probe_host(config.host), config.port):
        owner_pid = get_port_owner_pid(config.port)
        stopped_port_pid = free_port(config.port, preferred_pid=owner_pid)
        if state and stopped_port_pid == existing_pid:
            remove_state(state_path)
            state = None

    python_selection, _ = prepare_runtime(config)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stdout_path = LOG_DIR / f"web-{config.port}-{timestamp}.out.log"
    stderr_path = LOG_DIR / f"web-{config.port}-{timestamp}.err.log"

    print(f"\nStarting backend on http://{config.host}:{config.port}")
    if stopped_port_pid is not None:
        print(f"Released port {config.port} by stopping PID {stopped_port_pid}")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        process = subprocess.Popen(
            build_backend_command(config, python_selection.executable),
            cwd=str(PROJECT_ROOT),
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
            creationflags=creationflags,
        )

    ready = wait_for_service_ready(
        config.host, config.port, process.pid, config.startup_timeout_sec
    )
    if not ready:
        if is_process_running(process.pid):
            try:
                terminate_pid(process.pid, force=True)
            except OSError:
                pass
        remove_state(state_path)
        print("\n=== Startup Failed ===")
        show_recent_logs(stdout_path, stderr_path, 40)
        raise LauncherError(
            f"The web service did not become ready on port {config.port} within "
            f"{config.startup_timeout_sec} seconds."
        )

    state_payload = {
        "bindHost": config.host,
        "port": config.port,
        "pid": process.pid,
        "launcherPid": process.pid,
        "pythonExecutable": python_selection.executable,
        "condaEnv": python_selection.conda_env,
        "condaPrefix": python_selection.conda_prefix,
        "stdoutLog": str(stdout_path),
        "stderrLog": str(stderr_path),
        "startedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state_path, state_payload)

    print("\n=== Started ===")
    print(f"URL      : http://{config.host}:{config.port}")
    print(f"PID      : {process.pid}")
    print(f"Python   : {python_selection.executable}")
    if python_selection.conda_env:
        print(f"Conda    : {python_selection.conda_env}")
    print(f"Stdout   : {stdout_path}")
    print(f"Stderr   : {stderr_path}")
    print(f"State    : {state_path}")
    return 0


def stop_service(config: LauncherConfig) -> int:
    state_path = state_file_for_port(config.port)
    state = load_state(state_path)

    print("\n=== Stopping Service ===")

    if not state:
        if can_connect(probe_host(config.host), config.port):
            print(
                f"Port {config.port} is in use, but it is not managed by this script."
            )
            return 1
        print(f"No managed service is running on port {config.port}.")
        return 0

    state_pid = get_state_pid(state)
    if not state_pid or not is_process_running(state_pid):
        remove_state(state_path)
        print(f"Removed stale state file for port {config.port}.")
        return 0

    try:
        terminate_pid(state_pid, force=False)
    except OSError:
        pass

    deadline = time.time() + 10
    while time.time() < deadline:
        port_owner = get_port_owner_pid(config.port)
        if not is_process_running(state_pid) or port_owner != state_pid:
            remove_state(state_path)
            print(f"Stopped managed service on port {config.port}.")
            return 0
        time.sleep(0.5)

    try:
        terminate_pid(state_pid, force=True)
    except OSError:
        pass

    time.sleep(1)
    port_owner = get_port_owner_pid(config.port)
    if is_process_running(state_pid) and port_owner == state_pid:
        print(f"Managed service PID {state_pid} did not stop cleanly.")
        return 1

    remove_state(state_path)
    print(f"Stopped managed service on port {config.port}.")
    return 0


def restart_service(config: LauncherConfig) -> int:
    state = load_state(state_file_for_port(config.port))
    config = merge_restart_defaults(config, state)
    stop_service(config)
    return start_service(config)


def status_service(config: LauncherConfig) -> int:
    state = load_state(state_file_for_port(config.port))
    host = get_state_host(state, config.host)
    return print_service_status(state, host=host, port=config.port)


def print_log_tail(path: Path, title: str, lines: int) -> None:
    if not path.exists():
        return

    print(f"\n=== {title} ===")
    for line in read_tail(path, lines):
        print(line, end="")


def follow_log_file(path: Path, lines: int) -> None:
    print_log_tail(path, "Stdout", lines)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        while True:
            line = handle.readline()
            if line:
                print(line, end="")
            else:
                time.sleep(0.5)


def logs_service(config: LauncherConfig) -> int:
    state = load_state(state_file_for_port(config.port))
    if not state:
        raise LauncherError(
            f"No managed service state file was found for port {config.port}."
        )

    stdout_path = Path(state["stdoutLog"]) if state.get("stdoutLog") else None
    stderr_path = Path(state["stderrLog"]) if state.get("stderrLog") else None

    if stdout_path:
        if config.follow:
            if stderr_path and stderr_path.exists():
                print_log_tail(stderr_path, "Stderr", config.log_tail_lines)
            follow_log_file(stdout_path, config.log_tail_lines)
            return 0
        print_log_tail(stdout_path, "Stdout", config.log_tail_lines)

    if stderr_path:
        print_log_tail(stderr_path, "Stderr", config.log_tail_lines)

    return 0


def run_foreground(config: LauncherConfig) -> int:
    python_selection, _ = prepare_runtime(config)
    print("\n=== Running Foreground Service ===")
    print(f"URL      : http://{config.host}:{config.port}")
    print("Stop     : Ctrl+C")
    return subprocess.call(
        build_backend_command(config, python_selection.executable),
        cwd=str(PROJECT_ROOT),
    )


def help_text() -> str:
    return """Codex Session Patcher Web UI launcher

Usage:
  scripts/start-web.[bat|ps1|sh] [start|stop|restart|status|logs|run] [options]

Common options:
  --host <host>                 Bind host (default: 127.0.0.1)
  --port <port>                 Bind port (default: 9090)
  --python <python>             Explicit Python executable to use
  --conda-env <name>            Existing Conda environment name
  --conda-env-path <path>       Conda prefix path; default: ./.conda/web
  --python-version <version>    Python version when creating a Conda prefix
  --conda-channel <channel>     Conda channel(s), comma-separated or repeated
  --no-install                  Do not auto-install missing dependencies
  --skip-build                  Do not run the frontend build step
  --log-tail <lines>            Lines to show for logs (default: 80)
  --follow                      Follow stdout in logs mode

Compatibility aliases:
  -Host / -Port / -CondaEnv / -StartupTimeoutSec / -LogTailLines
  -SkipFrontendBuild / -InstallPythonDeps / -Follow

Examples:
  scripts/start-web.bat start
  scripts/start-web.bat start -Port 9090
  scripts/start-web.bat start -Port 9999
  scripts/start-web.ps1 restart -CondaEnv myenv -Port 9090
  ./scripts/start-web.sh run --host 0.0.0.0 --port 9090
  ./scripts/start-web.sh start --conda-env-path ./.conda/web --conda-channel conda-forge
"""


def dispatch(config: LauncherConfig) -> int:
    if config.action == "help":
        print(help_text())
        return 0
    if config.action == "run":
        return run_foreground(config)
    if config.action == "start":
        return start_service(config)
    if config.action == "stop":
        return stop_service(config)
    if config.action == "restart":
        return restart_service(config)
    if config.action == "status":
        return status_service(config)
    if config.action == "logs":
        return logs_service(config)
    raise LauncherError(f"Unsupported action: {config.action}")


def main(argv: Sequence[str] | None = None) -> int:
    log_handle = None
    log_path = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    try:
        config = parse_cli_args(argv or sys.argv[1:])
        log_path, log_handle = install_launcher_logging(config.port)
        return dispatch(config)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except LauncherError as exc:
        print(str(exc), file=sys.stderr)
        if log_path is not None:
            print(f"Launcher log: {log_path}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected launcher failure: {exc}", file=sys.stderr)
        if log_path is not None:
            print(f"Launcher log: {log_path}", file=sys.stderr)
        return 1
    finally:
        if log_handle is not None:
            try:
                sys.stdout = original_stdout
                sys.stderr = original_stderr
                log_handle.flush()
                log_handle.close()
            except OSError:
                pass


def console_main() -> None:
    raise SystemExit(main())
