# Windows Web Startup

Use `scripts/start-web.ps1` to manage the Web UI on Windows.

It provides:

- Conda environment based startup
- Custom host and port
- Port conflict detection before startup
- Automatic frontend build on each `start`
- `start`, `stop`, `restart`, `status`, and `logs` commands
- PID, state, and log files under `web-logs\`

## Quick Start

```powershell
.\scripts\start-web.ps1 start -CondaEnv codex-patcher -Port 8080
```

You can also use the batch wrapper:

```bat
.\scripts\start-web.bat start -CondaEnv codex-patcher -Port 8080
```

## Commands

Start the service:

```powershell
.\scripts\start-web.ps1 start -CondaEnv codex-patcher -Host 127.0.0.1 -Port 8080
```

Check the current status:

```powershell
.\scripts\start-web.ps1 status -Port 8080
```

Restart the service:

```powershell
.\scripts\start-web.ps1 restart -Port 8080
```

Stop the service:

```powershell
.\scripts\start-web.ps1 stop -Port 8080
```

Show logs:

```powershell
.\scripts\start-web.ps1 logs -Port 8080
.\scripts\start-web.ps1 logs -Port 8080 -Follow
```

## Notes

- Default host is `127.0.0.1`.
- Default port is `8080`.
- Default Conda environment is `base`.
- If `web\frontend\node_modules` does not exist, the script runs `npm install` first.
- The script checks that `fastapi` and `uvicorn` are available in the selected Conda environment before startup.
