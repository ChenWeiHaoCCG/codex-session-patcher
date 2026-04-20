# Windows 桌面启动器说明

## 功能

桌面启动器 `codex-patcher-launcher.exe` 提供：

- 中文界面字段名和状态提示
- 自定义服务端口
- 启动前自动检查并释放被占用端口
- 启动日志面板，支持滚动查看
- 启动成功后一键打开浏览器
- 启动过程中不弹出可见的 `powershell.exe` 窗口

## 生成方式

```bat
scripts\build-binary.bat
```

生成物：

```bat
dist\codex-patcher-launcher\codex-patcher-launcher.exe
```

CLI 可执行文件仍然会一并生成：

```bat
dist\codex-patcher\codex-patcher.exe
```

## 使用方式

直接双击：

```bat
dist\codex-patcher-launcher\codex-patcher-launcher.exe
```

或命令行启动：

```bat
dist\codex-patcher-launcher\codex-patcher-launcher.exe --port 9999
```

## 日志说明

桌面启动器界面中的“启动日志”会输出：

- 端口占用释放日志
- 服务启动过程日志
- Uvicorn 启动日志
- 服务停止日志

如果服务成功启动，界面状态会从“启动中”切换到“运行中”。
