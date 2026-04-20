<div align="center">

# Codex Session Patcher

**AI Coding Session Cleaner & CTF/Pentest Prompt Injection Tool**

Supports **Codex CLI**, **Claude Code**, and **OpenCode**

[简体中文](./README.md) | English

</div>

---

## What Is This?

AI coding tools such as Codex, Claude Code, and OpenCode often refuse security-related requests in CTF, pentest, and research scenarios, which breaks workflow continuity.

Codex Session Patcher provides two groups of capabilities:

1. Session cleaning
Replace refusal responses in existing sessions so you can continue from the same conversation.

2. CTF prompt injection
Inject security-testing context into supported tools to reduce future refusals.

---

## Features

### Session Cleaning

- Smart refusal detection with low false positive rate
- AI-assisted rewrite for refusal responses
- Batch cleaning for all refusals in a session
- Reasoning block removal
- Backup and restore support
- Diff preview before applying changes

### CTF / Pentest Prompt Injection

- Codex profile mode
- Codex global mode
- Claude Code dedicated workspace mode
- OpenCode dedicated workspace mode
- Custom prompts in Web UI
- AI prompt rewrite based on injected context

### Web UI

- Session list with filters and grouping
- Visual cleaning workflow
- Chinese / English interface
- Real-time logs over WebSocket
- Windows desktop launcher exe with custom port and startup log panel

---

## Installation

```bash
git clone https://github.com/ryfineZ/codex-session-patcher.git
cd codex-session-patcher

# CLI only
pip install -e .

# Web UI
pip install -e ".[web]"
cd web/frontend && npm install && npm run build && cd ../..
```

---

## Usage

### Web UI

```bash
# Production mode
./scripts/start-web.sh

# Or directly
uvicorn web.backend.main:app --host 0.0.0.0 --port 9090
```

Visit `http://localhost:9090`, or `http://<server-ip>:9090`.

Windows script usage:

```powershell
.\scripts\start-web.bat start
.\scripts\start-web.ps1 start -CondaEnv codex-patcher -Port 9090
.\scripts\start-web.ps1 start -Port 9999
.\scripts\start-web.ps1 status -Port 9090
.\scripts\start-web.ps1 restart -Port 9090
.\scripts\start-web.ps1 stop -Port 9090
```

The launcher now automatically:

- uses Conda with default prefix `./.conda/web`
- creates `./.conda/web` if missing
- installs missing Python web runtime dependencies automatically
- installs missing frontend dependencies with `npm install`
- rebuilds the frontend with `npm run build`
- writes launcher logs under `web-logs`

### Windows Desktop Launcher

```powershell
dist\codex-patcher-launcher\codex-patcher-launcher.exe
```

Desktop launcher features:

- Chinese UI labels and status prompts
- Custom service port input
- Auto-release occupied port before startup
- Detailed startup log panel with scrolling
- One-click browser open after service startup
- No visible `powershell.exe` pop-up during port checks

### Development Mode

```bash
./scripts/dev-web.sh
```

### CLI

```bash
codex-patcher --help
codex-patcher --dry-run --show-content
codex-patcher --latest
codex-patcher --all
codex-patcher --session-dir ~/.codex/sessions --latest
codex-patcher --latest --format claude-code
codex-patcher --latest --format opencode
codex-patcher --latest --no-backup
codex-patcher --web
codex-patcher --web --host 0.0.0.0 --port 9090
```

---

## Build Executables

Windows:

```powershell
scripts\build-binary.bat
```

Cross-platform shell:

```bash
./scripts/build-binary.sh
```

Outputs:

- `dist/codex-patcher/codex-patcher.exe`
- `dist/codex-patcher-launcher/codex-patcher-launcher.exe`

---

## Configuration

CLI and Web UI share:

`~/.codex-patcher/config.json`

---

## License

[MIT License](LICENSE)
