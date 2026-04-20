from __future__ import annotations

import argparse
import ctypes
import logging
import queue
import threading
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from tkinter import messagebox

import uvicorn

from codex_session_patcher.web_launcher import can_connect, free_port
from web.backend.main import app


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9090
WINDOW_WIDTH = 440
WINDOW_HEIGHT = 760
STARTUP_TIMEOUT_SEC = 25

BG = "#070910"
CARD_BG = "#11131d"
CARD_BORDER = "#202434"
TEXT = "#eef2ff"
MUTED = "#8f97b5"
ACCENT = "#7286ff"
ACCENT_SOFT = "#20274a"
SUCCESS = "#4fd1a5"
WARNING = "#ffbe5c"
ERROR = "#ff6b7d"
INPUT_BG = "#171b29"


class QueueLogHandler(logging.Handler):
    def __init__(self, output_queue: queue.Queue[tuple[str, str]]):
        super().__init__(level=logging.INFO)
        self.output_queue = output_queue
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()

        level = record.levelname.upper()
        if level not in {"INFO", "WARNING", "ERROR"}:
            level = "INFO"
        self.output_queue.put((level, message))


def get_port_owner_pid_local(port: int) -> int | None:
    if port <= 0 or not hasattr(ctypes, "windll"):
        return None

    MIB_TCP_STATE_LISTEN = 2
    AF_INET = 2
    TCP_TABLE_OWNER_PID_LISTENER = 3
    NO_ERROR = 0
    ERROR_INSUFFICIENT_BUFFER = 122

    class MIB_TCPROW_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwState", ctypes.c_uint32),
            ("dwLocalAddr", ctypes.c_uint32),
            ("dwLocalPort", ctypes.c_uint32),
            ("dwRemoteAddr", ctypes.c_uint32),
            ("dwRemotePort", ctypes.c_uint32),
            ("dwOwningPid", ctypes.c_uint32),
        ]

    class MIB_TCPTABLE_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwNumEntries", ctypes.c_uint32),
            ("table", MIB_TCPROW_OWNER_PID * 1),
        ]

    get_extended_tcp_table = ctypes.windll.iphlpapi.GetExtendedTcpTable
    size = ctypes.c_ulong(0)
    result = get_extended_tcp_table(
        None,
        ctypes.byref(size),
        False,
        AF_INET,
        TCP_TABLE_OWNER_PID_LISTENER,
        0,
    )
    if result not in (NO_ERROR, ERROR_INSUFFICIENT_BUFFER):
        return None

    buffer = ctypes.create_string_buffer(size.value)
    result = get_extended_tcp_table(
        buffer,
        ctypes.byref(size),
        False,
        AF_INET,
        TCP_TABLE_OWNER_PID_LISTENER,
        0,
    )
    if result != NO_ERROR:
        return None

    table = ctypes.cast(buffer, ctypes.POINTER(MIB_TCPTABLE_OWNER_PID)).contents
    row_type = MIB_TCPROW_OWNER_PID * table.dwNumEntries
    rows = ctypes.cast(ctypes.addressof(table.table), ctypes.POINTER(row_type)).contents

    for row in rows:
        listen_port = int.from_bytes(int(row.dwLocalPort).to_bytes(4, "little")[:2], "big")
        if row.dwState == MIB_TCP_STATE_LISTEN and listen_port == port:
            return int(row.dwOwningPid)
    return None


@dataclass
class LauncherState:
    port: int = DEFAULT_PORT
    running: bool = False
    starting: bool = False
    stopping: bool = False


class DesktopLauncherApp:
    def __init__(self, initial_port: int):
        self.root = tk.Tk()
        self.root.title("Codex Web 启动器")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.configure(bg=BG)

        self.state = LauncherState(port=initial_port)
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.status_var = tk.StringVar(value="未启动")
        self.hint_var = tk.StringVar(value="点击启动")
        self.port_var = tk.StringVar(value=str(initial_port))
        self.url_var = tk.StringVar(value=self._make_url(initial_port))
        self._after_jobs: set[str] = set()
        self._server_log_handler: QueueLogHandler | None = None

        self._build_ui()
        self._apply_status("idle")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._schedule(120, self._drain_events)

    def _schedule(self, delay_ms: int, callback) -> None:
        def wrapped() -> None:
            job_id = current_job[0]
            if job_id in self._after_jobs:
                self._after_jobs.discard(job_id)
            callback()

        current_job = [""]
        current_job[0] = self.root.after(delay_ms, wrapped)
        self._after_jobs.add(current_job[0])

    def _cancel_after_jobs(self) -> None:
        for job_id in list(self._after_jobs):
            try:
                self.root.after_cancel(job_id)
            except tk.TclError:
                pass
            finally:
                self._after_jobs.discard(job_id)

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(4, weight=1)

        header = tk.Frame(self.root, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)

        title_wrap = tk.Frame(header, bg=BG)
        title_wrap.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_wrap,
            text="Codex Web 启动器",
            font=("Segoe UI", 14, "bold"),
            fg=TEXT,
            bg=BG,
        ).pack(side="left")
        tk.Label(
            title_wrap,
            text="v1.0",
            font=("Segoe UI", 9),
            fg=MUTED,
            bg=BG,
            padx=8,
        ).pack(side="left")

        hero = tk.Frame(self.root, bg=BG)
        hero.grid(row=1, column=0, sticky="nsew", padx=18, pady=(8, 12))

        self.button_canvas = tk.Canvas(
            hero,
            width=220,
            height=220,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )
        self.button_canvas.pack()
        self.button_canvas.bind("<Button-1>", lambda _event: self.toggle_service())

        tk.Label(
            hero,
            textvariable=self.hint_var,
            font=("Segoe UI", 14),
            fg=TEXT,
            bg=BG,
        ).pack(pady=(4, 10))

        self.status_pill = tk.Label(
            hero,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg=MUTED,
            bg=ACCENT_SOFT,
            padx=12,
            pady=6,
        )
        self.status_pill.pack()

        port_card = self._build_card(row=2, title="服务端口", icon="◎")
        port_entry_wrap = tk.Frame(port_card, bg=CARD_BG)
        port_entry_wrap.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 12))
        port_entry_wrap.grid_columnconfigure(0, weight=1)
        self.port_entry = tk.Entry(
            port_entry_wrap,
            textvariable=self.port_var,
            font=("Segoe UI", 12),
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=CARD_BORDER,
            highlightcolor=ACCENT,
        )
        self.port_entry.grid(row=0, column=0, sticky="ew", ipady=12, padx=2, pady=2)

        url_card = self._build_card(row=3, title="访问地址", icon="↗")
        url_line = tk.Frame(url_card, bg=CARD_BG)
        url_line.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 12))
        url_line.grid_columnconfigure(0, weight=1)
        self.url_label = tk.Label(
            url_line,
            textvariable=self.url_var,
            font=("Consolas", 11),
            fg=TEXT,
            bg=INPUT_BG,
            anchor="w",
            padx=12,
            pady=12,
        )
        self.url_label.grid(row=0, column=0, sticky="ew")
        self.open_button = tk.Button(
            url_line,
            text="打开",
            command=self.open_browser,
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT,
            fg=TEXT,
            activebackground="#8a98ff",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=16,
            pady=10,
            cursor="hand2",
        )
        self.open_button.grid(row=0, column=1, padx=(10, 0), sticky="e")

        log_card = self._build_card(row=4, title="启动日志", icon=">_")
        log_card.grid_rowconfigure(1, weight=1)
        log_card.grid_columnconfigure(0, weight=1)
        log_body = tk.Frame(log_card, bg=CARD_BG)
        log_body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(8, 12))
        log_body.grid_rowconfigure(0, weight=1)
        log_body.grid_columnconfigure(0, weight=1)

        text_wrap = tk.Frame(log_body, bg=CARD_BG)
        text_wrap.grid(row=0, column=0, sticky="nsew")
        text_wrap.grid_rowconfigure(0, weight=1)
        text_wrap.grid_columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            text_wrap,
            height=14,
            bg="#0b0e17",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            wrap="word",
            font=("Consolas", 10),
            padx=12,
            pady=12,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_scrollbar = tk.Scrollbar(
            text_wrap,
            orient="vertical",
            command=self.log_text.yview,
        )
        self.log_scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=self.log_scrollbar.set)
        self.log_text.tag_configure("INFO", foreground="#ced6ff")
        self.log_text.tag_configure("SUCCESS", foreground=SUCCESS)
        self.log_text.tag_configure("WARNING", foreground=WARNING)
        self.log_text.tag_configure("ERROR", foreground=ERROR)
        self.log_text.config(state="disabled")

        footer = tk.Frame(log_body, bg=CARD_BG)
        footer.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(0, weight=1)
        self.footer_label = tk.Label(
            footer,
            text="服务启动后的详细日志会显示在这里，可滚动查看。",
            font=("Segoe UI", 9),
            fg=MUTED,
            bg=CARD_BG,
            anchor="w",
        )
        self.footer_label.grid(row=0, column=0, sticky="w")
        tk.Button(
            footer,
            text="清空",
            command=self.clear_logs,
            font=("Segoe UI", 9),
            bg="#181d2c",
            fg=MUTED,
            activebackground="#22283d",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
        ).grid(row=0, column=1, sticky="e")

        self._draw_action_button("idle")

    def _build_card(self, row: int, title: str, icon: str) -> tk.Frame:
        card = tk.Frame(
            self.root,
            bg=CARD_BG,
            highlightthickness=1,
            highlightbackground=CARD_BORDER,
            bd=0,
        )
        card.grid(row=row, column=0, sticky="nsew", padx=18, pady=10)
        card.grid_columnconfigure(0, weight=1)

        header = tk.Frame(card, bg=CARD_BG)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        tk.Label(
            header,
            text=icon,
            font=("Segoe UI", 10),
            fg=MUTED,
            bg=CARD_BG,
        ).pack(side="left")
        tk.Label(
            header,
            text=title,
            font=("Segoe UI", 11),
            fg=MUTED,
            bg=CARD_BG,
            padx=8,
        ).pack(side="left")
        return card

    def _draw_action_button(self, mode: str) -> None:
        canvas = self.button_canvas
        canvas.delete("all")
        outer = "#111522"
        mid = "#131826"
        inner = "#181d2c"
        icon_color = TEXT
        if mode == "running":
            outer = "#14261f"
            mid = "#173126"
            inner = "#1b3d2e"
            icon_color = SUCCESS
        elif mode == "starting":
            outer = "#20253e"
            mid = "#243054"
            inner = "#293866"
            icon_color = ACCENT
        elif mode == "stopping":
            outer = "#33291a"
            mid = "#44321b"
            inner = "#553c1c"
            icon_color = WARNING

        canvas.create_oval(28, 28, 192, 192, fill=outer, outline="")
        canvas.create_oval(42, 42, 178, 178, fill=mid, outline="")
        canvas.create_oval(55, 55, 165, 165, fill=inner, outline="")

        if mode == "running":
            canvas.create_rectangle(95, 95, 125, 125, fill=icon_color, outline="")
        else:
            canvas.create_polygon(98, 88, 98, 132, 132, 110, fill=icon_color, outline="")

    def _apply_status(self, mode: str) -> None:
        palette = {
            "idle": ("未启动", "点击启动", "#171b29", MUTED),
            "starting": ("启动中", "正在拉起服务", "#20274a", ACCENT),
            "running": ("运行中", "点击停止", "#19372d", SUCCESS),
            "stopping": ("停止中", "正在停止服务", "#3a2b12", WARNING),
            "error": ("异常", "请查看启动日志", "#45222a", ERROR),
        }
        status, hint, bg, fg = palette[mode]
        self.status_var.set(status)
        self.hint_var.set(hint)
        self.status_pill.configure(bg=bg, fg=fg)
        self._draw_action_button(mode)
        self.open_button.configure(state="normal" if mode == "running" else "disabled")

    def _make_url(self, port: int) -> str:
        return f"http://{DEFAULT_HOST}:{port}"

    def append_log(self, message: str, level: str = "INFO") -> None:
        if not self.log_text.winfo_exists():
            return
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line, level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def toggle_service(self) -> None:
        if self.state.starting or self.state.stopping:
            return
        if self.state.running:
            self.stop_service()
        else:
            self.start_service()

    def _install_server_logger(self) -> None:
        if self._server_log_handler is not None:
            return

        handler = QueueLogHandler(self.events)
        targets = [
            logging.getLogger("uvicorn"),
            logging.getLogger("uvicorn.error"),
            logging.getLogger("uvicorn.access"),
            logging.getLogger("codex.desktop"),
        ]
        for logger in targets:
            logger.handlers = [handler]
            logger.setLevel(logging.INFO)
            logger.propagate = False
        self._server_log_handler = handler

    def start_service(self) -> None:
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("端口无效", "服务端口必须是整数。")
            return
        if not 1 <= port <= 65535:
            messagebox.showerror("端口无效", "服务端口必须在 1 到 65535 之间。")
            return

        self.state.port = port
        self.url_var.set(self._make_url(port))
        self.state.starting = True
        self._apply_status("starting")
        self.append_log(f"准备启动服务，端口 {port}", "INFO")

        owner_pid = get_port_owner_pid_local(port)
        if owner_pid is not None:
            self.append_log(f"检测到端口 {port} 被 PID {owner_pid} 占用，尝试释放", "WARNING")
            try:
                stopped_pid = free_port(port, preferred_pid=owner_pid)
                if stopped_pid is not None:
                    self.append_log(f"已释放端口 {port}，停止 PID {stopped_pid}", "SUCCESS")
            except Exception as exc:
                self.state.starting = False
                self._apply_status("error")
                self.append_log(f"释放端口失败: {exc}", "ERROR")
                return

        self._install_server_logger()
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=DEFAULT_HOST,
                port=port,
                log_config=None,
                access_log=True,
                log_level="info",
            )
        )
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        self._schedule(150, lambda: self._poll_startup(time.time()))

    def _run_server(self) -> None:
        assert self.server is not None
        try:
            self.server.run()
        except Exception as exc:  # pragma: no cover
            self.events.put(("ERROR", f"服务线程异常退出: {exc}"))
        finally:
            self.events.put(("STOPPED", "server-thread-exited"))

    def _poll_startup(self, started_at: float) -> None:
        port = self.state.port
        if can_connect(DEFAULT_HOST, port):
            self.state.starting = False
            self.state.running = True
            self._apply_status("running")
            self.append_log(f"服务启动成功: {self._make_url(port)}", "SUCCESS")
            self.append_log("可点击“打开”直接在浏览器访问。", "INFO")
            return

        if self.server_thread and not self.server_thread.is_alive():
            self.state.starting = False
            self.state.running = False
            self._apply_status("error")
            self.append_log("服务线程已退出，启动失败。", "ERROR")
            return

        if time.time() - started_at > STARTUP_TIMEOUT_SEC:
            self.state.starting = False
            self.state.running = False
            self._apply_status("error")
            self.append_log("等待服务启动超时。", "ERROR")
            if self.server is not None:
                self.server.should_exit = True
            return

        self._schedule(180, lambda: self._poll_startup(started_at))

    def stop_service(self) -> None:
        if not self.server:
            self.state.running = False
            self.state.starting = False
            self._apply_status("idle")
            return

        self.state.stopping = True
        self._apply_status("stopping")
        self.append_log("正在停止服务...", "INFO")
        self.server.should_exit = True
        self._schedule(180, self._poll_shutdown)

    def _poll_shutdown(self) -> None:
        if self.server_thread and self.server_thread.is_alive():
            self._schedule(180, self._poll_shutdown)
            return

        self.server = None
        self.server_thread = None
        self.state.running = False
        self.state.starting = False
        self.state.stopping = False
        self._apply_status("idle")
        self.append_log("服务已停止。", "INFO")

    def _drain_events(self) -> None:
        while True:
            try:
                level, message = self.events.get_nowait()
            except queue.Empty:
                break

            if message == "server-thread-exited":
                if not self.state.stopping and not self.state.starting and self.state.running:
                    self.state.running = False
                    self._apply_status("idle")
                    self.append_log("服务已退出。", "WARNING")
                continue

            if self.state.starting and (
                "Uvicorn running on" in message
                or "Application startup complete" in message
            ):
                self.state.starting = False
                self.state.running = True
                self._apply_status("running")

            self.append_log(message, level)
        if self.root.winfo_exists():
            self._schedule(120, self._drain_events)

    def open_browser(self) -> None:
        url = self._make_url(self.state.port)
        webbrowser.open(url)
        self.append_log(f"已打开浏览器: {url}", "INFO")

    def on_close(self) -> None:
        if self.state.running or self.state.starting:
            if not messagebox.askyesno("退出", "服务仍在运行，确定停止并退出吗？"):
                return
            if self.server:
                self.server.should_exit = True
        self._cancel_after_jobs()
        self.root.destroy()

    def run(self) -> None:
        self.append_log("启动器已就绪，可自定义端口后点击启动。", "INFO")
        self.root.mainloop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex Session Patcher desktop launcher")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Initial service port")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    launcher = DesktopLauncherApp(initial_port=args.port)
    launcher.run()


if __name__ == "__main__":
    main()
