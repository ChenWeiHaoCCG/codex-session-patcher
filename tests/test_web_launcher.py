from __future__ import annotations

from pathlib import Path

from codex_session_patcher.web_launcher import (
    LauncherConfig,
    WEB_RUNTIME_REQUIREMENTS,
    free_port,
    install_python_web_dependencies,
    launcher_log_path_for_port,
    parse_cli_args,
    resolve_python_selection,
)


def test_parse_cli_args_accepts_legacy_powershell_flags():
    config = parse_cli_args(
        [
            "start",
            "-CondaEnv",
            "codex-patcher",
            "-Host",
            "127.0.0.1",
            "-Port",
            "9090",
            "-SkipFrontendBuild",
            "-Follow",
            "-LogTailLines",
            "120",
        ]
    )

    assert config.action == "start"
    assert config.conda_env == "codex-patcher"
    assert config.host == "127.0.0.1"
    assert config.port == 9090
    assert config.build_frontend is False
    assert config.follow is True
    assert config.log_tail_lines == 120


def test_parse_cli_args_accepts_shell_conda_prefix_options():
    config = parse_cli_args(
        [
            "start",
            "--conda-env-path",
            "./.conda/web",
            "--python-version",
            "3.11",
            "--conda-channel",
            "conda-forge,defaults",
            "--no-install",
        ]
    )

    assert config.conda_env_path == "./.conda/web"
    assert config.python_version == "3.11"
    assert config.conda_channels == ["conda-forge", "defaults"]
    assert config.auto_install is False


def test_launcher_defaults_to_project_conda_prefix():
    config = LauncherConfig()
    assert config.port == 9090
    assert Path(config.conda_env_path).as_posix().endswith("/.conda/web")


def test_resolve_python_selection_requires_conda(monkeypatch):
    monkeypatch.delenv("CONDA_EXE", raising=False)
    monkeypatch.setattr("codex_session_patcher.web_launcher.shutil.which", lambda _: None)
    monkeypatch.setattr("codex_session_patcher.web_launcher.Path.home", lambda: Path("Z:/no-conda-home"))

    config = LauncherConfig(conda_env_path="./.conda/web")

    try:
        resolve_python_selection(config)
    except RuntimeError as exc:
        assert "Conda was not found" in str(exc)
    else:
        raise AssertionError("resolve_python_selection should require Conda")


def test_install_python_web_dependencies_avoids_editable_install(monkeypatch):
    commands = []

    def fake_run_command(args, *, cwd=None, check=True):
        commands.append((list(args), cwd, check))
        return None

    monkeypatch.setattr("codex_session_patcher.web_launcher.run_command", fake_run_command)

    install_python_web_dependencies("python")

    assert len(commands) == 3
    assert commands[0][0][:5] == ["python", "-m", "pip", "install", "--disable-pip-version-check"]
    assert commands[1][0][:5] == ["python", "-m", "pip", "install", "--disable-pip-version-check"]
    assert commands[2][0] == ["python", "-m", "pip", "check"]
    assert ".[web]" not in " ".join(" ".join(cmd[0]) for cmd in commands)
    for requirement in WEB_RUNTIME_REQUIREMENTS:
        assert requirement in commands[1][0]


def test_free_port_returns_none_when_port_is_free(monkeypatch):
    monkeypatch.setattr("codex_session_patcher.web_launcher.get_port_owner_pid", lambda port: None)
    assert free_port(9090) is None


def test_launcher_log_path_is_port_scoped():
    assert launcher_log_path_for_port(9090).name == "launcher-9090.log"
