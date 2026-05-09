"""
YouTube Downloader — powered by yt-dlp
Modern UI with cookies support, quality selection and file size display
"""

import os
import sys
import json
import threading
import subprocess
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import time

# ───────────────────────────── paths ──────────────────────────────
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
YTDLP    = BASE_DIR / "yt-dlp.exe"
FFMPEG   = BASE_DIR / "ffmpeg.exe"
DENO     = BASE_DIR / "deno.exe"
CONFIG_FILE = BASE_DIR / "config.json"

# ─────────────────────────── colour palette ───────────────────────
BG        = "#0f0f13"
BG2       = "#1a1a24"
BG3       = "#242433"
ACCENT    = "#7c6af7"      # purple
ACCENT2   = "#5b9cf6"      # blue
SUCCESS   = "#4ade80"
WARNING   = "#fbbf24"
DANGER    = "#f87171"
TEXT      = "#e2e2f0"
SUBTEXT   = "#8888aa"
BORDER    = "#2e2e45"

FONT_TITLE  = ("Segoe UI", 22, "bold")
FONT_HEAD   = ("Segoe UI", 12, "bold")
FONT_BODY   = ("Segoe UI", 10)
FONT_SMALL  = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 9)


# ══════════════════════════════════════════════════════════════════
class RoundedButton(tk.Canvas):
    """Canvas-based button with rounded corners and hover animation."""

    def __init__(self, parent, text="", command=None,
                 bg=ACCENT, fg=TEXT, hover_bg=None,
                 width=120, height=36, radius=10,
                 font=FONT_BODY, **kwargs):
        super().__init__(parent, width=width, height=height,
                         bg=parent["bg"] if "bg" in parent.keys() else BG,
                         highlightthickness=0, **kwargs)
        self.command  = command
        self.bg       = bg
        self.hover_bg = hover_bg or self._lighten(bg)
        self.fg       = fg
        self.radius   = radius
        self.text     = text
        self.font     = font
        self._current = bg
        self._draw(bg)
        self.bind("<Enter>",    self._on_enter)
        self.bind("<Leave>",    self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _lighten(self, hex_col):
        r, g, b = int(hex_col[1:3], 16), int(hex_col[3:5], 16), int(hex_col[5:7], 16)
        r, g, b = min(255, r + 30), min(255, g + 30), min(255, b + 30)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw(self, fill):
        self.delete("all")
        w, h, r = self.winfo_reqwidth(), self.winfo_reqheight(), self.radius
        self.create_arc(0, 0, 2*r, 2*r, start=90,  extent=90,  fill=fill, outline=fill)
        self.create_arc(w-2*r, 0, w, 2*r, start=0,  extent=90,  fill=fill, outline=fill)
        self.create_arc(0, h-2*r, 2*r, h, start=180, extent=90,  fill=fill, outline=fill)
        self.create_arc(w-2*r, h-2*r, w, h, start=270, extent=90, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w-r, h,   fill=fill, outline=fill)
        self.create_rectangle(0, r, w, h-r,   fill=fill, outline=fill)
        self.create_text(w//2, h//2, text=self.text, fill=self.fg, font=self.font)

    def _on_enter(self, _):
        self._draw(self.hover_bg)

    def _on_leave(self, _):
        self._draw(self.bg)

    def _on_click(self, _):
        if self.command:
            self.command()

    def configure_text(self, text):
        self.text = text
        self._draw(self._current if hasattr(self, "_current") else self.bg)


# ══════════════════════════════════════════════════════════════════
class FormatRow:
    """One row in the format table."""
    def __init__(self, data: dict):
        self.id       = data.get("format_id", "?")
        self.ext      = data.get("ext", "?")
        self.res      = data.get("resolution", data.get("format_note", "?"))
        self.vcodec   = data.get("vcodec", "none")
        self.acodec   = data.get("acodec", "none")
        self.fps      = data.get("fps") or ""
        raw           = data.get("filesize") or data.get("filesize_approx")
        self.size_raw = raw
        self.size_str = self._fmt_size(raw)
        self.tbr      = data.get("tbr") or 0
        self.has_video = self.vcodec not in (None, "none", "")
        self.has_audio = self.acodec not in (None, "none", "")

    @staticmethod
    def _fmt_size(b):
        if not b:
            return "~"
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    @property
    def label(self):
        kind = []
        if self.has_video:
            fps = f" {self.fps}fps" if self.fps else ""
            kind.append(f"🎞 {self.res}{fps}")
        if self.has_audio:
            kind.append("🔊 Audio")
        kind_str = " + ".join(kind) if kind else "❓"
        return f"[{self.id}] {kind_str}  |  .{self.ext}  |  {self.size_str}"


# ══════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.configure(bg=BG)
        self.geometry("900x720")
        self.minsize(780, 600)
        self.resizable(True, True)

        # state
        self._formats: list[FormatRow] = []
        self._dl_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_fetching = False
        self.cookies_path = tk.StringVar(value="")
        self.save_dir     = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.url_var      = tk.StringVar()
        self.sel_format   = tk.StringVar(value="best")
        self.audio_only   = tk.BooleanVar(value=False)
        self.subtitle     = tk.BooleanVar(value=False)
        self.thumbnail    = tk.BooleanVar(value=False)
        self.speed_limit  = tk.StringVar(value="")

        self._load_config()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self._build_ui()
        self._check_dependencies()

    # ─────────────────────── config ───────────────────────────────
    def _load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                if "cookies_path" in config: self.cookies_path.set(config["cookies_path"])
                if "save_dir" in config: self.save_dir.set(config["save_dir"])
                if "audio_only" in config: self.audio_only.set(config["audio_only"])
                if "subtitle" in config: self.subtitle.set(config["subtitle"])
                if "thumbnail" in config: self.thumbnail.set(config["thumbnail"])
                if "speed_limit" in config: self.speed_limit.set(config["speed_limit"])
            except Exception as e:
                print(f"Error loading config: {e}")

    def _save_config(self):
        config = {
            "cookies_path": self.cookies_path.get(),
            "save_dir": self.save_dir.get(),
            "audio_only": self.audio_only.get(),
            "subtitle": self.subtitle.get(),
            "thumbnail": self.thumbnail.get(),
            "speed_limit": self.speed_limit.get()
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def _on_closing(self):
        self._save_config()
        self._stop_event.set()
        self.destroy()

    # ─────────────────────── dependencies check ──────────────────────────
    def _check_dependencies(self):
        if not FFMPEG.exists():
            self._log(f"⚠  ffmpeg.exe 未找到！高画质视频下载后可能无法自动合并音频，请将其放置到: {FFMPEG}", "warn")

        if not YTDLP.exists():
            self._log(f"⚠  yt-dlp.exe 未找到，请放置到: {YTDLP}", "warn")
        else:
            threading.Thread(target=self._update_ytdlp_thread, daemon=True).start()

        # Deno detection
        deno = self._find_deno()
        if deno:
            self._log(f"✅  Deno 已找到: {deno}", "ok")
            self._deno_status_label.config(text=f"✅ Deno: {Path(deno).name}", fg=SUCCESS)
        else:
            self._log(
                "⚠  未找到 deno.exe！某些平台（YouTube 等）需要 Deno 才能获取格式列表。\n"
                "   请将 deno.exe 放到程序同目录，或点击右侧「下载 Deno」按钮。",
                "warn"
            )
            self._deno_status_label.config(text="⚠ Deno 未安装", fg=WARNING)

    def _find_deno(self):
        """Return path to deno.exe if found in BASE_DIR or system PATH, else None."""
        import shutil
        if DENO.exists():
            return str(DENO)
        found = shutil.which("deno")
        return found  # None if not found

    def _update_ytdlp_thread(self):
        self.after(0, self._log, "🔄  正在检查 yt-dlp 更新...", "info")
        try:
            cmd = [str(YTDLP), "-U"]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)

            output = result.stdout + result.stderr
            if "up to date" in output or "is up to date" in output:
                self.after(0, self._log, "✅  yt-dlp 已是最新版本", "ok")
            elif "Updated yt-dlp" in output or "Updating to version" in output:
                self.after(0, self._log, "✨  yt-dlp 更新成功！", "ok")
                self.after(0, messagebox.showinfo, "更新完成", "yt-dlp 已自动更新到最新版本！")
            elif result.returncode != 0:
                self.after(0, self._log, f"❌  yt-dlp 更新失败:\n{output.strip()}", "err")
            else:
                self.after(0, self._log, f"ℹ️  yt-dlp 更新检查结果:\n{output.strip()}", "info")
        except Exception as e:
            self.after(0, self._log, f"❌  检查更新异常: {e}", "err")

    def _download_deno(self):
        """Open browser to Deno releases page for manual download."""
        import webbrowser
        webbrowser.open("https://github.com/denoland/deno/releases/latest")
        self._log(
            "🌐  已打开 Deno 下载页面，请下载 deno-x86_64-pc-windows-msvc.zip，\n"
            f"   解压后将 deno.exe 放到: {BASE_DIR}",
            "info"
        )

    # ─────────────────────────── UI ───────────────────────────────
    def _build_ui(self):
        # title bar area
        top = tk.Frame(self, bg=BG2, pady=16)
        top.pack(fill="x")
        tk.Label(top, text="▶  YouTube Downloader",
                 font=FONT_TITLE, fg=ACCENT, bg=BG2).pack(side="left", padx=24)
        tk.Label(top, text="powered by yt-dlp",
                 font=FONT_SMALL, fg=SUBTEXT, bg=BG2).pack(side="left", padx=4, pady=6)

        # main body (left + right panels)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        left  = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right = tk.Frame(body, bg=BG2, bd=0, relief="flat")
        right.grid(row=0, column=1, sticky="ns")
        self._build_right(right)

        self._build_url_section(left)
        self._build_format_section(left)
        self._build_output_section(left)
        self._build_progress_section(left)
        self._build_log_section(left)

    # ── right panel (settings) ─────────────────────────────────────
    def _build_right(self, parent):
        parent.configure(width=230)
        inner = tk.Frame(parent, bg=BG2, padx=14, pady=14)
        inner.pack(fill="both", expand=True)

        self._section_label(inner, "⚙  设置")

        # cookies
        self._label(inner, "Cookies 文件")
        cookies_row = tk.Frame(inner, bg=BG2)
        cookies_row.pack(fill="x", pady=(2, 8))
        tk.Entry(cookies_row, textvariable=self.cookies_path,
                 font=FONT_SMALL, bg=BG3, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 bd=0, highlightthickness=1,
                 highlightcolor=ACCENT, highlightbackground=BORDER).pack(
            side="left", fill="x", expand=True, ipady=5, padx=(0, 4))
        RoundedButton(cookies_row, text="浏览", command=self._browse_cookies,
                      bg=BG3, width=52, height=30, radius=7,
                      font=FONT_SMALL).pack(side="right")

        # speed limit
        self._label(inner, "限速 (如 2M, 500K)")
        tk.Entry(inner, textvariable=self.speed_limit,
                 font=FONT_SMALL, bg=BG3, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 bd=0, highlightthickness=1,
                 highlightcolor=ACCENT, highlightbackground=BORDER).pack(
            fill="x", ipady=5, pady=(2, 10))

        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=8)
        self._section_label(inner, "📥  下载选项")

        self._checkbtn(inner, "仅下载音频 (MP3)", self.audio_only)
        self._checkbtn(inner, "下载字幕", self.subtitle)
        self._checkbtn(inner, "下载封面缩略图", self.thumbnail)

        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=8)
        self._section_label(inner, "🦕  Deno (JS 解释器)")

        # Deno status label
        self._deno_status_label = tk.Label(
            inner, text="🔍 检测中...",
            font=FONT_SMALL, fg=SUBTEXT, bg=BG2, anchor="w"
        )
        self._deno_status_label.pack(fill="x", pady=(0, 4))

        RoundedButton(inner, text="📥  下载 Deno",
                      command=self._download_deno,
                      bg="#2d4a3e", hover_bg="#3a6b56",
                      width=200, height=30,
                      font=FONT_SMALL).pack(pady=(0, 4))

        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=8)

        # action buttons
        self._fetch_btn = RoundedButton(inner, text="🔍  获取格式列表",
                      command=self._fetch_formats,
                      bg=ACCENT2, width=200, height=38,
                      font=FONT_BODY)
        self._fetch_btn.pack(pady=4)

        self._dl_btn = RoundedButton(inner, text="⬇  开始下载",
                      command=self._start_download,
                      bg=ACCENT, width=200, height=38,
                      font=("Segoe UI", 10, "bold"))
        self._dl_btn.pack(pady=4)

        RoundedButton(inner, text="⏹  停止",
                      command=self._stop_download,
                      bg="#3a3a55", width=200, height=34,
                      font=FONT_SMALL).pack(pady=4)

    # ── left panels ────────────────────────────────────────────────
    def _build_url_section(self, parent):
        card = self._card(parent)
        self._section_label(card, "🔗  视频链接")
        row = tk.Frame(card, bg=self._card_bg)
        row.pack(fill="x", pady=(4, 0))
        self._url_entry = tk.Entry(row, textvariable=self.url_var,
                                   font=FONT_BODY, bg=BG3, fg=TEXT,
                                   insertbackground=TEXT, relief="flat",
                                   bd=0, highlightthickness=1,
                                   highlightcolor=ACCENT,
                                   highlightbackground=BORDER)
        self._url_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self._url_entry.insert(0, "粘贴 YouTube / 播放列表 URL …")
        self._url_entry.config(fg=SUBTEXT)
        self._url_entry.bind("<FocusIn>",  self._url_focus_in)
        self._url_entry.bind("<FocusOut>", self._url_focus_out)

    def _build_format_section(self, parent):
        card = self._card(parent)
        self._section_label(card, "🎬  画质 / 格式选择")

        # dropdown
        self._combo_var = tk.StringVar(value="— 请先点击「获取格式列表」—")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                         fieldbackground=BG3, background=BG3,
                         foreground=TEXT, selectbackground=BG3,
                         selectforeground=TEXT,
                         arrowcolor=ACCENT)
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", BG3)],
                  selectbackground=[("readonly", BG3)])

        self._format_combo = ttk.Combobox(card, textvariable=self._combo_var,
                                           state="readonly", style="Dark.TCombobox",
                                           font=FONT_BODY)
        self._format_combo.pack(fill="x", ipady=5, pady=(4, 4))
        self._format_combo.bind("<<ComboboxSelected>>", self._on_format_select)

        # info row
        self._format_info = tk.Label(card, text="",
                                      font=FONT_SMALL, fg=SUBTEXT,
                                      bg=self._card_bg, anchor="w")
        self._format_info.pack(fill="x")

    def _build_output_section(self, parent):
        card = self._card(parent)
        self._section_label(card, "📁  保存位置")
        row = tk.Frame(card, bg=self._card_bg)
        row.pack(fill="x", pady=(4, 0))
        tk.Entry(row, textvariable=self.save_dir,
                 font=FONT_SMALL, bg=BG3, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 bd=0, highlightthickness=1,
                 highlightcolor=ACCENT, highlightbackground=BORDER).pack(
            side="left", fill="x", expand=True, ipady=5)
        RoundedButton(row, text="选择", command=self._browse_save_dir,
                      bg=BG3, width=56, height=30, radius=7,
                      font=FONT_SMALL).pack(side="right", padx=(6, 0))
        RoundedButton(row, text="打开", command=self._open_save_dir,
                      bg=BG3, width=56, height=30, radius=7,
                      font=FONT_SMALL).pack(side="right", padx=(6, 0))

    def _build_progress_section(self, parent):
        card = self._card(parent)
        self._section_label(card, "📊  下载进度")
        self._progress_label = tk.Label(card, text="等待中…",
                                         font=FONT_SMALL, fg=SUBTEXT,
                                         bg=self._card_bg, anchor="w")
        self._progress_label.pack(fill="x", pady=(4, 4))

        self._pbar = ttk.Progressbar(card, mode="determinate", maximum=100)
        style = ttk.Style()
        style.configure("Accent.Horizontal.TProgressbar",
                         troughcolor=BG3, background=ACCENT,
                         thickness=12)
        self._pbar.configure(style="Accent.Horizontal.TProgressbar")
        self._pbar.pack(fill="x", ipady=2)

        self._speed_label = tk.Label(card, text="",
                                      font=FONT_SMALL, fg=SUBTEXT,
                                      bg=self._card_bg, anchor="w")
        self._speed_label.pack(fill="x")

    def _build_log_section(self, parent):
        card = self._card(parent, expand=True)
        self._section_label(card, "📋  日志输出")
        log_frame = tk.Frame(card, bg=BG3)
        log_frame.pack(fill="both", expand=True, pady=(4, 0))

        self._log_text = tk.Text(log_frame, font=FONT_MONO,
                                  bg=BG3, fg=TEXT,
                                  relief="flat", bd=0,
                                  state="disabled", wrap="word",
                                  selectbackground=ACCENT)
        self._log_text.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        sb = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        sb.pack(side="right", fill="y")
        self._log_text.configure(yscrollcommand=sb.set)

        # colour tags
        self._log_text.tag_configure("ok",   foreground=SUCCESS)
        self._log_text.tag_configure("warn", foreground=WARNING)
        self._log_text.tag_configure("err",  foreground=DANGER)
        self._log_text.tag_configure("info", foreground=ACCENT2)

        # clear button
        RoundedButton(card, text="清除日志", command=self._clear_log,
                      bg=BG3, width=80, height=26, radius=6,
                      font=FONT_SMALL).pack(anchor="e", pady=(4, 0))

    # ── helpers ────────────────────────────────────────────────────
    _card_bg = BG2

    def _card(self, parent, expand=False):
        outer = tk.Frame(parent, bg=BORDER, bd=0)
        outer.pack(fill="both", expand=expand, pady=5)
        inner = tk.Frame(outer, bg=BG2, padx=14, pady=10)
        inner.pack(fill="both", expand=expand, padx=1, pady=1)
        return inner

    def _section_label(self, parent, text):
        tk.Label(parent, text=text, font=FONT_HEAD,
                 fg=ACCENT, bg=parent["bg"]).pack(anchor="w", pady=(0, 4))

    def _label(self, parent, text):
        tk.Label(parent, text=text, font=FONT_SMALL,
                 fg=SUBTEXT, bg=parent["bg"]).pack(anchor="w")

    def _checkbtn(self, parent, text, var):
        style = ttk.Style()
        style.configure("Dark.TCheckbutton",
                         background=BG2, foreground=TEXT,
                         font=FONT_SMALL)
        ttk.Checkbutton(parent, text=text, variable=var,
                        style="Dark.TCheckbutton").pack(anchor="w", pady=2)

    # ── URL placeholder ────────────────────────────────────────────
    def _url_focus_in(self, _):
        if self._url_entry["fg"] == SUBTEXT:
            self._url_entry.delete(0, "end")
            self._url_entry.config(fg=TEXT)

    def _url_focus_out(self, _):
        if not self.url_var.get():
            self._url_entry.insert(0, "粘贴 YouTube / 播放列表 URL …")
            self._url_entry.config(fg=SUBTEXT)

    # ── browse buttons ─────────────────────────────────────────────
    def _browse_cookies(self):
        path = filedialog.askopenfilename(
            title="选择 Cookies 文件",
            filetypes=[("Netscape Cookies", "*.txt"), ("所有文件", "*.*")])
        if path:
            self.cookies_path.set(path)
            self._log(f"✓  已载入 cookies: {path}", "ok")

    def _browse_save_dir(self):
        d = filedialog.askdirectory(title="选择保存目录")
        if d:
            self.save_dir.set(d)

    def _open_save_dir(self):
        d = self.save_dir.get()
        if d and Path(d).exists():
            try:
                os.startfile(d)
            except Exception as e:
                self._log(f"❌ 无法打开文件夹: {e}", "err")

    # ── logging ────────────────────────────────────────────────────
    def _log(self, msg, tag=""):
        self._log_text.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._log_text.insert("end", f"[{ts}] {msg}\n", tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    # ── format on_select ──────────────────────────────────────────
    def _on_format_select(self, _):
        label = self._combo_var.get()
        # find matching format
        for fmt in self._formats:
            if fmt.label == label:
                info_parts = []
                if fmt.vcodec not in (None, "none", ""):
                    info_parts.append(f"视频编码: {fmt.vcodec}")
                if fmt.acodec not in (None, "none", ""):
                    info_parts.append(f"音频编码: {fmt.acodec}")
                if fmt.tbr:
                    info_parts.append(f"码率: {fmt.tbr:.0f}kbps")
                self._format_info.config(
                    text="  |  ".join(info_parts) if info_parts else "")
                self.sel_format.set(fmt.id)
                return
        self.sel_format.set("best")

    # ══════════════════════════════════════════════════════════════
    #  FETCH FORMATS
    # ══════════════════════════════════════════════════════════════
    def _fetch_formats(self):
        if getattr(self, "_is_fetching", False):
            self._log("⏳  正在获取，请不要重复点击...", "warn")
            return

        url = self.url_var.get().strip()
        if not url or url.startswith("粘贴"):
            messagebox.showwarning("提示", "请先输入 YouTube 链接")
            return

        self._is_fetching = True
        # disable buttons during fetch
        self._fetch_btn.bg = "#3a3a55"
        self._fetch_btn._draw("#3a3a55")
        self._log(f"🔍  正在获取格式列表: {url}", "info")
        self._format_combo.set("正在获取…")
        threading.Thread(target=self._fetch_thread, args=(url,), daemon=True).start()

    def _fetch_thread(self, url):
        try:
            cmd = [str(YTDLP), "--dump-json", "--no-playlist"]

            # Pass deno path so yt-dlp can use it as JS interpreter
            deno = self._find_deno()
            if deno:
                cmd += ["--extractor-args", f"youtube:player_client=web"]

            if self.cookies_path.get():
                cmd += ["--cookies", self.cookies_path.get()]
            cmd.append(url)

            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            if result.returncode != 0:
                err = result.stderr.strip().splitlines()
                last_err = err[-1] if err else "未知错误"
                # Give a hint if the error is about missing JS interpreter
                if "deno" in last_err.lower() or "jsinterp" in last_err.lower() \
                        or "format" in last_err.lower():
                    hint = "\n💡 提示：将 deno.exe 放到程序同目录可解决此问题"
                else:
                    hint = ""
                self.after(0, self._log, f"❌  获取失败: {last_err}{hint}", "err")
                self.after(0, self._format_combo.set, "— 获取失败 —")
                return
            data = json.loads(result.stdout)
            formats = [FormatRow(f) for f in data.get("formats", [])]
            formats.sort(key=lambda f: (
                not f.has_video,
                -(f.size_raw or 0)
            ))
            self.after(0, self._populate_formats, formats, data.get("title", ""))
        except Exception as e:
            self.after(0, self._log, f"❌  异常: {e}", "err")
            self.after(0, self._format_combo.set, "— 获取失败 —")
        finally:
            self._is_fetching = False
            # re-enable fetch button
            self.after(0, self._restore_fetch_btn)

    def _restore_fetch_btn(self):
        self._fetch_btn.bg = ACCENT2
        self._fetch_btn._draw(ACCENT2)

    def _populate_formats(self, formats: list[FormatRow], title: str):
        self._formats = formats
        labels = [f.label for f in formats]
        # prepend smart presets
        presets = [
            "✨ 自动最佳画质 (bestvideo+bestaudio)",
            "🎵 仅音频 (bestaudio)",
            "📱 720p (bestvideo[height<=720]+bestaudio)",
            "📱 480p (bestvideo[height<=480]+bestaudio)",
        ]
        all_labels = presets + labels
        self._format_combo["values"] = all_labels
        self._format_combo.set(all_labels[0])
        self.sel_format.set("bestvideo+bestaudio/best")
        self._format_info.config(text=f"视频标题: {title}")
        self._log(f"✓  共找到 {len(formats)} 种格式  |  {title}", "ok")

    # preset id map
    _PRESET_MAP = {
        "✨ 自动最佳画质 (bestvideo+bestaudio)": "bestvideo+bestaudio/best",
        "🎵 仅音频 (bestaudio)": "bestaudio/best",
        "📱 720p (bestvideo[height<=720]+bestaudio)": "bestvideo[height<=720]+bestaudio/best",
        "📱 480p (bestvideo[height<=480]+bestaudio)": "bestvideo[height<=480]+bestaudio/best",
    }

    def _resolve_format(self):
        label = self._combo_var.get()
        if label in self._PRESET_MAP:
            return self._PRESET_MAP[label]
        for fmt in self._formats:
            if fmt.label == label:
                # if video-only, merge with best audio
                if fmt.has_video and not fmt.has_audio:
                    return f"{fmt.id}+bestaudio/best"
                return fmt.id
        return "bestvideo+bestaudio/best"

    # ══════════════════════════════════════════════════════════════
    #  DOWNLOAD
    # ══════════════════════════════════════════════════════════════
    def _start_download(self):
        url = self.url_var.get().strip()
        if not url or url.startswith("粘贴"):
            messagebox.showwarning("提示", "请先输入 YouTube 链接")
            return
        if self._dl_thread and self._dl_thread.is_alive():
            messagebox.showinfo("提示", "已有下载任务正在进行")
            return

        self._stop_event.clear()
        self._pbar["value"] = 0
        self._progress_label.config(text="准备下载…", fg=ACCENT2)
        self._speed_label.config(text="")
        self._log("⬇  开始下载…", "info")
        self._dl_thread = threading.Thread(
            target=self._download_thread, args=(url,), daemon=True)
        self._dl_thread.start()

    def _stop_download(self):
        self._stop_event.set()
        self._log("⏹  已请求停止", "warn")

    def _download_thread(self, url):
        fmt = self._resolve_format()
        out_tmpl = str(Path(self.save_dir.get()) / "%(title)s.%(ext)s")

        cmd = [str(YTDLP),
               "-f", fmt,
               "-o", out_tmpl,
               "--ffmpeg-location", str(FFMPEG.parent),
               "--newline",
               url]

        if self.cookies_path.get():
            cmd += ["--cookies", self.cookies_path.get()]
        if self.audio_only.get():
            cmd += ["--extract-audio", "--audio-format", "mp3",
                    "--audio-quality", "0"]
        if self.subtitle.get():
            cmd += ["--write-auto-sub", "--sub-lang", "zh-Hans,en"]
        if self.thumbnail.get():
            cmd += ["--write-thumbnail"]
        if self.speed_limit.get().strip():
            cmd += ["--limit-rate", self.speed_limit.get().strip()]

        self.after(0, self._log, "CMD: " + " ".join(cmd), "info")

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)

            for line in proc.stdout:
                if self._stop_event.is_set():
                    proc.terminate()
                    self.after(0, self._log, "⏹  下载已停止", "warn")
                    self.after(0, self._progress_label.config, {"text": "已停止", "fg": WARNING})
                    return
                line = line.rstrip()
                self._parse_progress(line)
                self.after(0, self._log, line)

            proc.wait()
            if proc.returncode == 0:
                self.after(0, self._on_download_done)
            else:
                self.after(0, self._log, f"❌  下载失败 (code {proc.returncode})", "err")
                self.after(0, self._progress_label.config, {"text": "下载失败", "fg": DANGER})
        except Exception as e:
            self.after(0, self._log, f"❌  异常: {e}", "err")

    def _parse_progress(self, line):
        # [download]  42.3% of  123.45MiB at  2.34MiB/s ETA 00:30
        m = re.search(r"\[download\]\s+([\d.]+)%.*?at\s+([\d.]+\S+)\s+ETA\s+(\S+)", line)
        if m:
            pct   = float(m.group(1))
            speed = m.group(2)
            eta   = m.group(3)
            self.after(0, self._update_progress, pct, speed, eta)

    def _update_progress(self, pct, speed, eta):
        self._pbar["value"] = pct
        self._progress_label.config(
            text=f"{pct:.1f}%  |  ETA {eta}", fg=ACCENT2)
        self._speed_label.config(
            text=f"速度: {speed}", fg=SUCCESS)

    def _on_download_done(self):
        self._pbar["value"] = 100
        self._progress_label.config(text="✅  下载完成！", fg=SUCCESS)
        self._speed_label.config(text="")
        self._log("✅  下载完成！文件已保存到: " + self.save_dir.get(), "ok")
        
        if messagebox.askyesno("下载完成", f"视频下载完毕！\n\n已保存至:\n{self.save_dir.get()}\n\n是否立即打开该文件夹？"):
            self._open_save_dir()


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()
