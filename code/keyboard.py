import collections
import math
import queue
import threading
import time
import tkinter as tk

try:
    import numpy as np
    import sounddevice as sd
    import pyautogui
except ImportError as exc:
    raise SystemExit(
        f"Missing package: {exc}\n\n"
        "Run:\npy -m pip install --upgrade numpy sounddevice pyautogui"
    )

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False

SAMPLE_RATE_PREFERENCES = (48000, 44100, 32000, 16000)
BLOCK_SIZE = 256
DEFAULT_SENSITIVITY = 7.0       
LETTER_SILENCE = 0.60
REFRACTORY = 0.12
AUTO_RETRY_MS = 4000
HISTORY = 64

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E",
    "..-.": "F", "--.": "G", "....": "H", "..": "I", ".---": "J",
    "-.-": "K", ".-..": "L", "--": "M", "-.": "N", "---": "O",
    ".--.": "P", "--.-": "Q", ".-.": "R", "...": "S", "-": "T",
    "..-": "U", "...-": "V", ".--": "W", "-..-": "X", "-.--": "Y",
    "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3",
    "....-": "4", ".....": "5", "-....": "6", "--...": "7",
    "---..": "8", "----.": "9",
}


SPECIAL = {
    "..--": "space",
    "---.": "backspace",
    "........": "backspace",  
    ".-.-": "enter",
}
SPECIAL_LABEL = {"space": "SPC", "backspace": "BKSP", "enter": "ENTER"}

BG = "#050A14"
PANEL = "#0A1424"
PANEL2 = "#0F1F36"
DEEP = "#060E1B"
BORDER = "#173250"
CYAN = "#00E5FF"
MAGENTA = "#FF2BD6"
VIOLET = "#8B5CF6"
GREEN = "#39FFA0"
ORANGE = "#FFB547"
RED = "#FF4D6D"
WHITE = "#EAF6FF"
MUTED = "#7F9BB5"

audio_events = queue.Queue()
audio_levels = queue.Queue(maxsize=400)
audio_errors = queue.Queue()


def blend(c1, c2, t):
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t)
                                   for i in range(3))


def drain(q):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return

class SoundEngine:
    """Detects short, sharp sounds (clap / finger snap).

    A snap is very short and bright, so its overall volume (RMS) is low.
    We therefore look at the sharp "edge" of the signal (first difference,
    a simple high-pass filter) and compare it with an adaptive noise floor.
    """

    def __init__(self):
        self.stream = None
        self.running = False
        self.last_trigger = 0.0
        self.last_callback_time = 0.0
        self.device_name = ""
        self.sample_rate = None
        self.lock = threading.RLock()
        self.prev = 0.0
        self.floor = 0.002
        self.ratio = 4.7
        self.min_abs = 0.005
        self.set_sensitivity(DEFAULT_SENSITIVITY)

    def set_sensitivity(self, s):
        s = float(s)
        self.ratio = 11.0 - s * 0.9
        self.min_abs = 0.012 - s * 0.001

    def callback(self, indata, frames, time_info, status):
        if not self.running:
            return
        now = time.monotonic()
        self.last_callback_time = now
        if status and audio_errors.qsize() < 3:
            audio_errors.put(str(status))

        x = indata.mean(axis=1) if indata.ndim > 1 else indata[:, 0]
        x = x.astype(np.float32)
        d = np.empty_like(x)
        d[0] = x[0] - self.prev
        d[1:] = x[1:] - x[:-1]
        self.prev = float(x[-1])

        peak = float(np.max(np.abs(d)))
        thr = max(self.min_abs, self.floor * self.ratio)

        if peak < thr:
            self.floor = self.floor * 0.97 + peak * 0.03

        try:
            audio_levels.put_nowait((peak, thr))
        except queue.Full:
            pass

        if peak >= thr and now - self.last_trigger >= REFRACTORY:
            self.last_trigger = now
            audio_events.put((now, peak))

    def _candidate_devices(self):
        devices = sd.query_devices()
        try:
            default_input = sd.default.device[0]
            default_input = (None if default_input is None
                             or int(default_input) < 0 else int(default_input))
        except Exception:
            default_input = None

        candidates = []
        if default_input is not None:
            candidates.append(default_input)
        for index, info in enumerate(devices):
            if info["max_input_channels"] > 0 and index not in candidates:
                candidates.append(index)
        return [(i, devices[i]) for i in candidates
                if devices[i]["max_input_channels"] > 0]

    def connect_automatically(self):
        with self.lock:
            if self.running and self.stream is not None:
                return True

            self.stop()
            drain(audio_events)
            drain(audio_levels)
            drain(audio_errors)
            self.prev = 0.0
            self.floor = 0.002

            try:
                candidates = self._candidate_devices()
            except Exception as exc:
                raise RuntimeError(f"Could not enumerate audio devices: {exc}")

            if not candidates:
                raise RuntimeError(
                    "Windows did not report any microphone input device. "
                    "Check that a recording device is enabled in Windows."
                )

            failures = []
            for index, info in candidates:
                name = str(info["name"])
                max_channels = int(info["max_input_channels"])
                channels_to_try = [1] + ([2] if max_channels >= 2 else [])

                default_rate = int(info.get("default_samplerate") or 0)
                rates = [default_rate] if default_rate > 0 else []
                for rate in SAMPLE_RATE_PREFERENCES:
                    if rate not in rates:
                        rates.append(rate)

                for channels in channels_to_try:
                    for rate in rates:
                        stream = None
                        try:
                            sd.check_input_settings(
                                device=index, channels=channels,
                                dtype="float32", samplerate=rate)
                            stream = sd.InputStream(
                                device=index, samplerate=rate,
                                channels=channels, blocksize=BLOCK_SIZE,
                                dtype="float32", latency="low",
                                callback=self.callback)
                            self.running = True
                            stream.start()
                            self.stream = stream
                            self.device_name = name
                            self.sample_rate = rate
                            return True
                        except Exception as exc:
                            self.running = False
                            if stream is not None:
                                try:
                                    stream.close()
                                except Exception:
                                    pass
                            failures.append(
                                f"{name} ({rate} Hz, {channels} ch): {exc}")

            short = "\n".join(failures[:5])
            if len(failures) > 5:
                short += f"\n...and {len(failures) - 5} more attempts."
            raise RuntimeError(
                "Found microphone devices, but Windows/PortAudio could not "
                "open any of them.\n\n" + short)

    def stop(self):
        with self.lock:
            self.running = False
            stream, self.stream = self.stream, None
            if stream is not None:
                for fn in (stream.stop, stream.close):
                    try:
                        fn()
                    except Exception:
                        pass
            self.device_name = ""
            self.sample_rate = None

class NeonButton(tk.Label):
    def __init__(self, parent, text, command, color=CYAN, pad=(16, 11)):
        super().__init__(
            parent, text=text, bg=PANEL2, fg=color, cursor="hand2",
            font=("Segoe UI", 10, "bold"), padx=pad[0], pady=pad[1],
            highlightthickness=1,
            highlightbackground=blend(PANEL2, color, 0.45))
        self.color = color
        self.command = command
        self.enabled = True
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonRelease-1>", self._click)

    def _enter(self, _e):
        if self.enabled:
            self.configure(bg=blend(PANEL2, self.color, 0.20),
                           highlightbackground=self.color)

    def _leave(self, _e):
        if self.enabled:
            self.configure(bg=PANEL2,
                           highlightbackground=blend(PANEL2, self.color, 0.45))

    def _click(self, e):
        if (self.enabled and 0 <= e.x <= self.winfo_width()
                and 0 <= e.y <= self.winfo_height()):
            self.command()

    def set_enabled(self, value):
        self.enabled = value
        if value:
            self.configure(fg=self.color, cursor="hand2", bg=PANEL2,
                           highlightbackground=blend(PANEL2, self.color, 0.45))
        else:
            self.configure(fg=MUTED, cursor="arrow", bg=PANEL2,
                           highlightbackground=BORDER)

    def set_text(self, text, color=None):
        if color:
            self.color = color
        self.configure(text=text)
        self.set_enabled(self.enabled)


def glow_text(canvas, x, y, text, size, color, anchor="w"):
    font = ("Segoe UI", size, "bold")
    for dist, strength in ((3, 0.10), (2, 0.18), (1, 0.32)):
        col = blend(BG, color, strength)
        for dx, dy in ((-dist, 0), (dist, 0), (0, -dist), (0, dist),
                       (-dist, -dist), (dist, dist),
                       (-dist, dist), (dist, -dist)):
            canvas.create_text(x + dx, y + dy, text=text, font=font,
                               fill=col, anchor=anchor)
    canvas.create_text(x, y, text=text, font=font, fill=color, anchor=anchor)


class App:
    def __init__(self, root):
        self.root = root
        root.title("MH2 - Clap-Snap Keyboard")
        root.geometry("960x760")
        root.minsize(780, 580)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.engine = SoundEngine()
        self.listening = False
        self.connecting = False
        self.mini = False
        self.typing_enabled = True
        self.normal_geometry = "960x760"
        self.next_retry_at = 0
        self.bucket_start = None
        self.bucket_count = 0
        self.last_sound_time = None
        self.morse_buffer = ""
        self.typed_text = ""
        self.total_sounds = 0
        self.flash = 0.0
        self.cur_thr = 0.02
        self.history = collections.deque([0.0] * HISTORY, maxlen=HISTORY)

        self.status = tk.StringVar()
        self.status_short = tk.StringVar()
        self.device_status = tk.StringVar()
        self.device_name = tk.StringVar(value="Detecting automatically...")
        self.meter_text = tk.StringVar(value="Waiting for audio samples...")
        self.count = tk.StringVar(value="0")
        self.group = tk.StringVar(value="0")
        self.letter = tk.StringVar(value="-")
        self.morse = tk.StringVar(value="Waiting for clap or finger snap...")
        self.decoded = tk.StringVar(value="Decoded character: -")
        self.output = tk.StringVar(value="")
        self.dots = []

        self.main_frame = tk.Frame(root, bg=BG)
        self.mini_frame = tk.Frame(root, bg=BG)
        self.build_main()
        self.build_mini()
        self.main_frame.pack(fill="both", expand=True)
        self.pinned = True
        self.root.attributes("-topmost", True)
        self.root.bind("<Unmap>", self.keep_visible)
        self.set_status("AUTO CONNECTING TO MICROPHONE...", "CONNECTING...",
                        ORANGE, "SEARCHING INPUT DEVICES")

        self.root.after(500, self.auto_connect)
        self.root.after(20, self.poll)
        self.root.after(40, self.animate)

    def lbl(self, parent, text, size=9, color=MUTED, weight="bold", **kw):
        bg = kw.pop("bg", None) or parent.cget("bg")
        return tk.Label(parent, text=text, bg=bg, fg=color,
                        font=("Segoe UI", size, weight), **kw)

    def card(self, parent, pady=5):
        f = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                     highlightthickness=1)
        f.pack(fill="x", pady=pady)
        return f

    def set_status(self, long_text, short_text, color, device_text=""):
        self.status.set(long_text)
        self.status_short.set(short_text)
        self.device_status.set(device_text)
        for d in self.dots:
            d.configure(fg=color)

    def refresh_output(self):
        """Show typed text; Enter is displayed as a return symbol."""
        shown = self.typed_text.replace("\n", "\u23ce")
        self.output.set(shown[-60:] if self.mini else shown[-100:])


  
    def build_main(self):
        m = self.main_frame

        header = tk.Frame(m, bg=BG)
        header.pack(fill="x", padx=24, pady=(14, 2))
        title = tk.Canvas(header, width=520, height=58, bg=BG,
                          highlightthickness=0)
        title.pack(side="left")
        glow_text(title, 6, 30, "MH2", 30, CYAN)
        glow_text(title, 112, 34, "CLAP-SNAP KEYBOARD", 16, WHITE)

        NeonButton(header, "MINI MODE", self.toggle_mini, VIOLET,
                   (14, 8)).pack(side="right", padx=(8, 0), pady=(10, 0))
        self.pin_btn = NeonButton(header, "PIN: ON", self.toggle_pin, GREEN,
                                  (14, 8))
        self.pin_btn.pack(side="right", pady=(10, 0))

        self.line = tk.Canvas(m, height=4, bg=BG, highlightthickness=0)
        self.line.pack(fill="x", padx=24, pady=(0, 6))
        self.line_items = []
        for i in range(60):
            self.line_items.append(
                self.line.create_rectangle(0, 0, 1, 4, outline="", fill=CYAN))
        self.line.bind("<Configure>", self.layout_line)

        body = tk.Frame(m, bg=BG)
        body.pack(fill="both", expand=True, padx=24)

        # status + device
        sc = self.card(body)
        row = tk.Frame(sc, bg=PANEL)
        row.pack(fill="x", padx=16, pady=(10, 4))
        dot = self.lbl(row, "\u25cf", 16, ORANGE)
        dot.pack(side="left")
        self.dots.append(dot)
        tk.Label(row, textvariable=self.status, bg=PANEL, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=10)
        tk.Label(row, textvariable=self.device_status, bg=PANEL, fg=ORANGE,
                 font=("Consolas", 9, "bold")).pack(side="right")
        row2 = tk.Frame(sc, bg=PANEL)
        row2.pack(fill="x", padx=16, pady=(0, 10))
        self.lbl(row2, "ACTIVE MICROPHONE", 8).pack(side="left")
        tk.Label(row2, textvariable=self.device_name, bg=PANEL, fg=CYAN,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=12)
        NeonButton(row2, "AUTO CONNECT", self.manual_reconnect, CYAN,
                   (12, 5)).pack(side="right")

        vc = self.card(body)
        vi = tk.Frame(vc, bg=PANEL)
        vi.pack(fill="x", padx=16, pady=(10, 12))
        top = tk.Frame(vi, bg=PANEL)
        top.pack(fill="x")
        self.lbl(top, "LIVE SIGNAL  \u2022  ORANGE LINE = TRIGGER LEVEL",
                 8).pack(side="left")
        tk.Label(top, textvariable=self.meter_text, bg=PANEL, fg=CYAN,
                 font=("Consolas", 9)).pack(side="right")
        self.viz = tk.Canvas(vi, height=120, bg=DEEP, highlightthickness=1,
                             highlightbackground=BORDER)
        self.viz.pack(fill="x", pady=(8, 0))
        self.lbl(vi, "TIMING  \u2022  0.4s WINDOW: 2nd SNAP MUST COME BEFORE "
                 "THE BAR EMPTIES", 8).pack(anchor="w", pady=(8, 3))
        self.timer = tk.Canvas(vi, height=26, bg=DEEP, highlightthickness=1,
                               highlightbackground=BORDER)
        self.timer.pack(fill="x")


      
        stats = tk.Frame(body, bg=BG)
        stats.pack(fill="x", pady=5)
        for i, (title_, var, color) in enumerate((
                ("TOTAL SOUNDS", self.count, CYAN),
                ("CURRENT GROUP", self.group, ORANGE),
                ("LAST KEY", self.letter, GREEN))):
            f = tk.Frame(stats, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1)
            f.pack(side="left", fill="both", expand=True,
                   padx=(0, 8 if i < 2 else 0))
            self.lbl(f, title_, 8).pack(pady=(8, 0))
            tk.Label(f, textvariable=var, bg=PANEL, fg=color,
                     font=("Segoe UI", 22, "bold")).pack(pady=(0, 6))

      
        oc = self.card(body)
        oi = tk.Frame(oc, bg=PANEL)
        oi.pack(fill="x", padx=16, pady=10)
        self.lbl(oi, "LIVE MORSE SEQUENCE", 8).pack(anchor="w")
        tk.Label(oi, textvariable=self.morse, bg=PANEL, fg=CYAN,
                 font=("Consolas", 20, "bold"), anchor="w").pack(fill="x")
        tk.Label(oi, textvariable=self.decoded, bg=PANEL, fg=GREEN,
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(anchor="w")

        tc = self.card(body)
        ti = tk.Frame(tc, bg=PANEL)
        ti.pack(fill="x", padx=16, pady=10)
        self.lbl(ti, "TYPED OUTPUT", 8).pack(anchor="w")
        tk.Label(ti, textvariable=self.output, bg=PANEL, fg=WHITE,
                 font=("Consolas", 16, "bold"), anchor="w", justify="left",
                 wraplength=820).pack(fill="x", pady=(2, 0))

      
        controls = tk.Frame(m, bg=BG)
        controls.pack(fill="x", padx=24, pady=(6, 4))
        for c in range(4):
            controls.columnconfigure(c, weight=1, uniform="b")
        self.start_btn = NeonButton(controls, "\u25b6  START", self.start_listening, GREEN)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.stop_btn = NeonButton(controls, "\u25a0  STOP", self.stop_listening, RED)
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=6)
        self.stop_btn.set_enabled(False)
        NeonButton(controls, "CLEAR", self.clear, CYAN).grid(
            row=0, column=2, sticky="ew", padx=6)
        self.typing_btn = NeonButton(controls, "TYPING: ON", self.toggle_typing, MAGENTA)
        self.typing_btn.grid(row=0, column=3, sticky="ew", padx=(6, 0))

        settings = tk.Frame(m, bg=BG)
        settings.pack(fill="x", padx=24, pady=(4, 2))
        self.lbl(settings, "SNAP / CLAP SENSITIVITY", 8, bg=BG).pack(side="left")
        self.sens = tk.DoubleVar(value=DEFAULT_SENSITIVITY)
        tk.Scale(settings, from_=1, to=10, resolution=0.5,
                 orient="horizontal", variable=self.sens, bg=BG, fg=WHITE,
                 troughcolor="#17334A", activebackground=CYAN,
                 highlightthickness=0, length=260,
                 command=self.change_sensitivity).pack(side="left", padx=12)
        self.lbl(settings, "Higher = easier to trigger (use 8-10 for soft finger snaps)",
                 8, bg=BG).pack(side="left")

        self.lbl(m, "1 sound = DOT (.)    2 sounds = DASH (-)    "
                 "0.4s group window    0.6s silence = decode",
                 8, bg=BG).pack(pady=(2, 0))
        self.lbl(m, "SPACE = ..--     BACKSPACE = ---.  (or ........)     "
                 "ENTER = .-.-",
                 9, ORANGE, bg=BG).pack(pady=(2, 8))

    def layout_line(self, event):
        w = max(60, event.width)
        seg = w / len(self.line_items)
        for i, item in enumerate(self.line_items):
            self.line.coords(item, i * seg, 0, (i + 1) * seg + 1, 4)

  
    def build_mini(self):
        m = self.mini_frame
        top = tk.Frame(m, bg=PANEL, highlightbackground=CYAN,
                       highlightthickness=1)
        top.pack(fill="both", expand=True, padx=6, pady=6)

        r1 = tk.Frame(top, bg=PANEL)
        r1.pack(fill="x", padx=10, pady=(8, 0))
        dot = self.lbl(r1, "\u25cf", 13, ORANGE)
        dot.pack(side="left")
        self.dots.append(dot)
        tk.Label(r1, textvariable=self.status_short, bg=PANEL, fg=WHITE,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=8)
        tk.Label(r1, textvariable=self.letter, bg=PANEL, fg=GREEN,
                 font=("Segoe UI", 16, "bold")).pack(side="right")
        self.lbl(r1, "LAST", 8).pack(side="right", padx=6)

        tk.Label(top, textvariable=self.morse, bg=PANEL, fg=CYAN,
                 font=("Consolas", 14, "bold"), anchor="w").pack(
                     fill="x", padx=10, pady=(4, 0))
        tk.Label(top, textvariable=self.output, bg=PANEL, fg=WHITE,
                 font=("Consolas", 11, "bold"), anchor="w").pack(
                     fill="x", padx=10)
        self.mini_timer = tk.Canvas(top, height=22, bg=DEEP,
                                    highlightthickness=1,
                                    highlightbackground=BORDER)
        self.mini_timer.pack(fill="x", padx=10, pady=(6, 0))

        r4 = tk.Frame(top, bg=PANEL)
        r4.pack(fill="x", padx=10, pady=8)
        NeonButton(r4, "EXPAND", self.toggle_mini, VIOLET,
                   (10, 4)).pack(side="left")
        self.mini_toggle = NeonButton(r4, "STOP", self.mini_start_stop, RED,
                                      (10, 4))
        self.mini_toggle.pack(side="right")

    def toggle_mini(self):
        if not self.mini:
            self.normal_geometry = self.root.geometry()
            self.main_frame.pack_forget()
            self.mini_frame.pack(fill="both", expand=True)
            self.root.minsize(330, 160)
            self.root.geometry("400x175")
            self.mini = True
        else:
            self.mini_frame.pack_forget()
            self.main_frame.pack(fill="both", expand=True)
            self.root.minsize(780, 580)
            self.root.geometry(self.normal_geometry)
            self.mini = False
        self.refresh_output()

    def keep_visible(self, event=None):
        """The window can never stay minimized: it comes straight back."""
        if event is not None and event.widget is not self.root:
            return
        try:
            if self.root.state() == "iconic":
                self.root.after(30, self.root.deiconify)
        except tk.TclError:
            pass

    def draw_timer(self, canvas):
        """Countdown bar that shows how long the current window stays open."""
        now = time.monotonic()
        w = max(100, canvas.winfo_width())
        h = max(12, canvas.winfo_height())
        canvas.delete("all")

        if self.bucket_count and self.bucket_start is not None:
            left = max(0.0, GROUP_WINDOW - (now - self.bucket_start))
            frac = left / GROUP_WINDOW
            color = blend(RED, GREEN, frac)
            text = (f"SNAP AGAIN NOW FOR DASH  {left:.2f}s" if left > 0
                    else "GROUP CLOSED")
        elif (self.morse_buffer and self.last_sound_time is not None):
            left = max(0.0, LETTER_SILENCE - (now - self.last_sound_time))
            frac = left / LETTER_SILENCE
            color = VIOLET
            text = f"NEXT SYMBOL OR WAIT TO TYPE  {left:.2f}s"
        else:
            frac = 0.0
            color = CYAN
            text = "READY  \u2022  SNAP OR CLAP"

        canvas.create_rectangle(0, 0, w, h, fill=DEEP, outline="")
        if frac > 0:
            canvas.create_rectangle(0, 0, w * frac, h,
                                    fill=blend(DEEP, color, 0.35), outline="")
            canvas.create_rectangle(0, 0, w * frac, 3, fill=color, outline="")
            canvas.create_rectangle(0, h - 3, w * frac, h, fill=color,
                                    outline="")
        canvas.create_text(w / 2, h / 2, text=text, fill=WHITE,
                           font=("Consolas", 10, "bold"))

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.pin_btn.set_text("PIN: ON" if self.pinned else "PIN: OFF",
                              GREEN if self.pinned else MUTED)

    def mini_start_stop(self):
        if self.listening:
            self.stop_listening()
        else:
            self.start_listening()

    def refresh_buttons(self):
        self.start_btn.set_enabled(not self.listening)
        self.stop_btn.set_enabled(self.listening)
        if self.listening:
            self.mini_toggle.set_text("STOP", RED)
        else:
            self.mini_toggle.set_text("START", GREEN)

    def toggle_typing(self):
        self.typing_enabled = not self.typing_enabled
        self.typing_btn.set_text(
            "TYPING: ON" if self.typing_enabled else "TYPING: OFF",
            MAGENTA if self.typing_enabled else MUTED)

  
    def auto_connect(self):
        if self.listening or self.connecting:
            return
        self.connecting = True
        self.set_status("SEARCHING AND CONNECTING TO MICROPHONE...",
                        "CONNECTING...", ORANGE, "AUTO SCAN")
        self.root.update_idletasks()
        try:
            self.engine.set_sensitivity(self.sens.get())
            self.engine.connect_automatically()
            self.listening = True
            self.set_status("MICROPHONE CONNECTED  \u2022  LISTENING",
                            "LISTENING", GREEN, "AUDIO STREAM OPEN")
            self.device_name.set(
                f"{self.engine.device_name}  ({self.engine.sample_rate} Hz)")
            self.meter_text.set("Ready - clap or snap")
            self.next_retry_at = 0
        except Exception as exc:
            self.listening = False
            self.set_status("MIC NOT CONNECTED  \u2022  AUTO RETRY ENABLED",
                            "NO MIC - RETRYING", RED, "RETRYING")
            self.device_name.set("No active input stream")
            self.next_retry_at = time.monotonic() + AUTO_RETRY_MS / 1000
            self.decoded.set("Microphone: " + str(exc).split("\n")[0])
        finally:
            self.connecting = False
            self.refresh_buttons()

    def manual_reconnect(self):
        if self.connecting:
            return
        self.engine.stop()
        self.listening = False
        self.root.after(100, self.auto_connect)

    def start_listening(self):
        if not self.listening:
            self.auto_connect()

    def stop_listening(self):
        if self.listening:
            self.process_events()
            if self.bucket_count:
                self.flush_bucket()
            if self.morse_buffer:
                self.decode()
        self.engine.stop()
        self.listening = False
        self.set_status("MICROPHONE STOPPED", "STOPPED", RED, "STREAM CLOSED")
        self.device_name.set("Stopped by user")
        self.meter_text.set("Stopped - press Start")
        self.next_retry_at = 0
        self.refresh_buttons()

  
    def change_sensitivity(self, value):
        self.engine.set_sensitivity(value)

    @staticmethod
    def symbols(n):
        return "-" * (n // 2) + ("." if n % 2 else "")

    def update_morse(self):
        current = self.morse_buffer
        if self.bucket_count:
            current += self.symbols(self.bucket_count)
        self.morse.set(current or "Waiting for clap or finger snap...")
        self.group.set(str(self.bucket_count))

    def flush_bucket(self):
        if self.bucket_count:
            self.morse_buffer += self.symbols(self.bucket_count)
            self.bucket_count = 0
            self.bucket_start = None
            self.update_morse()

    def press_key(self, key, label):
        """Send a real key press (letters are typed, special keys pressed)."""
        if not self.typing_enabled:
            return
        try:
            if key in ("space", "backspace", "enter"):
                pyautogui.press(key)
            else:
                pyautogui.write(key.lower(), interval=0)
        except Exception as exc:
            self.decoded.set(f"Decoded {label}; typing error: {exc}")

    def decode(self):
        if not self.morse_buffer:
            return
        code = self.morse_buffer
        letter = MORSE.get(code)
        action = SPECIAL.get(code)

        if letter:
            self.letter.set(letter)
            self.decoded.set(f"Decoded character: {letter}  |  Morse: {code}")
            self.typed_text = (self.typed_text + letter)[-300:]
            self.press_key(letter, letter)
        elif action:
            label = SPECIAL_LABEL[action]
            self.letter.set(label)
            self.decoded.set(f"Special key: {action.upper()}  |  Morse: {code}")
            if action == "space":
                self.typed_text = (self.typed_text + " ")[-300:]
            elif action == "enter":
                self.typed_text = (self.typed_text + "\n")[-300:]
            elif action == "backspace":
                self.typed_text = self.typed_text[:-1]
            self.press_key(action, label)
        else:
            self.letter.set("?")
            self.decoded.set(f"Unknown Morse code: {code}")

        self.refresh_output()
        self.morse_buffer = ""
        self.update_morse()

    def process_events(self):
        while True:
            try:
                event_time, level = audio_events.get_nowait()
            except queue.Empty:
                break
            if (self.bucket_count and self.bucket_start is not None
                    and event_time - self.bucket_start > GROUP_WINDOW):
                self.flush_bucket()
            if self.bucket_count == 0:
                self.bucket_start = event_time
            self.bucket_count += 1
            self.last_sound_time = event_time
            self.total_sounds += 1
            self.count.set(str(self.total_sounds))
            self.flash = 1.0
            self.update_morse()

    def poll(self):
        now = time.monotonic()
        if self.listening:
            self.process_events()
            if (self.bucket_count and self.bucket_start is not None
                    and now - self.bucket_start >= GROUP_WINDOW):
                self.flush_bucket()
            if (self.morse_buffer and self.bucket_count == 0
                    and self.last_sound_time is not None
                    and now - self.last_sound_time >= LETTER_SILENCE):
                self.decode()
                self.last_sound_time = None

            peak, thr, got = 0.0, None, False
            while True:
                try:
                    p, t = audio_levels.get_nowait()
                except queue.Empty:
                    break
                got = True
                peak = max(peak, p)
                thr = t
            if got:
                self.cur_thr = thr
                self.history.append(peak)
                self.meter_text.set(
                    f"signal {peak:.4f}  \u2022  trigger {thr:.4f}")

            if (self.engine.last_callback_time
                    and now - self.engine.last_callback_time > 5):
                self.engine.stop()
                self.listening = False
                self.set_status("AUDIO INPUT LOST  \u2022  RECONNECTING...",
                                "RECONNECTING...", ORANGE, "RETRYING")
                self.next_retry_at = now + 0.5
                self.refresh_buttons()
        elif self.next_retry_at and now >= self.next_retry_at:
            self.next_retry_at = 0
            self.auto_connect()

        try:
            err = audio_errors.get_nowait()
            self.meter_text.set(f"Audio driver notice: {err}")
        except queue.Empty:
            pass

        self.root.after(30, self.poll)

    def animate(self):
        t = time.monotonic()

        if not self.mini:
            n = len(self.line_items)
            for i, item in enumerate(self.line_items):
                k = (i / n - t * 0.25) % 1.0
                self.line.itemconfigure(
                    item, fill=blend(CYAN, MAGENTA, abs(k * 2 - 1)))

            c = self.viz
            w = max(200, c.winfo_width())
            h = max(80, c.winfo_height())
            c.delete("all")
            mid = h / 2
            step = w / HISTORY
            thr = max(self.cur_thr, 1e-6)
            values = list(self.history)
            for i, v in enumerate(values):
                ratio = min(1.0, v / (thr * 2))
                bh = 2 + ratio * (mid - 8)
                col = MAGENTA if v >= thr else blend(CYAN, VIOLET, i / HISTORY)
                x0 = i * step + 2
                x1 = x0 + step - 4
                c.create_rectangle(x0 - 1, mid - bh - 3, x1 + 1, mid + bh + 3,
                                   fill=blend(DEEP, col, 0.22), outline="")
                c.create_rectangle(x0, mid - bh, x1, mid + bh,
                                   fill=col, outline="")
            ty = 2 + 0.5 * (mid - 8)
            for y in (mid - ty, mid + ty):
                c.create_line(0, y, w, y, fill=ORANGE, dash=(4, 4))
            c.configure(highlightbackground=blend(BORDER, MAGENTA,
                                                  self.flash))

        self.draw_timer(self.mini_timer if self.mini else self.timer)

        if self.pinned and int(t * 25) % 25 == 0:
            try:
                if self.root.state() != "iconic":
                    self.root.attributes("-topmost", True)
            except tk.TclError:
                pass

        self.flash *= 0.85
        self.root.after(40, self.animate)

    def clear(self):
        self.typed_text = ""
        self.morse_buffer = ""
        self.bucket_count = 0
        self.bucket_start = None
        self.last_sound_time = None
        self.total_sounds = 0
        self.output.set("")
        self.morse.set("Waiting for clap or finger snap...")
        self.decoded.set("Decoded character: -")
        self.letter.set("-")
        self.group.set("0")
        self.count.set("0")
        drain(audio_events)

    def close(self):
        self.listening = False
        self.engine.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
