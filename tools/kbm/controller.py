"""Estado e logica do Switch KBM, sem UI: perfil atual, teclas, ajustes, bridge e gravacao."""
import collections
import queue
import re
import sys
import tempfile
import threading
from pathlib import Path

import bindings as bd
import profiles as pf
import updater
from flasher import FIRMWARE_VERSION
from mapping import display_name
from runners import BridgeRunner, FlashRunner, list_ports, pick_default_port

APP_TITLE = "Switch KBM"
APP_VERSION = "1.0.1"
REPO_URL = "https://github.com/Carlos-Gabryel/switch-kbm"
AIM_LABELS = {"gyro": "Giroscópio", "stick": "Analógico direito"}
STATUS_PREFIXES = ("CAPTURADO", "LIBERADO", "Modo de mira",
                   "Sensibilidade")
CAPTURE_HINT = "Pressione a tecla (ou clique/roda do mouse). Esc cancela."
NO_PORT_MSG = "Selecione a porta COM da placa ESP32."
LOG_LINES = 500
FIRMWARE_RE = re.compile(r"^FIRMWARE v(\d+)\s*$")
FIRMWARE_OLD_MSG = "Firmware da placa desatualizado — vá em Placa › Preparar placa"


class Controller:
    def __init__(self, store=None):
        self.store = store or pf.ProfileStore()
        self.runner = BridgeRunner()
        self.flasher = FlashRunner()
        self.name = ""
        self.base = {}
        self.rows = bd.empty_rows()
        self.settings = {}          # aim (rotulo), sens, invh, invv, walk, wheel (valores crus)
        self.dirty = False
        self.loading = False
        self.waiting = None         # (row_id, slot) aguardando uma tecla
        self.msg = ""
        self.ports = []
        self.port = ""              # dispositivo selecionado (ex.: COM4)
        self.stat_extra = ""
        self.flash_resume = False
        self.flash_pct = -1         # ultimo multiplo de 10 logado
        self.flash_progress = None  # 0..1 enquanto grava (None = parado)
        self.log = collections.deque(maxlen=LOG_LINES)
        self.log_seq = 0            # cresce a cada linha (a UI detecta novidade)
        self.fw_version = None      # versao do firmware informada pela placa (None = ainda nao sei)
        self.update_state = "idle"  # idle | checking | uptodate | available | downloading | error
        self.update_release = None
        self.update_error = ""
        self.update_progress = 0.0
        self.update_ready = False   # o .exe novo ja foi trocado e relancado: a UI deve fechar
        st = self.store.load_settings()
        names = self.store.names()
        last = st.get("last_profile")
        self.load_profile(last if last in names else names[0])
        self.refresh_ports(st.get("port"))

    # ---------------- estado ----------------
    @property
    def names(self):
        return self.store.names()

    @property
    def flashing(self):
        return self.flasher.running

    def set_dirty(self, d=True):
        if not self.loading:
            self.dirty = d

    def set_setting(self, key, value):
        self.settings[key] = value
        self.set_dirty()

    def load_profile(self, name):
        self.loading = True
        try:
            data = self.store.load(name)
            self.name = name
            self.apply_data(data)
        finally:
            self.loading = False
        self.dirty = False
        self.store.save_settings(last_profile=name)

    def apply_data(self, data):
        self.base = data
        self.rows = bd.profile_to_rows(data)
        d = bd.SETTING_DEFAULTS
        self.settings = {
            "aim": AIM_LABELS.get(data.get("aim_mode", "gyro"), AIM_LABELS["gyro"]),
            "sens": round(float(data.get("deg_per_count", d["deg_per_count"])) *
                          float(data.get("gyro_sensitivity", 1.0)), 4),
            "invh": not data.get("invert_yaw", True),
            "invv": not data.get("invert_pitch", True),
            "walk": round(float(data.get("walk_scale", d["walk_scale"])), 3),
            "wheel": float(data.get("wheel_pulse_ms", d["wheel_pulse_ms"])),
        }
        self.waiting = None

    @staticmethod
    def _num(value, default):
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return default

    def collect(self):
        s = self.settings
        s = {
            "aim_mode": "stick" if s.get("aim") == AIM_LABELS["stick"] else "gyro",
            "deg_per_count": round(max(0.001, self._num(s.get("sens"), 0.05)), 4),
            "gyro_sensitivity": 1.0,
            "invert_yaw": not s.get("invh"),
            "invert_pitch": not s.get("invv"),
            "walk_scale": round(min(0.95, max(0.1, self._num(s.get("walk"), 0.5))), 3),
            "wheel_pulse_ms": max(10.0, self._num(s.get("wheel"), 80)),
        }
        return bd.rows_to_profile(self.rows, s, self.base)

    # ---------------- teclas ----------------
    def start_capture(self, rid, slot):
        if self.waiting:
            return
        self.waiting = (rid, slot)
        self.msg = CAPTURE_HINT

    def cancel_capture(self, msg="Cancelado."):
        self.waiting = None
        self.msg = msg

    def on_capture(self, kind, value=None):
        """Resultado da captura: kind = 'name' | 'cancel' | 'error'."""
        if not self.waiting:
            return
        if kind == "cancel":
            self.cancel_capture(value or "Cancelado.")
        elif kind == "error":
            self.msg = value or ""      # tecla nao suportada: continua esperando
        else:
            rid, slot = self.waiting
            self.assign(rid, slot, value)

    def assign(self, rid, slot, name):
        self.waiting = None
        try:
            new, moved = bd.assign_key(self.rows, rid, slot, name)
        except ValueError as e:
            self.msg = "Aviso: %s" % e
            return
        if new != self.rows:
            self.rows = new
            self.set_dirty()
        self.msg = "%s saiu de %s" % (display_name(name), bd.ROW_LABELS[moved]) if moved else ""

    def clear_slot(self, rid, slot):
        self.waiting = None
        self.rows = bd.clear_slot(self.rows, rid, slot)
        self.set_dirty()

    def clear_row(self, rid):
        self.waiting = None
        self.rows = bd.clear_row(self.rows, rid)
        self.set_dirty()

    def extras(self, rid):
        more = [display_name(k) for k in self.rows[rid][bd.SLOTS:] if k]
        return ("+ " + ", ".join(more)) if more and rid in bd.BUTTON_IDS else ""

    # ---------------- perfis ----------------
    def switch(self, name):
        """Carrega o perfil; reinicia o bridge se estava rodando (devolve erro de start ou None)."""
        self.load_profile(name)
        if self.runner.running:
            return self.restart()
        return None

    def new_profile(self, name):
        return self.store.create(name)          # ValueError em nome invalido/duplicado

    def dup_profile(self, name):
        return self.store.create(name, self.collect())

    def rename(self, new_name):
        new = self.store.rename(self.name, new_name)    # ValueError / OSError
        self.name = new
        self.store.save_settings(last_profile=new)
        return new

    def delete(self):
        self.store.delete(self.name)            # ValueError (ex.: ultimo perfil)
        self.dirty = False
        return self.switch(self.store.names()[0])

    def save(self, restart=True):
        """True se salvou; levanta OSError se falhar."""
        data = self.collect()
        self.store.save(self.name, data)
        self.base = data
        self.dirty = False
        self.msg = "Perfil salvo."
        if restart and self.runner.running:
            self.restart()
        return True

    def restore_defaults(self):
        self.loading = True
        try:
            self.apply_data(pf.default_profile())
        finally:
            self.loading = False
        self.set_dirty()

    # ---------------- portas ----------------
    def refresh_ports(self, preferred=None):
        if not isinstance(preferred, str):
            preferred = None
        self.ports = list_ports()
        want = preferred or self.port or pick_default_port(self.ports)
        self.port = next((dev for dev, _ in self.ports if dev == want), "")

    def set_port(self, dev):
        self.port = dev
        self.store.save_settings(port=dev)

    # ---------------- bridge ----------------
    def add_log(self, line):
        self.log.append(line)
        self.log_seq += 1

    @property
    def running(self):
        return self.runner.running

    def start(self):
        """Inicia o bridge. Retorna None ou (tipo, mensagem) com tipo 'warn' | 'error'."""
        if self.flasher.running:
            return "warn", "Aguarde o fim da gravação do firmware."
        if not self.port:
            return "warn", NO_PORT_MSG
        if self.dirty:
            try:
                self.save(restart=False)
            except OSError as e:
                return "error", "Falha ao salvar: %s" % e
        try:
            self.runner.start(self.port, self.store.path(self.name))
        except OSError as e:
            return "error", "Não foi possível iniciar o bridge: %s" % e
        self.stat_extra = ""
        self.fw_version = None
        return None

    def stop(self):
        self.runner.stop()

    def toggle_capture(self, before=None):
        """Alterna a captura de mouse/teclado no bridge (o mesmo que F12). before(pid) roda antes do envio.
        Devolve True se enviou."""
        if not self.runner.running:
            return False
        if before:
            before(self.runner.proc.pid)
        self.runner.send("capture")
        return True

    def restart(self):
        self.runner.stop()
        return self.start()

    @property
    def firmware_old(self):
        """True se a placa informou um firmware mais antigo que o embutido neste programa."""
        return self.fw_version is not None and self.fw_version < FIRMWARE_VERSION

    def on_bridge_line(self, line):
        self.add_log(line)
        m = FIRMWARE_RE.match(line)
        if m:
            self.fw_version = int(m.group(1))
            return
        sens = bd.parse_sens_line(line)
        if sens is not None:
            self.set_setting("sens", round(sens, 4))    # marca dirty como antes
            return
        if line.startswith(STATUS_PREFIXES):
            self.stat_extra = line

    # ---------------- gravacao do firmware ----------------
    def prepare_check(self):
        """None se pode gravar, senao (tipo, mensagem)."""
        if self.flasher.running:
            return "busy", ""
        if not self.port:
            return "warn", NO_PORT_MSG
        return None

    def flash(self):
        """Para o bridge (guardando se deve voltar) e inicia a gravacao. None ou (tipo, msg)."""
        self.flash_resume = self.runner.running
        if self.flash_resume:
            self.stop()
        try:
            self.flasher.start(self.port)
        except OSError as e:
            return "error", "Não foi possível iniciar a gravação: %s" % e
        self.flash_pct = -1
        self.flash_progress = 0.0
        self.msg = "Gravando firmware..."
        return None

    def on_flash_line(self, line):
        m = re.search(r"\((\d+) ?%\)", line)
        if m and line.startswith("Writing at"):
            self.flash_progress = int(m.group(1)) / 100.0
            pct = int(m.group(1)) // 10 * 10
            if pct == self.flash_pct:
                return
            self.flash_pct = pct
        self.add_log(line)

    def flash_done(self):
        """Fim da gravacao. Retorna (ok, resume_error): resume_error = (tipo, msg) do restart."""
        code = self.flasher.proc.returncode
        self.flasher.proc = None
        self.flash_progress = None
        if code == 0:
            self.msg = "Placa pronta."
            self.fw_version = None      # a placa informa de novo quando o bridge reconectar
            return True, (self.start() if self.flash_resume else None)
        self.msg = "Falha ao gravar o firmware."
        return False, None

    def poll(self):
        """Esvazia as filas dos subprocessos. Retorna lista de eventos para a UI:
        ('flash_done', ok, resume_error) | ('bridge_exit', code)."""
        events = []
        try:
            while True:
                self.on_bridge_line(self.runner.q.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                self.on_flash_line(self.flasher.q.get_nowait())
        except queue.Empty:
            pass
        if self.flasher.proc is not None and not self.flasher.running:
            ok, err = self.flash_done()
            events.append(("flash_done", ok, err))
        if self.runner.proc is not None and not self.runner.running:
            code = self.runner.proc.returncode
            self.runner.proc = None
            self.msg = "Bridge encerrou (código %s)." % code
            events.append(("bridge_exit", code))
        return events

    # ---------------- atualizacao do programa ----------------
    def check_update(self, opener=None):
        """Consulta o GitHub (bloqueante; a UI chama por start_check). Nunca levanta."""
        self.update_state, self.update_error = "checking", ""
        try:
            rel = updater.latest(**({"opener": opener} if opener else {}))
            if updater.newer(rel, APP_VERSION):
                self.update_release, self.update_state = rel, "available"
            else:
                self.update_release, self.update_state = None, "uptodate"
        except Exception as e:      # UpdateError ou qualquer outra: nunca derruba a UI
            self.update_state, self.update_error = "error", str(e)
            self.add_log("Atualização: %s" % e)
        return self.update_state

    def start_check(self):
        if self.update_state in ("checking", "downloading"):
            return False
        self.update_state = "checking"
        threading.Thread(target=self.check_update, daemon=True).start()
        return True

    def update_blocker(self):
        """None se pode atualizar agora, senao o motivo."""
        if self.flasher.running:
            return "Aguarde o fim da gravação do firmware."
        if not updater.can_apply():
            return updater.NOT_FROZEN_MSG
        if self.update_state != "available" or self.update_release is None:
            return "Nenhuma atualização disponível."
        return None

    def install_update(self, exe=None, opener=None, launch=None, wait=False):
        """Para o bridge e baixa+troca o exe em segundo plano. Devolve o motivo da recusa ou None."""
        why = self.update_blocker()
        if why:
            return why
        self.stop()
        self.update_state, self.update_progress, self.update_error = "downloading", 0.0, ""
        th = threading.Thread(target=self._install, args=(exe, opener, launch), daemon=True)
        th.start()
        if wait:
            th.join()
        return None

    def _install(self, exe, opener, launch):
        try:
            exe = Path(exe or sys.executable)
            kw = {"opener": opener} if opener else {}
            new = updater.download(self.update_release, Path(tempfile.gettempdir()) / "SwitchKBM-update",
                                   progress=lambda f: setattr(self, "update_progress", f), **kw)
            if self.flasher.running:        # nunca troca o programa no meio da gravacao
                raise updater.UpdateError("a gravação do firmware começou; tente de novo depois")
            updater.apply(new, exe, **({"launch": launch} if launch else {}))
            self.update_ready = True
        except (updater.UpdateError, OSError) as e:
            self.update_state, self.update_error = "error", str(e)
            self.add_log("Atualização: %s" % e)

    # ---------------- status e encerramento ----------------
    def status(self):
        """(chave, titulo, detalhe): chave = 'stopped' | 'running' | 'flashing'."""
        if self.flasher.running:
            return "flashing", "Gravando firmware", self.port or "—"
        if self.runner.running:
            return "running", "Rodando", " · ".join(x for x in (self.port, self.stat_extra or
                                                              "F12 captura o mouse") if x)
        return "stopped", "Parado", " · ".join(x for x in (self.port, "F12 captura o mouse") if x)

    def shutdown(self):
        self.flasher.kill()
        self.runner.stop()
