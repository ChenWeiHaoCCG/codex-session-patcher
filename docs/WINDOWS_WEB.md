# Windows Web Startup

Use the Windows scripts or the packaged desktop launcher to manage the Web UI.

## Capabilities

- Conda-first startup
- Custom host and port
- Port conflict detection before startup
- Automatic dependency installation
- Automatic frontend build
- `start`, `stop`, `restart`, `status`, and `logs` commands
- PID, state, and log files under `web-logs\`
- Packaged desktop launcher exe for Windows

## Quick Start

PowerShell:

```powershell
.\scripts\start-web.ps1 start
```

Batch wrapper:

```bat
.\scripts\start-web.bat start
```

Desktop launcher:

```bat
dist\codex-patcher-launcher\codex-patcher-launcher.exe
```

## Common Commands

Start with default port:

```powershell
.\scripts\start-web.ps1 start
```

Start with custom port:

```powershell
.\scripts\start-web.ps1 start -Port 9999
```

Start with a specific Conda environment:

```powershell
.\scripts\start-web.ps1 start -CondaEnv codex-patcher -Host 127.0.0.1 -Port 9090
```

Status:

```powershell
.\scripts\start-web.ps1 status -Port 9090
```

Restart:

```powershell
.\scripts\start-web.ps1 restart -Port 9090
```

Stop:

```powershell
.\scripts\start-web.ps1 stop -Port 9090
```

Show logs:

```powershell
.\scripts\start-web.ps1 logs -Port 9090
.\scripts\start-web.ps1 logs -Port 9090 -Follow
```

## Notes

- Default host is `127.0.0.1`
- Default port is `9090`
- Default Conda prefix is `.\.conda\web`
- The launcher creates `.\.conda\web` automatically if missing
- Missing Python web runtime dependencies are installed automatically
- Missing frontend dependencies are installed automatically
- Frontend assets are rebuilt automatically before startup
- The desktop launcher supports custom ports and scrollable startup logs
- The desktop launcher checks occupied ports without showing a visible `powershell.exe` window

## Build

```bat
scripts\build-binary.bat
```

Generated desktop launcher:

```bat
dist\codex-patcher-launcher\codex-patcher-launcher.exe
```
