"""Switch KBM - programa para remapear teclado/mouse -> botoes do Switch e rodar o bridge."""
import os
import queue
import re
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk  # noqa: E402
from tkinter import messagebox, simpledialog, ttk  # noqa: E402

import bindings as bd  # noqa: E402
import profiles as pf  # noqa: E402
from mapping import display_name  # noqa: E402

APP_TITLE = "Switch KBM"
AIM_LABELS = {"gyro": "Giroscópio", "stick": "Analógico direito"}
CREATE_NO_WINDOW = 0x08000000
STATUS_PREFIXES = ("Modo gatilho", "DualSense", "CAPTURADO", "LIBERADO", "Modo de mira",
                   "Sensibilidade")


def list_ports():
    """Retorna lista de (device, rotulo)."""
    try:
        from serial.tools import list_ports as lp
        out = []
        for p in sorted(lp.comports(), key=lambda x: x.device):
            out.append((p.device, "%s — %s" % (p.device, p.description or "serial")))
        return out
    except Exception:
        return []


def pick_default_port(ports):
    for key in ("cp210", "ch9102"):
        for dev, label in ports:
            if key in label.lower():
                return dev
    return ports[0][0] if ports else ""


class BridgeRunner:
    """Executa o bridge como subprocesso e entrega as linhas por uma fila."""

    def __init__(self):
        self.proc = None
        self.q = queue.Queue()

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def command(port, config_path):
        args = ["--port", port, "--config", config_path, "--stdin-control"]
        if getattr(sys, "frozen", False):
            return [sys.executable, "--bridge"] + args
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kbm_bridge.py")
        return [sys.executable, "-u", script] + args

    def start(self, port, config_path):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            self.command(port, config_path), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW, env=env)
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        try:
            for raw in iter(proc.stdout.readline, b""):
                self.q.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        except Exception:
            pass

    def stop(self):
        p = self.proc
        if p is None:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.write(b"quit\n")
                    p.stdin.flush()
                    p.stdin.close()
                except Exception:
                    pass
                try:
                    p.wait(3)
                except subprocess.TimeoutExpired:
                    p.terminate()
                    try:
                        p.wait(2)
                    except subprocess.TimeoutExpired:
                        p.kill()
        finally:
            self.proc = None


class FlashRunner:
    """Executa o gravador de firmware como subprocesso; linhas (separadas por CR ou LF) na fila."""

    def __init__(self):
        self.proc = None
        self.q = queue.Queue()

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, port):
        import flasher
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            flasher.command(port), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW, env=env)
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        buf = b""
        try:
            while True:
                chunk = proc.stdout.read1(256)
                if not chunk:
                    break
                buf += chunk
                parts = buf.replace(b"\r", b"\n").split(b"\n")
                buf = parts.pop()
                for raw in parts:
                    if raw.strip():
                        self.q.put(raw.decode("utf-8", "replace"))
            if buf.strip():
                self.q.put(buf.decode("utf-8", "replace"))
        except Exception:
            pass

    def kill(self):
        p = self.proc
        if p is not None and p.poll() is None:
            p.kill()


class App(tk.Tk):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or pf.ProfileStore()
        self.runner = BridgeRunner()
        self.title(APP_TITLE)
        self.geometry("760x720")
        self.minsize(640, 520)
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        self.name = ""
        self.base = {}
        self.rows = bd.empty_rows()
        self.dirty = False
        self.loading = False
        self.waiting = None
        self.cells = {}
        self.extras = {}
        self.ports = []
        self.stat_extra = ""
        self.flasher = FlashRunner()
        self.flash_resume = False
        self._flash_pct = -1
        self._build()
        st = self.store.load_settings()
        names = self.store.names()
        last = st.get("last_profile")
        self.profile_cb["values"] = names
        self._load_profile(last if last in names else names[0])
        self._refresh_ports(st.get("port"))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<KeyPress>", self._on_key, add="+")
        self.bind_all("<ButtonPress>", self._on_mouse_btn, add="+")
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.after(100, self._poll)

    # ---------------- construcao ----------------
    def _build(self):
        pad = dict(padx=8, pady=4)
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Perfil:").grid(row=0, column=0, sticky="w")
        self.profile_var = tk.StringVar()
        self.profile_cb = ttk.Combobox(top, textvariable=self.profile_var, state="readonly",
                                       width=24)
        self.profile_cb.grid(row=0, column=1, padx=4)
        self.profile_cb.bind("<<ComboboxSelected>>", self._on_profile_pick)
        for i, (t, cmd) in enumerate((("Novo", self._new), ("Duplicar", self._dup),
                                      ("Renomear", self._rename), ("Excluir", self._delete))):
            ttk.Button(top, text=t, command=cmd, width=9).grid(row=0, column=2 + i, padx=2)
        ttk.Label(top, text="Porta:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(top, textvariable=self.port_var, state="readonly", width=48)
        self.port_cb.grid(row=1, column=1, columnspan=4, padx=4, pady=(6, 0), sticky="we")
        self.port_cb.bind("<<ComboboxSelected>>", self._on_port_pick)
        ttk.Button(top, text="Atualizar", command=self._refresh_ports, width=9).grid(
            row=1, column=5, padx=2, pady=(6, 0))
        self.prep_btn = ttk.Button(top, text="Preparar placa", command=self._prepare, width=14)
        self.prep_btn.grid(row=1, column=6, padx=2, pady=(6, 0))

        # parte de baixo primeiro (para o canvas expandir no meio)
        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", **pad)
        self.status_var = tk.StringVar(value="Parado")
        self.msg_var = tk.StringVar(value="")
        btns = ttk.Frame(bottom)
        btns.pack(fill="x")
        ttk.Button(btns, text="Salvar", command=self.save).pack(side="left")
        ttk.Button(btns, text="Restaurar padrão", command=self._restore).pack(side="left", padx=6)
        self.run_btn = ttk.Button(btns, text="Iniciar", command=self._toggle_run, width=12)
        self.run_btn.pack(side="right")
        ttk.Label(bottom, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(6, 0))
        ttk.Label(bottom, textvariable=self.msg_var, foreground="#555").pack(anchor="w")
        self.log_open = False
        self.log_btn = ttk.Button(bottom, text="Log ▸", command=self._toggle_log, width=8)
        self.log_btn.pack(anchor="w", pady=(4, 0))
        self.log_frame = ttk.Frame(bottom)
        self.log_text = tk.Text(self.log_frame, height=7, state="disabled", wrap="none")
        sb = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self._build_settings()

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)
        self.canvas = tk.Canvas(mid, highlightthickness=0)
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win,
                                                                            width=e.width))
        self._build_rows()

    def _build_rows(self):
        f = self.inner
        f.columnconfigure(0, weight=1, minsize=190)
        r = 0
        for c, t in ((0, "Botão do Switch"), (1, "Tecla 1"), (2, "Tecla 2")):
            ttk.Label(f, text=t, font=("Segoe UI", 9, "bold")).grid(row=r, column=c, sticky="w",
                                                                    padx=4, pady=2)
        r += 1
        for rid, label in bd.BUTTON_ROWS:
            self._make_row(r, rid, label, 2)
            r += 1
        ttk.Separator(f).grid(row=r, column=0, columnspan=5, sticky="we", pady=8)
        r += 1
        ttk.Label(f, text="Movimento (analógico esquerdo)",
                  font=("Segoe UI", 10, "bold")).grid(row=r, column=0, columnspan=5,
                                                      sticky="w", padx=4)
        r += 1
        for rid, label in bd.MOVE_ROWS:
            self._make_row(r, rid, label, 1)
            r += 1
        ttk.Label(f, text="Mira: mouse + setas (o modo de mira define quem controla o giroscópio e quem controla o analógico direito).",
                  wraplength=460, justify="left",
                  foreground="#555").grid(row=r, column=0, columnspan=5, sticky="w", padx=4,
                                          pady=(8, 4))

    def _make_row(self, r, rid, label, nslots):
        f = self.inner
        ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", padx=4, pady=2)
        for s in range(nslots):
            c = ttk.Label(f, text="", width=24, anchor="center", relief="groove",
                          background="white", cursor="hand2", padding=3)
            c.grid(row=r, column=1 + s, padx=3, pady=2)
            c.bind("<Button-1>", lambda e, a=rid, b=s: self._cell_click(a, b))
            c.bind("<Button-3>", lambda e, a=rid, b=s: self._cell_menu(e, a, b))
            self.cells[(rid, s)] = c
        ttk.Button(f, text="✕", width=3, command=lambda a=rid: self._clear(a)).grid(
            row=r, column=3, padx=3)
        ex = ttk.Label(f, text="", foreground="#888")
        ex.grid(row=r, column=4, sticky="w")
        self.extras[rid] = ex

    def _build_settings(self):
        fr = ttk.LabelFrame(self, text="Mira e ajustes")
        fr.pack(side="bottom", fill="x", padx=8, pady=4)
        fr.columnconfigure(1, weight=1)
        self.v_aim = tk.StringVar()
        self.v_sens = tk.DoubleVar(value=0.05)
        self.v_invh = tk.BooleanVar()
        self.v_invv = tk.BooleanVar()
        self.v_walk = tk.DoubleVar(value=0.5)
        self.v_wheel = tk.DoubleVar(value=80)
        ttk.Label(fr, text="Modo de mira:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        cb = ttk.Combobox(fr, textvariable=self.v_aim, state="readonly", width=20,
                          values=list(AIM_LABELS.values()))
        cb.grid(row=0, column=1, sticky="w")
        ttk.Label(fr, text="Sensibilidade:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        ttk.Scale(fr, from_=0.005, to=0.3, variable=self.v_sens).grid(row=1, column=1,
                                                                      sticky="we")
        ttk.Entry(fr, textvariable=self.v_sens, width=8).grid(row=1, column=2, padx=6)
        ttk.Checkbutton(fr, text="Inverter horizontal", variable=self.v_invh).grid(
            row=2, column=0, sticky="w", padx=6)
        ttk.Checkbutton(fr, text="Inverter vertical", variable=self.v_invv).grid(
            row=2, column=1, sticky="w")
        ttk.Label(fr, text="Andar devagar:").grid(row=3, column=0, sticky="w", padx=6, pady=3)
        ttk.Scale(fr, from_=0.2, to=0.9, variable=self.v_walk).grid(row=3, column=1,
                                                                    sticky="we")
        ttk.Entry(fr, textvariable=self.v_walk, width=8).grid(row=3, column=2, padx=6)
        ttk.Label(fr, text="Roda: pulso (ms):").grid(row=4, column=0, sticky="w", padx=6,
                                                     pady=3)
        ttk.Entry(fr, textvariable=self.v_wheel, width=8).grid(row=4, column=1, sticky="w")
        for v in (self.v_aim, self.v_sens, self.v_invh, self.v_invv, self.v_walk, self.v_wheel):
            v.trace_add("write", lambda *a: self._set_dirty())

    # ---------------- estado ----------------
    def _set_dirty(self, d=True):
        if self.loading:
            return
        self.dirty = d
        self._title()

    def _title(self):
        self.title("%s%s — %s" % ("*" if self.dirty else "", APP_TITLE, self.name))

    def _msg(self, text):
        self.msg_var.set(text)

    def _refresh_cells(self):
        for (rid, s), c in self.cells.items():
            if self.waiting == (rid, s):
                c.configure(text="Pressione uma tecla…", foreground="#c00000")
            else:
                k = self.rows[rid][s] if s < len(self.rows[rid]) else ""
                c.configure(text=display_name(k) if k else "—",
                            foreground="black" if k else "#999")
        for rid, ex in self.extras.items():
            more = [display_name(k) for k in self.rows[rid][bd.SLOTS:] if k]
            ex.configure(text=("+ " + ", ".join(more)) if more and rid in bd.BUTTON_IDS else "")

    def _load_profile(self, name):
        self.loading = True
        try:
            data = self.store.load(name)
            self.name = name
            self.profile_var.set(name)
            self._apply_data(data)
        finally:
            self.loading = False
        self.dirty = False
        self._title()
        self.store.save_settings(last_profile=name)

    def _apply_data(self, data):
        self.base = data
        self.rows = bd.profile_to_rows(data)
        d = bd.SETTING_DEFAULTS
        self.v_aim.set(AIM_LABELS.get(data.get("aim_mode", "gyro"), AIM_LABELS["gyro"]))
        self.v_sens.set(round(float(data.get("deg_per_count", d["deg_per_count"])) *
                              float(data.get("gyro_sensitivity", 1.0)), 4))
        self.v_invh.set(not data.get("invert_yaw", True))
        self.v_invv.set(not data.get("invert_pitch", True))
        self.v_walk.set(round(float(data.get("walk_scale", d["walk_scale"])), 3))
        self.v_wheel.set(float(data.get("wheel_pulse_ms", d["wheel_pulse_ms"])))
        self.waiting = None
        self._refresh_cells()

    def collect(self):
        aim = "stick" if self.v_aim.get() == AIM_LABELS["stick"] else "gyro"
        s = {
            "aim_mode": aim,
            "deg_per_count": round(max(0.001, self._num(self.v_sens, 0.05)), 4),
            "gyro_sensitivity": 1.0,
            "invert_yaw": not self.v_invh.get(),
            "invert_pitch": not self.v_invv.get(),
            "walk_scale": round(min(0.95, max(0.1, self._num(self.v_walk, 0.5))), 3),
            "wheel_pulse_ms": max(10.0, self._num(self.v_wheel, 80)),
        }
        return bd.rows_to_profile(self.rows, s, self.base)

    @staticmethod
    def _num(var, default):
        try:
            return float(var.get())
        except (tk.TclError, ValueError):
            return default

    # ---------------- captura de teclas ----------------
    def _cell_click(self, rid, slot):
        if self.waiting:
            return None             # deixa o bind_all tratar como clique de mouse
        self.waiting = (rid, slot)
        self._refresh_cells()
        self._msg("Pressione a tecla (ou clique/roda do mouse). Esc cancela.")
        self.focus_force()
        return "break"

    def _cell_menu(self, ev, rid, slot):
        if self.waiting:
            return None
        m = tk.Menu(self, tearoff=0)
        for label, name in (("Botão lateral 1 do mouse", "x1"), ("Botão lateral 2 do mouse", "x2"),
                            ("Roda ↑", "wheel_up"), ("Roda ↓", "wheel_down"), ("Esc", "esc")):
            m.add_command(label=label, command=lambda n=name: self._assign(rid, slot, n))
        m.add_separator()
        m.add_command(label="Limpar", command=lambda: self._clear_slot(rid, slot))
        m.tk_popup(ev.x_root, ev.y_root)
        return "break"

    def _on_key(self, ev):
        if not self.waiting:
            return None
        if ev.keysym == "Escape":
            self.waiting = None
            self._refresh_cells()
            self._msg("Cancelado.")
            return "break"
        name = bd.tk_event_to_name(ev.keycode, ev.keysym)
        if name is None:
            self._msg("Tecla não suportada (código %s, %s)." % (ev.keycode, ev.keysym))
            return "break"
        rid, slot = self.waiting
        self.waiting = None
        self._assign(rid, slot, name)
        return "break"

    def _on_mouse_btn(self, ev):
        if not self.waiting:
            return None
        names = {1: "lmb", 2: "mmb", 3: "rmb", 4: "x1", 5: "x2", 8: "x1", 9: "x2"}
        name = names.get(ev.num)
        if not name:
            return "break"
        rid, slot = self.waiting
        self.waiting = None
        self._assign(rid, slot, name)
        return "break"

    def _on_wheel(self, ev):
        if self.waiting:
            rid, slot = self.waiting
            self.waiting = None
            self._assign(rid, slot, "wheel_up" if ev.delta > 0 else "wheel_down")
            return "break"
        if str(ev.widget).startswith(str(self.canvas)):
            self.canvas.yview_scroll(-1 if ev.delta > 0 else 1, "units")
        return None

    def _assign(self, rid, slot, name):
        self.waiting = None
        try:
            new, moved = bd.assign_key(self.rows, rid, slot, name)
        except ValueError as e:
            self._msg("Aviso: %s" % e)
            self._refresh_cells()
            return
        if new != self.rows:
            self.rows = new
            self._set_dirty()
        if moved:
            self._msg("%s saiu de %s" % (display_name(name), bd.ROW_LABELS[moved]))
        else:
            self._msg("")
        self._refresh_cells()

    def _clear_slot(self, rid, slot):
        self.rows = bd.clear_slot(self.rows, rid, slot)
        self._set_dirty()
        self._refresh_cells()

    def _clear(self, rid):
        self.waiting = None
        self.rows = bd.clear_row(self.rows, rid)
        self._set_dirty()
        self._refresh_cells()

    # ---------------- perfis ----------------
    def _refresh_names(self):
        self.profile_cb["values"] = self.store.names()

    def _confirm_discard(self):
        """True se pode seguir (salvou ou descartou)."""
        if not self.dirty:
            return True
        r = messagebox.askyesnocancel(APP_TITLE, "Há alterações não salvas no perfil \"%s\". "
                                      "Salvar antes de continuar?" % self.name)
        if r is None:
            return False
        if r:
            self.save(restart=False)
        return True

    def _switch(self, name):
        self._load_profile(name)
        if self.runner.running:
            self._restart()

    def _on_profile_pick(self, _e=None):
        new = self.profile_var.get()
        if new == self.name:
            return
        if not self._confirm_discard():
            self.profile_var.set(self.name)
            return
        self._switch(new)

    def _ask_name(self, title, initial=""):
        n = simpledialog.askstring(APP_TITLE, title, initialvalue=initial, parent=self)
        return pf.clean_name(n) if n else None

    def _new(self):
        if not self._confirm_discard():
            return
        n = self._ask_name("Nome do novo perfil:")
        if n:
            try:
                n = self.store.create(n)
            except ValueError as e:
                messagebox.showerror(APP_TITLE, str(e))
                return
            self._refresh_names()
            self._switch(n)

    def _dup(self):
        n = self._ask_name("Nome da cópia:", self.name + " (cópia)")
        if n:
            try:
                n = self.store.create(n, self.collect())
            except ValueError as e:
                messagebox.showerror(APP_TITLE, str(e))
                return
            self._refresh_names()
            self._switch(n)

    def _rename(self):
        n = self._ask_name("Novo nome:", self.name)
        if n and n != self.name:
            try:
                new = self.store.rename(self.name, n)
            except (ValueError, OSError) as e:
                messagebox.showerror(APP_TITLE, str(e))
                return
            self.name = new
            self.profile_var.set(new)
            self._refresh_names()
            self.store.save_settings(last_profile=new)
            self._title()

    def _delete(self):
        if not messagebox.askyesno(APP_TITLE, "Excluir o perfil \"%s\"?" % self.name):
            return
        try:
            self.store.delete(self.name)
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        self._refresh_names()
        self.dirty = False
        self._switch(self.store.names()[0])

    def save(self, restart=True):
        try:
            data = self.collect()
            self.store.save(self.name, data)
        except OSError as e:
            messagebox.showerror(APP_TITLE, "Falha ao salvar: %s" % e)
            return False
        self.base = data
        self.dirty = False
        self._title()
        self._msg("Perfil salvo.")
        if restart and self.runner.running:
            self._restart()
        return True

    def _restore(self):
        if not messagebox.askyesno(APP_TITLE, "Restaurar os valores padrão neste perfil? "
                                   "(só vale ao salvar)"):
            return
        self.loading = True
        try:
            self._apply_data(pf.default_profile())
        finally:
            self.loading = False
        self._set_dirty()

    # ---------------- portas ----------------
    def _refresh_ports(self, preferred=None):
        if not isinstance(preferred, str):
            preferred = None
        self.ports = list_ports()
        self.port_cb["values"] = [lbl for _, lbl in self.ports]
        want = preferred or self._cur_port() or pick_default_port(self.ports)
        for dev, lbl in self.ports:
            if dev == want:
                self.port_var.set(lbl)
                return
        self.port_var.set("")

    def _cur_port(self):
        cur = self.port_var.get()
        for dev, lbl in self.ports:
            if lbl == cur:
                return dev
        return ""

    def _on_port_pick(self, _e=None):
        self.store.save_settings(port=self._cur_port())

    # ---------------- bridge ----------------
    def _log(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        n = int(self.log_text.index("end-1c").split(".")[0])
        if n > 500:
            self.log_text.delete("1.0", "%d.0" % (n - 500))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _toggle_log(self):
        self.log_open = not self.log_open
        if self.log_open:
            self.log_frame.pack(fill="x", pady=2)
        else:
            self.log_frame.pack_forget()
        self.log_btn.configure(text="Log ▾" if self.log_open else "Log ▸")

    def _toggle_run(self):
        if self.runner.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        if self.flasher.running:
            messagebox.showwarning(APP_TITLE, "Aguarde o fim da gravação do firmware.")
            return
        port = self._cur_port()
        if not port:
            messagebox.showwarning(APP_TITLE, "Selecione a porta COM da placa (Placa-USBC ou Placa-MicroB).")
            return
        if self.dirty and not self.save(restart=False):
            return
        try:
            self.runner.start(port, self.store.path(self.name))
        except OSError as e:
            messagebox.showerror(APP_TITLE, "Não foi possível iniciar o bridge: %s" % e)
            return
        self.stat_extra = ""
        self._set_status()

    def _prepare(self):
        if self.flasher.running:
            return
        port = self._cur_port()
        if not port:
            messagebox.showwarning(APP_TITLE, "Selecione a porta COM da placa (Placa-USBC ou Placa-MicroB).")
            return
        if not messagebox.askyesno(APP_TITLE, "Gravar o firmware na placa em %s? "
                                   "Não desconecte o cabo até terminar (~30 s)." % port):
            return
        self.flash_resume = self.runner.running
        if self.flash_resume:
            self._stop()
        if not self.log_open:
            self._toggle_log()
        try:
            self.flasher.start(port)
        except OSError as e:
            messagebox.showerror(APP_TITLE, "Não foi possível iniciar a gravação: %s" % e)
            return
        self._flash_pct = -1
        self.prep_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self._msg("Gravando firmware...")

    def _on_flash_line(self, line):
        m = re.search(r"\((\d+) ?%\)", line)
        if m and line.startswith("Writing at"):
            pct = int(m.group(1)) // 10 * 10
            if pct == self._flash_pct:
                return
            self._flash_pct = pct
        self._log(line)

    def _flash_done(self):
        code = self.flasher.proc.returncode
        self.flasher.proc = None
        self.prep_btn.configure(state="normal")
        self.run_btn.configure(state="normal")
        if code == 0:
            self._msg("Placa pronta.")
            messagebox.showinfo(APP_TITLE, "Placa pronta.")
            if self.flash_resume:
                self._start()
        else:
            self._msg("Falha ao gravar o firmware.")
            messagebox.showerror(APP_TITLE, "Falha ao gravar — veja o Log.")

    def _stop(self):
        self.runner.stop()
        self._set_status()

    def _restart(self):
        self.runner.stop()
        self._start()

    def _set_status(self):
        if self.runner.running:
            extra = " · " + self.stat_extra if self.stat_extra else ""
            self.status_var.set("Rodando — F12 captura" + extra)
            self.run_btn.configure(text="Parar")
        else:
            self.status_var.set("Parado")
            self.run_btn.configure(text="Iniciar")

    def _on_bridge_line(self, line):
        self._log(line)
        sens = bd.parse_sens_line(line)
        if sens is not None:
            self.v_sens.set(round(sens, 4))     # dispara dirty via trace
            return
        if line.startswith(STATUS_PREFIXES):
            self.stat_extra = line
            self._set_status()

    def _poll(self):
        try:
            while True:
                self._on_bridge_line(self.runner.q.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                self._on_flash_line(self.flasher.q.get_nowait())
        except queue.Empty:
            pass
        if self.flasher.proc is not None and not self.flasher.running:
            self._flash_done()
        if self.runner.proc is not None and not self.runner.running:
            code = self.runner.proc.returncode
            self.runner.proc = None
            self._msg("Bridge encerrou (código %s)." % code)
        self._set_status()
        self.after(100, self._poll)

    def _on_close(self):
        if self.flasher.running and not messagebox.askyesno(
                APP_TITLE, "A gravação do firmware está em andamento. "
                "Interromper agora pode deixar a placa sem firmware. Sair mesmo assim?"):
            return
        if not self._confirm_discard():
            return
        self.flasher.kill()
        self.runner.stop()
        self.destroy()


def selftest():
    import tempfile
    import traceback
    tmp = tempfile.mkdtemp(prefix="kbmtest")
    app = None
    try:
        app = App(pf.ProfileStore(base=tmp))
        assert app.name == pf.DEFAULT_NAME, app.name
        assert app.rows["R1"][0] == "g"

        class Ev:
            keycode, keysym = 0x47, "g"
        app.waiting = ("B", 0)
        app._on_key(Ev)
        assert app.rows["B"][0] == "g" and "g" not in app.rows["R1"], app.rows["B"]
        assert app.dirty and app.title().startswith("*")
        assert "saiu de R" in app.msg_var.get(), app.msg_var.get()

        class F12:
            keycode, keysym = 0x7B, "F12"
        app.waiting = ("A", 0)
        app._on_key(F12)
        assert app.rows["A"][0] != "f12"
        app.update()
        app._on_bridge_line("SENS deg_per_count=0.0550")
        assert abs(app.v_sens.get() - 0.055) < 1e-9
        assert app.save() and not app.dirty
    except Exception:
        traceback.print_exc()
        if app is not None:
            app.destroy()
        return 1
    app.after(1500, app.destroy)
    app.mainloop()
    return 0


def _fix_std_streams():
    for fd, name, mode in ((0, "stdin", "r"), (1, "stdout", "w"), (2, "stderr", "w")):
        if getattr(sys, name) is None:
            try:
                kw = {"buffering": 1} if mode == "w" else {}
                f = open(fd, mode, encoding="utf-8", closefd=False, **kw)
            except OSError:
                f = open(os.devnull, mode)
            setattr(sys, name, f)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--bridge":
        _fix_std_streams()
        import kbm_bridge
        kbm_bridge.main(argv[1:])
        return 0
    if argv and argv[0] == "--flash":
        _fix_std_streams()
        import flasher
        return flasher.run(argv[1])
    if "--selftest" in argv:
        return selftest()
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
