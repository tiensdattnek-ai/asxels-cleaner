"""Responsive Tk desktop interface for the safe Python cleanup engine."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import os
import platform
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from . import __version__
from .engine import CATEGORIES, CleanReport, ScanReport, clean_targets, human_bytes, resolve_targets, scan_targets
from .memory import memory_status, trim_working_sets
from .storage import append_activity, load_summary, log_path, save_summary

BG = "#09111F"
PANEL = "#111D31"
PANEL_ALT = "#172640"
BORDER = "#273956"
TEXT = "#F4F7FF"
MUTED = "#9DAECB"
ACCENT = "#4D8CFF"
ACCENT_HOVER = "#6B9EFF"
TEAL = "#42D8C0"
SUCCESS = "#6FE4AB"
AMBER = "#F3AD75"
DANGER = "#F27B7B"


class CleanerApp(tk.Tk):
    """Single-window application. Workers only communicate through Queue."""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"Asxels Cleaner  •  Python Engine v{__version__}")
        self.geometry("1120x790")
        self.minsize(980, 700)
        self.configure(bg=BG)
        self.option_add("*Font", ("Segoe UI", 10))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_dpi()
        self._setup_style()

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.pending_clean = False
        self.category_vars = {item.key: tk.BooleanVar(value=item.default) for item in CATEGORIES}
        self.status_var = tk.StringVar(value="Sẵn sàng. Bấm “Xem trước” để kiểm tra trước khi dọn.")
        self.metric_clean_var = tk.StringVar(value="Chưa kiểm tra")
        self.metric_ram_var = tk.StringVar(value="Đang tải…")
        self.metric_history_var = tk.StringVar(value="Chưa có dữ liệu")
        self.memory_detail_var = tk.StringVar(value="Đang tải thông tin RAM…")
        self.memory_percent = tk.IntVar(value=0)
        self.history = load_summary()

        self._build()
        self._restore_history()
        self._refresh_memory()
        self.after(80, self._poll_events)
        self.after(5000, self._scheduled_memory_refresh)
        self.bind("<F5>", lambda _event: self.preview())
        self.bind("<Return>", lambda _event: self.request_clean())
        self.bind("<Escape>", lambda _event: self.cancel_current())

    def _set_dpi(self) -> None:
        if platform.system() != "Windows":
            return
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 24))
        style.configure("Eyebrow.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI Semibold", 9))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("PanelTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 11))
        style.configure("PanelSub.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("MetricLabel.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI Semibold", 8))
        style.configure("MetricValue.TLabel", background=PANEL, foreground=TEAL, font=("Segoe UI Semibold", 19))
        style.configure("TProgressbar", troughcolor="#0E1930", background=TEAL, borderwidth=0, thickness=7)

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=(30, 23, 30, 18))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        header_left = ttk.Frame(header)
        header_left.pack(side="left", fill="x", expand=True)
        ttk.Label(header_left, text="ASXELS  /  PYTHON ENGINE", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(header_left, text="Dọn sạch thông minh. Có kiểm soát.", style="Title.TLabel").pack(anchor="w", pady=(2, 2))
        ttk.Label(header_left, text="Chỉ xử lý cache và tệp tạm đã biết — không quét toàn ổ hay chạm dữ liệu cá nhân.",
                  style="Sub.TLabel").pack(anchor="w")
        self.platform_badge = tk.Label(header, text="  WINDOWS / PYTHON  ", bg="#183B66", fg="#DDECFF",
                                       font=("Segoe UI Semibold", 8), padx=6, pady=5)
        self.platform_badge.pack(side="right", anchor="n", pady=5)

        metrics = ttk.Frame(outer)
        metrics.pack(fill="x", pady=(20, 17))
        metrics.columnconfigure((0, 1, 2), weight=1, uniform="metric")
        self._metric(metrics, 0, "SẴN SÀNG DỌN", self.metric_clean_var, TEAL)
        self._metric(metrics, 1, "RAM KHẢ DỤNG", self.metric_ram_var, TEAL)
        self._metric(metrics, 2, "LẦN DỌN GẦN NHẤT", self.metric_history_var, TEXT)

        workspace = ttk.Frame(outer)
        workspace.pack(fill="both", expand=True)
        workspace.columnconfigure(0, weight=7)
        workspace.columnconfigure(1, weight=4)
        workspace.rowconfigure(0, weight=1)

        cleanup = ttk.Frame(workspace, style="Panel.TFrame", padding=17)
        cleanup.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._build_cleanup_panel(cleanup)
        side = ttk.Frame(workspace, style="Panel.TFrame", padding=17)
        side.grid(row=0, column=1, sticky="nsew")
        self._build_side_panel(side)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(13, 0))
        self.status_label = ttk.Label(footer, textvariable=self.status_var, style="Sub.TLabel")
        self.status_label.pack(side="left", fill="x", expand=True)
        ttk.Label(footer, text=f"v{__version__}  •  cục bộ / không telemetry", style="Sub.TLabel").pack(side="right")

    def _metric(self, parent: ttk.Frame, column: int, title: str, variable: tk.StringVar, color: str) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=(16, 12))
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 5, 0 if column == 2 else 5))
        ttk.Label(card, text=title, style="MetricLabel.TLabel").pack(anchor="w")
        label = ttk.Label(card, textvariable=variable, style="MetricValue.TLabel")
        label.configure(foreground=color)
        label.pack(anchor="w", pady=(4, 0))

    def _build_cleanup_panel(self, panel: ttk.Frame) -> None:
        title_row = ttk.Frame(panel, style="Panel.TFrame")
        title_row.pack(fill="x")
        ttk.Label(title_row, text="Khu vực dọn dẹp", style="PanelTitle.TLabel").pack(side="left")
        ttk.Label(title_row, text="BẤM ĐỂ CHỌN", style="PanelSub.TLabel", foreground=ACCENT).pack(side="right")
        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", pady=(11, 7))

        self.category_controls: list[tk.Checkbutton] = []
        for category in CATEGORIES:
            card = tk.Frame(panel, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", pady=3)
            check = tk.Checkbutton(card, variable=self.category_vars[category.key], bg=PANEL, activebackground=PANEL,
                                   selectcolor=PANEL_ALT, highlightthickness=0, relief="flat", bd=0,
                                   command=self._selection_changed)
            check.grid(row=0, column=0, rowspan=2, padx=(8, 0), pady=7)
            self.category_controls.append(check)
            tk.Label(card, text=category.title, bg=PANEL, fg=TEXT, anchor="w", font=("Segoe UI Semibold", 10)).grid(
                row=0, column=1, sticky="ew", padx=(3, 10), pady=(6, 0))
            detail = category.subtitle + (f"  •  {category.caution}" if category.caution else "")
            tk.Label(card, text=detail, bg=PANEL, fg=AMBER if category.caution else MUTED, anchor="w",
                     font=("Segoe UI", 8), wraplength=520, justify="left").grid(
                row=1, column=1, sticky="ew", padx=(3, 10), pady=(0, 6))
            card.grid_columnconfigure(1, weight=1)

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        self.preview_button = tk.Button(actions, text="↻  XEM TRƯỚC", command=self.preview, bg=PANEL_ALT, fg=TEXT,
                                        activebackground=BORDER, activeforeground=TEXT, relief="flat", bd=0,
                                        font=("Segoe UI Semibold", 10), padx=17, pady=10, cursor="hand2")
        self.preview_button.pack(side="left")
        self.clean_button = tk.Button(actions, text="✦  DỌN DẸP AN TOÀN", command=self.request_clean, bg=ACCENT, fg="white",
                                      activebackground=ACCENT_HOVER, activeforeground="white", relief="flat", bd=0,
                                      font=("Segoe UI Semibold", 10), padx=20, pady=10, cursor="hand2")
        self.clean_button.pack(side="right")
        self.cancel_button = tk.Button(actions, text="HỦY", command=self.cancel_current, bg="#4A3140", fg="#FFD9DD",
                                       activebackground="#694151", activeforeground="white", relief="flat", bd=0,
                                       font=("Segoe UI Semibold", 9), padx=12, pady=10, state="disabled", cursor="hand2")
        self.cancel_button.pack(side="right", padx=(0, 8))

    def _build_side_panel(self, panel: ttk.Frame) -> None:
        ttk.Label(panel, text="Bộ nhớ tức thì", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Yêu cầu Windows trim working set của các ứng dụng phù hợp. Không đóng tiến trình và không tạo thêm RAM vật lý.",
                  style="PanelSub.TLabel", wraplength=285, justify="left").pack(anchor="w", pady=(5, 12))
        ttk.Label(panel, textvariable=self.memory_detail_var, style="PanelSub.TLabel", wraplength=285, justify="left").pack(anchor="w")
        self.memory_bar = ttk.Progressbar(panel, maximum=100, variable=self.memory_percent)
        self.memory_bar.pack(fill="x", pady=(9, 10))
        self.memory_button = tk.Button(panel, text="⚡  TỐI ƯU BỘ NHỚ", command=self.optimize_memory, bg=PANEL_ALT, fg=TEXT,
                                       activebackground=BORDER, activeforeground=TEXT, relief="flat", bd=0,
                                       font=("Segoe UI Semibold", 10), padx=12, pady=10, cursor="hand2")
        self.memory_button.pack(fill="x")

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", pady=18)
        ttk.Label(panel, text="Minh bạch & an toàn", style="PanelTitle.TLabel").pack(anchor="w")
        rules = (
            "✓  Không đụng Documents, Downloads, Desktop hoặc Registry.",
            "✓  Không theo symbolic link/junction khi quét hoặc xóa.",
            "✓  File đang khóa, bị bảo vệ hoặc thiếu quyền sẽ được bỏ qua.",
            "✓  Hủy tác vụ được hỗ trợ; các file đã xóa trước đó không thể hoàn tác.",
        )
        for rule in rules:
            tk.Label(panel, text=rule, bg=PANEL, fg=SUCCESS if rule.startswith("✓  Không đụng") else MUTED,
                     anchor="w", font=("Segoe UI", 9), wraplength=280, justify="left").pack(anchor="w", pady=4)

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", pady=18)
        logs = ttk.Frame(panel, style="Panel.TFrame")
        logs.pack(fill="x")
        ttk.Label(logs, text="NHẬT KÝ CỤC BỘ", style="PanelSub.TLabel").pack(side="left")
        tk.Button(logs, text="MỞ", command=self.open_logs, bg=PANEL_ALT, fg=TEXT, activebackground=BORDER,
                  activeforeground=TEXT, relief="flat", bd=0, font=("Segoe UI Semibold", 8), padx=10, pady=5,
                  cursor="hand2").pack(side="right")

    def _restore_history(self) -> None:
        if self.history:
            removed = self.history.get("bytes_removed")
            if isinstance(removed, int):
                self.metric_history_var.set(human_bytes(removed))

    def _selected_keys(self) -> list[str]:
        return [key for key, variable in self.category_vars.items() if variable.get()]

    def _selection_changed(self) -> None:
        if not self.busy:
            self.metric_clean_var.set("Cần kiểm tra")
            self.status_var.set("Lựa chọn đã thay đổi. Bấm “Xem trước” để tính lại chính xác.")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for control in self.category_controls:
            control.configure(state=state)
        self.preview_button.configure(state=state)
        self.clean_button.configure(state=state)
        self.memory_button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def _worker(self, kind: str, job: Callable[[], Any]) -> None:
        self._set_busy(True)
        self.cancel_event.clear()

        def run() -> None:
            try:
                self.events.put((kind, job()))
            except Exception as exc:  # Engine failures must reach the UI, not vanish in a thread.
                self.events.put(("error", (kind, f"{type(exc).__name__}: {exc}")))

        threading.Thread(target=run, name=f"asxels-{kind}", daemon=True).start()

    def _progress(self, text: str) -> None:
        self.events.put(("status", text))

    def preview(self) -> None:
        keys = self._selected_keys()
        if not keys:
            messagebox.showinfo("Asxels Cleaner", "Hãy chọn ít nhất một khu vực để kiểm tra.")
            return
        self.pending_clean = False
        self.status_var.set("Đang kiểm tra các khu vực đã chọn…")
        self._worker("scan", lambda: self._scan_job(keys, False))

    def request_clean(self) -> None:
        keys = self._selected_keys()
        if not keys:
            messagebox.showinfo("Asxels Cleaner", "Hãy chọn ít nhất một khu vực để dọn.")
            return
        self.pending_clean = True
        self.status_var.set("Đang kiểm tra lần cuối trước khi dọn…")
        self._worker("scan", lambda: self._scan_job(keys, True))

    def _scan_job(self, keys: list[str], clean_after: bool) -> tuple[ScanReport, list[Any], bool]:
        targets = resolve_targets(keys)
        report = scan_targets(targets, self._progress, self.cancel_event.is_set)
        return report, targets, clean_after

    def _start_clean(self, targets: list[Any]) -> None:
        self.status_var.set("Đang dọn các tệp cache/tạm đã xác nhận…")
        self._worker("clean", lambda: clean_targets(targets, self._progress, self.cancel_event.is_set))

    def optimize_memory(self) -> None:
        if platform.system() != "Windows":
            messagebox.showwarning("Asxels Cleaner", "Tính năng này chỉ hỗ trợ Windows.")
            return
        self.status_var.set("Đang gửi yêu cầu trim working set đến Windows…")
        self._worker("memory", lambda: trim_working_sets(self._progress, self.cancel_event.is_set))

    def cancel_current(self) -> None:
        if self.busy:
            self.cancel_event.set()
            self.status_var.set("Đang yêu cầu dừng sau mục hiện tại…")

    def _after_scan(self, payload: tuple[ScanReport, list[Any], bool]) -> None:
        report, targets, clean_after = payload
        self._set_busy(False)
        self.metric_clean_var.set(human_bytes(report.bytes_found))
        self.metric_history_var.set(f"{report.items_found:,} mục".replace(",", "."))
        if report.cancelled:
            self.status_var.set("Đã hủy khi đang kiểm tra. Không có tệp nào bị thay đổi.")
            return
        text = f"Tìm thấy {human_bytes(report.bytes_found)} trong {report.items_found:,} mục".replace(",", ".")
        if report.inaccessible:
            text += f"  •  {report.inaccessible} mục không đọc được"
        self.status_var.set(text)
        if not clean_after:
            return
        if not targets or not report.items_found:
            messagebox.showinfo("Asxels Cleaner", "Không tìm thấy tệp cache/tạm phù hợp trong các khu vực đã chọn.")
            return
        confirmation = (
            f"Xóa an toàn tối đa {human_bytes(report.bytes_found)} từ {report.items_found:,} mục?\n\n"
            "• Chỉ các vị trí cache/tạm cố định đã liệt kê.\n"
            "• Tệp đang dùng hoặc được hệ thống bảo vệ sẽ được bỏ qua.\n"
            "• Thùng rác (nếu chọn) sẽ bị dọn toàn bộ.\n"
            "• Không thể hoàn tác các tệp đã xóa."
        )
        if messagebox.askyesno("Xác nhận dọn dẹp", confirmation, icon="warning", default="no"):
            self._start_clean(targets)
        else:
            self.status_var.set("Đã hủy. Không có tệp nào bị thay đổi.")

    def _after_clean(self, report: CleanReport) -> None:
        self._set_busy(False)
        text = f"Đã dọn {human_bytes(report.bytes_removed)} từ {report.files_removed:,} mục".replace(",", ".")
        if report.folders_removed:
            text += f"  •  {report.folders_removed:,} thư mục".replace(",", ".")
        if report.skipped:
            text += f"  •  bỏ qua {report.skipped:,} mục".replace(",", ".")
        if report.errors:
            text += f"  •  lỗi {report.errors:,}".replace(",", ".")
        if report.cancelled:
            text += "  •  đã hủy theo yêu cầu"
        self.metric_clean_var.set("Đã dọn " + human_bytes(report.bytes_removed))
        self.metric_history_var.set(human_bytes(report.bytes_removed))
        self.status_var.set(text)
        append_activity("CLEAN", text)
        save_summary({"bytes_removed": report.bytes_removed, "files_removed": report.files_removed, "cancelled": report.cancelled})
        messagebox.showinfo("Asxels Cleaner", text + "\n\nTệp khóa/bảo vệ không bị ép xóa.")

    def _after_memory(self, result: tuple[int, int]) -> None:
        tried, trimmed = result
        self._set_busy(False)
        self.after(450, self._refresh_memory)
        text = f"Windows đã trim working set cho {trimmed}/{tried} tiến trình phù hợp."
        self.status_var.set(text)
        append_activity("MEMORY", text)
        messagebox.showinfo("Asxels Cleaner", text + "\n\nKhông có ứng dụng nào bị đóng; Windows tự quản lý việc phân bổ RAM.")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "scan":
                    self._after_scan(payload)
                elif kind == "clean":
                    self._after_clean(payload)
                elif kind == "memory":
                    self._after_memory(payload)
                elif kind == "error":
                    action, message = payload
                    self.pending_clean = False
                    self._set_busy(False)
                    self.status_var.set(f"Có lỗi khi {action}.")
                    append_activity("ERROR", f"{action}: {message}")
                    messagebox.showerror("Asxels Cleaner", f"Có lỗi khi thực hiện tác vụ:\n{message}")
        except queue.Empty:
            pass
        self.after(80, self._poll_events)

    def _refresh_memory(self) -> None:
        total, available, load = memory_status()
        if total:
            self.metric_ram_var.set(human_bytes(available))
            self.memory_detail_var.set(
                f"{human_bytes(available)} khả dụng / {human_bytes(total)} tổng  •  đang dùng {load}%"
            )
            self.memory_percent.set(load)
        elif platform.system() != "Windows":
            self.metric_ram_var.set("Windows only")
            self.memory_detail_var.set("Tối ưu bộ nhớ dùng Windows API và chỉ chạy trên Windows.")

    def _scheduled_memory_refresh(self) -> None:
        if not self.busy:
            self._refresh_memory()
        self.after(5000, self._scheduled_memory_refresh)

    def open_logs(self) -> None:
        folder = log_path().parent
        try:
            if platform.system() == "Windows":
                os.startfile(folder)  # type: ignore[attr-defined]
            else:
                messagebox.showinfo("Asxels Cleaner", f"Nhật ký: {folder}")
        except OSError as exc:
            messagebox.showerror("Asxels Cleaner", f"Không thể mở thư mục nhật ký.\n{exc}")

    def _on_close(self) -> None:
        if self.busy:
            messagebox.showinfo("Asxels Cleaner", "Tác vụ đang chạy. Hãy bấm HỦY và chờ tác vụ kết thúc trước khi đóng.")
            return
        self.destroy()
