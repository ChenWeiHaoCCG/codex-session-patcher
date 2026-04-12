# -*- coding: utf-8 -*-
"""
CTF configuration status helpers.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

CTF_MARKER = "managed-by: codex-session-patcher:ctf"
DEFAULT_CLAUDE_CTF_WORKSPACE = os.path.expanduser("~/.claude-ctf-workspace")
DEFAULT_OPENCODE_CTF_WORKSPACE = os.path.expanduser("~/.opencode-ctf-workspace")
GLOBAL_MARKER = "# __csp_ctf_global__"

DEFAULT_CODEX_DIR = os.path.expanduser("~/.codex")
DEFAULT_CODEX_CONFIG_PATH = os.path.join(DEFAULT_CODEX_DIR, "config.toml")
DEFAULT_CODEX_PROMPTS_DIR = os.path.join(DEFAULT_CODEX_DIR, "prompts")
DEFAULT_CODEX_PROMPT_FILE = "ctf_optimized.md"
DEFAULT_PATCHER_CONFIG_PATH = os.path.expanduser("~/.codex-patcher/config.json")

_PROFILE_SECTION_RE = re.compile(r"(?ms)^\[profiles\.ctf\]\s*(.*?)(?=^\[|\Z)")
_MODEL_INSTRUCTIONS_RE = re.compile(
    r'^\s*model_instructions_file\s*=\s*["\']([^"\']+)["\']\s*$',
    re.MULTILINE,
)


@dataclass
class CTFStatus:
    """CTF configuration status."""

    # Codex
    installed: bool = False
    config_exists: bool = False
    prompt_exists: bool = False
    profile_available: bool = False
    global_installed: bool = False
    config_path: Optional[str] = None
    prompt_path: Optional[str] = None
    # Claude Code
    claude_installed: bool = False
    claude_workspace_exists: bool = False
    claude_prompt_exists: bool = False
    claude_workspace_path: Optional[str] = None
    claude_prompt_path: Optional[str] = None
    # OpenCode
    opencode_installed: bool = False
    opencode_workspace_exists: bool = False
    opencode_prompt_exists: bool = False
    opencode_workspace_path: Optional[str] = None
    opencode_prompt_path: Optional[str] = None


def _read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _normalize_prompt_path(path_value: str | None) -> Optional[str]:
    if not path_value:
        return None
    return os.path.normpath(os.path.expanduser(path_value.strip()))


def _extract_model_instructions_path(block: str) -> Optional[str]:
    match = _MODEL_INSTRUCTIONS_RE.search(block or "")
    if not match:
        return None
    return _normalize_prompt_path(match.group(1))


def _extract_profile_prompt_path(config_content: str) -> Optional[str]:
    match = _PROFILE_SECTION_RE.search(config_content or "")
    if not match:
        return None
    return _extract_model_instructions_path(match.group(1))


def _extract_global_prompt_path(config_content: str) -> Optional[str]:
    if not config_content or GLOBAL_MARKER not in config_content:
        return None

    lines = config_content.splitlines()
    for index, line in enumerate(lines):
        if GLOBAL_MARKER not in line:
            continue
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("["):
                break
            match = _MODEL_INSTRUCTIONS_RE.match(stripped)
            if match:
                return _normalize_prompt_path(match.group(1))
            break
    return None


def _get_saved_codex_prompt_file(config_path: str = DEFAULT_PATCHER_CONFIG_PATH) -> Optional[str]:
    if not os.path.exists(config_path):
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return None

    prompt_file = config.get("ctf_prompts", {}).get("codex", {}).get("file")
    if not prompt_file:
        return None
    return str(prompt_file).strip()


def get_codex_prompt_path() -> str:
    """
    Resolve the actual Codex prompt path currently in use.

    Priority:
    1. Active profile configuration in ~/.codex/config.toml
    2. Active global configuration in ~/.codex/config.toml
    3. Saved template selection in ~/.codex-patcher/config.json
    4. Built-in default prompt filename
    """

    config_content = _read_text(DEFAULT_CODEX_CONFIG_PATH)

    profile_prompt_path = _extract_profile_prompt_path(config_content)
    if profile_prompt_path:
        return profile_prompt_path

    global_prompt_path = _extract_global_prompt_path(config_content)
    if global_prompt_path:
        return global_prompt_path

    prompt_file = _get_saved_codex_prompt_file() or DEFAULT_CODEX_PROMPT_FILE
    return os.path.join(DEFAULT_CODEX_PROMPTS_DIR, prompt_file)


def check_ctf_status() -> CTFStatus:
    """
    Check CTF configuration status for Codex, Claude Code and OpenCode.
    """

    config_path = DEFAULT_CODEX_CONFIG_PATH
    prompt_path = get_codex_prompt_path()

    status = CTFStatus(
        config_path=config_path,
        prompt_path=prompt_path,
    )

    status.config_exists = os.path.exists(config_path)
    config_content = _read_text(config_path) if status.config_exists else ""
    if config_content:
        status.profile_available = "[profiles.ctf]" in config_content
        status.global_installed = GLOBAL_MARKER in config_content

    status.prompt_exists = bool(prompt_path and os.path.exists(prompt_path))
    status.installed = status.profile_available and status.prompt_exists

    # Claude Code
    workspace_path = DEFAULT_CLAUDE_CTF_WORKSPACE
    claude_prompt_path = os.path.join(workspace_path, ".claude", "CLAUDE.md")

    status.claude_workspace_path = workspace_path
    status.claude_prompt_path = claude_prompt_path
    status.claude_workspace_exists = os.path.isdir(workspace_path)

    if os.path.exists(claude_prompt_path):
        try:
            with open(claude_prompt_path, "r", encoding="utf-8") as f:
                content = f.read(500)
            if CTF_MARKER in content:
                status.claude_prompt_exists = True
        except Exception:
            pass

    status.claude_installed = status.claude_workspace_exists and status.claude_prompt_exists

    # OpenCode
    opencode_workspace = DEFAULT_OPENCODE_CTF_WORKSPACE
    opencode_agents_path = os.path.join(opencode_workspace, "AGENTS.md")

    status.opencode_workspace_path = opencode_workspace
    status.opencode_prompt_path = opencode_agents_path
    status.opencode_workspace_exists = os.path.isdir(opencode_workspace)

    if os.path.exists(opencode_agents_path):
        try:
            with open(opencode_agents_path, "r", encoding="utf-8") as f:
                content = f.read(500)
            if CTF_MARKER in content:
                status.opencode_prompt_exists = True
        except Exception:
            pass

    status.opencode_installed = status.opencode_workspace_exists and status.opencode_prompt_exists

    return status
