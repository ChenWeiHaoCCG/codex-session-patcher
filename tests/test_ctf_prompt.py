# -*- coding: utf-8 -*-
"""
CTF 提示词 CRUD 测试
"""
from __future__ import annotations

import json
import os


class TestCTFPromptTemplates:
    """验证模板内容基本正确"""

    def test_codex_template_exists(self):
        from codex_session_patcher.ctf_config.templates import SECURITY_MODE_PROMPT
        assert 'CTF' in SECURITY_MODE_PROMPT
        assert len(SECURITY_MODE_PROMPT) > 100

    def test_claude_template_exists(self):
        from codex_session_patcher.ctf_config.templates import CLAUDE_CODE_SECURITY_MODE_PROMPT
        assert 'managed-by: codex-session-patcher:ctf' in CLAUDE_CODE_SECURITY_MODE_PROMPT

    def test_opencode_template_exists(self):
        from codex_session_patcher.ctf_config.templates import OPENCODE_SECURITY_MODE_PROMPT
        assert 'managed-by: codex-session-patcher:ctf' in OPENCODE_SECURITY_MODE_PROMPT
        assert '# Security Testing Mode' in OPENCODE_SECURITY_MODE_PROMPT

    def test_opencode_config_is_valid_json(self):
        from codex_session_patcher.ctf_config.templates import OPENCODE_CTF_CONFIG
        data = json.loads(OPENCODE_CTF_CONFIG)
        assert 'instructions' in data
        assert 'AGENTS.md' in data['instructions']

    def test_opencode_readme_exists(self):
        from codex_session_patcher.ctf_config.templates import OPENCODE_CTF_README
        assert 'opencode' in OPENCODE_CTF_README.lower()
        assert 'codex-patcher' in OPENCODE_CTF_README


class TestCustomPromptParameter:
    """验证 install() 方法的 custom_prompt 参数"""

    def test_codex_installer_accepts_custom_prompt(self, tmp_path):
        from codex_session_patcher.ctf_config.installer import CTFConfigInstaller

        installer = CTFConfigInstaller()
        installer.codex_dir = str(tmp_path / ".codex")
        installer.config_path = os.path.join(installer.codex_dir, "config.toml")
        installer.prompts_dir = os.path.join(installer.codex_dir, "prompts")
        installer.prompt_path = os.path.join(installer.prompts_dir, "security_mode.md")

        custom = "# My Custom Codex Prompt"
        success, _ = installer.install(custom_prompt=custom)
        assert success

        with open(installer.prompt_path, 'r') as f:
            content = f.read()
        assert content == custom

    def test_codex_installer_uses_default_without_custom(self, tmp_path):
        from codex_session_patcher.ctf_config.installer import CTFConfigInstaller
        from codex_session_patcher.ctf_config.templates import BUILTIN_TEMPLATES

        installer = CTFConfigInstaller()
        installer.codex_dir = str(tmp_path / ".codex")
        installer.config_path = os.path.join(installer.codex_dir, "config.toml")
        installer.prompts_dir = os.path.join(installer.codex_dir, "prompts")

        success, _ = installer.install()
        assert success

        with open(installer.prompt_path, 'r') as f:
            content = f.read()
        assert content == BUILTIN_TEMPLATES['codex'][0]['prompt']

    def test_claude_installer_accepts_custom_prompt(self, tmp_path):
        from codex_session_patcher.ctf_config.installer import ClaudeCodeCTFInstaller

        installer = ClaudeCodeCTFInstaller()
        installer.workspace_dir = str(tmp_path / "claude-ctf")
        installer.claude_dir = os.path.join(installer.workspace_dir, ".claude")
        installer.prompt_path = os.path.join(installer.claude_dir, "CLAUDE.md")
        installer.readme_path = os.path.join(installer.workspace_dir, "README.md")

        custom = "# My Custom Claude Prompt"
        success, _ = installer.install(custom_prompt=custom)
        assert success

        with open(installer.prompt_path, 'r') as f:
            content = f.read()
        assert content == custom


class TestCTFStatus:
    """验证 CTF status 结构和动态 prompt 路径解析"""

    def test_status_has_opencode_fields(self):
        from codex_session_patcher.ctf_config.status import CTFStatus
        status = CTFStatus()
        assert hasattr(status, 'opencode_installed')
        assert hasattr(status, 'opencode_workspace_exists')
        assert hasattr(status, 'opencode_prompt_exists')
        assert hasattr(status, 'opencode_workspace_path')
        assert hasattr(status, 'opencode_prompt_path')
        assert status.opencode_installed is False

    def test_status_detects_profile_prompt_file_from_config(self, tmp_path, monkeypatch):
        from codex_session_patcher.ctf_config import status as status_module

        home = tmp_path
        codex_dir = home / ".codex"
        prompts_dir = codex_dir / "prompts"
        prompt_path = prompts_dir / "ctf_optimized.md"
        config_path = codex_dir / "config.toml"

        prompts_dir.mkdir(parents=True)
        prompt_path.write_text("# custom prompt", encoding="utf-8")
        config_path.write_text(
            '[profiles.ctf]\nmodel_instructions_file = "~/.codex/prompts/ctf_optimized.md"\n',
            encoding="utf-8",
        )

        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setattr(status_module, "DEFAULT_CODEX_DIR", str(codex_dir))
        monkeypatch.setattr(status_module, "DEFAULT_CODEX_CONFIG_PATH", str(config_path))
        monkeypatch.setattr(status_module, "DEFAULT_CODEX_PROMPTS_DIR", str(prompts_dir))
        monkeypatch.setattr(
            status_module,
            "DEFAULT_PATCHER_CONFIG_PATH",
            str(home / ".codex-patcher" / "config.json"),
        )

        status = status_module.check_ctf_status()

        assert status.profile_available is True
        assert status.prompt_exists is True
        assert status.installed is True
        assert status.prompt_path == os.path.normpath(str(prompt_path))

    def test_get_codex_prompt_path_falls_back_to_saved_template_file(self, tmp_path, monkeypatch):
        from codex_session_patcher.ctf_config import status as status_module

        home = tmp_path
        codex_dir = home / ".codex"
        prompts_dir = codex_dir / "prompts"
        patcher_config_path = home / ".codex-patcher" / "config.json"
        patcher_config_path.parent.mkdir(parents=True)
        patcher_config_path.write_text(
            json.dumps(
                {
                    "ctf_prompts": {
                        "codex": {
                            "file": "ctf_private_deploy.md",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(status_module, "DEFAULT_CODEX_DIR", str(codex_dir))
        monkeypatch.setattr(status_module, "DEFAULT_CODEX_CONFIG_PATH", str(codex_dir / "config.toml"))
        monkeypatch.setattr(status_module, "DEFAULT_CODEX_PROMPTS_DIR", str(prompts_dir))
        monkeypatch.setattr(status_module, "DEFAULT_PATCHER_CONFIG_PATH", str(patcher_config_path))

        prompt_path = status_module.get_codex_prompt_path()

        assert prompt_path == os.path.join(str(prompts_dir), "ctf_private_deploy.md")
