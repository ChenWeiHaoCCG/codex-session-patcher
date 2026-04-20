from __future__ import annotations

from codex_session_patcher import desktop_launcher


def test_desktop_launcher_default_port():
    assert desktop_launcher.DEFAULT_PORT == 9090


def test_desktop_launcher_uses_local_port_lookup():
    assert hasattr(desktop_launcher, "get_port_owner_pid_local")
