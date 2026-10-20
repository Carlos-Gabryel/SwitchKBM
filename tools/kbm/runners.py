"""Execucao do bridge e do gravador como subprocessos (sem UI)."""
import os
import queue
import subprocess
import sys
import threading

CREATE_NO_WINDOW = 0x08000000


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
