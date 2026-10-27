"""A janela: barra lateral (abas + cartao de status com Iniciar/Parar) e a view da aba atual."""
from __future__ import annotations

import asyncio
import ctypes
import sys
import traceback
from pathlib import Path

import flet as ft

from capture import Capture
import updater
from controller import APP_TITLE, APP_VERSION, FIRMWARE_OLD_MSG, REPO_URL, Controller
from ui import theme as t

NAV = (("controles", "Controles", "gamepad-2"), ("ajustes", "Ajustes", "settings"),
       ("placa", "Placa", "cpu"))


def assets_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "ui" / "assets"
    return Path(__file__).resolve().parent / "assets"


class Shell:
    def __init__(self, page: ft.Page, ctrl: Controller, tab: str = "controles"):
        self.page, self.ctrl = page, ctrl
        self.capture = Capture()
        self.current = tab if tab in [k for k, _, _ in NAV] else "controles"
        from ui.views.ajustes import AjustesView
        from ui.views.controles import ControlesView
        from ui.views.placa import PlacaView
        self.views = {"controles": ControlesView(self), "ajustes": AjustesView(self),
                      "placa": PlacaView(self)}
        self.nav = ft.Column(spacing=4)
        self.status_box = ft.Container()
        self.fw_box = ft.Container(visible=False, padding=ft.Padding(0, 0, 0, 8),
                                   content=t.notice(FIRMWARE_OLD_MSG))
        self.update_bar = ft.Container(visible=False, bgcolor=t.CARD, padding=ft.Padding(24, 8, 24, 8),
                                       border=ft.Border(bottom=ft.BorderSide(1, t.BORDER)))
        self.run_btn = t.button("Iniciar", self.toggle_run, icon_name="play")
        self.cap_btn = t.button("Capturar mouse e teclado", self.toggle_capture, primary=False,
                                icon_name="mouse-pointer-2")
        self.cap_btn.tooltip = "Mesmo que apertar F12 (F12 também solta)"
        self.cap_btn.style.padding = ft.Padding(10, 8, 10, 8)
        self.body = ft.Container(expand=True, padding=24)
        self._sig = None
        sidebar = ft.Container(
            width=t.SIDEBAR_WIDTH, bgcolor=t.SIDEBAR, padding=ft.Padding(12, 16, 12, 16),
            border=ft.Border(right=ft.BorderSide(1, t.BORDER)),
            content=ft.Column([ft.WindowDragArea(ft.Container(t.brand(), padding=ft.Padding(6, 0, 0, 14))), self.nav,
                               ft.Container(expand=True), self.fw_box, self.status_box,
                               ft.Container(ft.Column([self.run_btn, self.cap_btn], spacing=8,
                                                      horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                            padding=ft.Padding(0, 8, 0, 0)),
                               self._credit()],
                              spacing=0, expand=True))
        page.window.icon = str(assets_dir() / ("icon.ico" if sys.platform == "win32" else "icon.png"))
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        self._build_title_bar()
        page.add(ft.Row([sidebar, ft.Column([self.title_bar, self.update_bar, self.body], spacing=0, expand=True)],
                        spacing=0, expand=True))
        self.render(full=True)
        self.ctrl.start_check()         # em segundo plano; falha so vai para o log
        page.run_task(self._poll)

    # ---- atualizacao do programa ----
    def update_now(self, e=None) -> None:
        """Pede confirmacao (perfil nao salvo) e baixa+troca o .exe; a janela fecha quando o novo abrir."""
        why = self.ctrl.update_blocker()
        if why:
            self.info(why)
            return

        def go():
            problem = self.ctrl.install_update()
            if problem:
                self.info(problem)
            self.render()
        self.confirm_discard(go)

    def _update_row(self) -> ft.Row:
        c = self.ctrl
        rel = c.update_release
        if c.update_state == "downloading":
            return ft.Row([t.icon("download", 16, t.GREEN),
                           t.text(f"Baixando a versão {rel.tag.lstrip('v')}…", 13),
                           ft.ProgressBar(value=c.update_progress, color=t.ACCENT, bgcolor=t.FIELD,
                                          width=180)], spacing=10)
        return ft.Row([t.icon("download", 16, t.GREEN),
                       t.text(f"Nova versão {rel.tag.lstrip('v')} disponível", 13), ft.Container(expand=True),
                       t.button("Atualizar", self.update_now, disabled=c.flashing or not updater.can_apply())],
                      spacing=10)

    def _credit(self) -> ft.Control:
        """Linha discreta de credito: abre o repositorio no navegador."""
        async def open_repo(e=None):
            await self.page.launch_url(REPO_URL)
        row = ft.Row([t.muted("By Carlos Gabryel", 11), t.icon("external-link", 11, t.FAINT),
                      t.text(f"v{APP_VERSION}", size=10, color=t.FAINT)],
                     spacing=5, alignment=ft.MainAxisAlignment.CENTER)
        return ft.Container(ft.GestureDetector(row, on_tap=open_repo, mouse_cursor=ft.MouseCursor.CLICK),
                            padding=ft.Padding(0, 10, 0, 0), tooltip=REPO_URL)

    # ---- infraestrutura ----
    def ui(self, fn) -> None:
        """Roda fn no laco da pagina (de qualquer thread)."""
        async def call():
            try:
                fn()
            except Exception:
                traceback.print_exc()
        self.page.run_task(call)

    # ---- dialogos ----
    def dialog(self, title: str, content, actions) -> None:
        self.page.show_dialog(ft.AlertDialog(modal=True, bgcolor=t.CARD, title=t.text(title, 16, bold=True),
                                             content=content, actions=actions))

    def close_dialog(self, e=None) -> None:
        self.page.pop_dialog()

    def info(self, message: str) -> None:
        self.dialog(APP_TITLE, t.muted(message, 13), [t.button("OK", self.close_dialog)])

    def ask(self, message: str, on_yes, yes: str = "Sim", no: str = "Não") -> None:
        def go(e=None):
            self.close_dialog()
            on_yes()
        self.dialog(APP_TITLE, t.muted(message, 13),
                    [t.button(no, self.close_dialog, primary=False), t.button(yes, go)])

    def ask_name(self, title: str, initial: str, on_ok) -> None:
        import profiles as pf
        field = ft.TextField(value=initial, autofocus=True, **t.field_style())

        def go(e=None):
            self.close_dialog()
            name = pf.clean_name(field.value) if field.value else None
            if name:
                on_ok(name)
        field.on_submit = go
        self.dialog(title, ft.Container(field, width=320),
                    [t.button("Cancelar", self.close_dialog, primary=False), t.button("OK", go)])

    def confirm_discard(self, then) -> None:
        """Chama then() se pode seguir (nada a salvar, salvou ou descartou)."""
        if not self.ctrl.dirty:
            then()
            return

        def save(e=None):
            self.close_dialog()
            if self.save(restart=False):
                then()

        def discard(e=None):
            self.close_dialog()
            then()
        self.dialog(APP_TITLE, t.muted("Há alterações não salvas no perfil \"%s\". Salvar antes de "
                                       "continuar?" % self.ctrl.name, 13),
                    [t.button("Cancelar", self.close_dialog, primary=False),
                     t.button("Descartar", discard, primary=False), t.button("Salvar", save)])

    def save(self, restart: bool = True) -> bool:
        try:
            self.ctrl.save(restart=restart)
        except OSError as e:
            self.info("Falha ao salvar: %s" % e)
            return False
        self.render()
        return True

    def report(self, problem) -> None:
        """problem = None | (tipo, mensagem) devolvido pelo controller."""
        if problem:
            self.info(problem[1])

    # ---- iniciar / parar ----
    def toggle_run(self, e=None) -> None:
        if self.ctrl.running:
            self.ctrl.stop()
        else:
            self.report(self.ctrl.start())
        self.render()

    def toggle_capture(self, e=None) -> None:
        def allow(pid):     # nossa janela esta em primeiro plano: deixa o bridge assumir o foco
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(pid)
            except Exception:
                pass
        self.ctrl.toggle_capture(allow)

    # ---- janela ----
    def _build_title_bar(self) -> None:
        """Barra de título própria (a nativa fica escondida): arrastar + minimizar/maximizar/fechar."""
        self.max_icon = ft.Container(content=t.icon("square", 14))
        self.title_bar = ft.Row([
            ft.WindowDragArea(ft.Container(height=36), expand=True),
            self._window_button(t.icon("minus", 16), self._minimize),
            self._window_button(self.max_icon, self._toggle_max),
            self._window_button(t.icon("x", 16), self._close, danger=True),
        ], spacing=0, height=36)

    def _window_button(self, content, on_click, danger: bool = False) -> ft.Control:
        hover = "#C42B1C" if danger else t.HOVER

        def on_hover(e):
            e.control.bgcolor = hover if e.data in (True, "true") else None
            e.control.update()
        return t.clickable(ft.Container(content=content, width=46, height=36, alignment=ft.Alignment.CENTER,
                                        on_click=on_click, on_hover=on_hover))

    def _minimize(self, e=None) -> None:
        self.page.window.minimized = True
        self.page.update()

    def _toggle_max(self, e=None) -> None:
        self.page.window.maximized = not self.page.window.maximized
        self.page.update()

    def _close(self, e=None) -> None:
        # dispara o evento CLOSE (prevent_close) -> _on_window_event pede confirmação e chama _quit
        self.page.run_task(self.page.window.close)

    def _on_window_event(self, e) -> None:
        if e.type in (ft.WindowEventType.MAXIMIZE, ft.WindowEventType.UNMAXIMIZE):
            maximized = e.type == ft.WindowEventType.MAXIMIZE
            self.page.window.maximized = maximized
            self.max_icon.content = t.icon("copy" if maximized else "square", 14)
            self.max_icon.update()
            return
        if e.type != ft.WindowEventType.CLOSE:
            return
        if self.ctrl.flashing:
            self.ask("A gravação do firmware está em andamento. Interromper agora pode deixar a placa "
                     "sem firmware. Sair mesmo assim?", lambda: self.confirm_discard(self._quit),
                     yes="Sair")
        else:
            self.confirm_discard(self._quit)

    def _quit(self) -> None:
        self.capture.cancel()
        self.ctrl.shutdown()
        self.page.run_task(self.page.window.destroy)

    # ---- navegacao e desenho ----
    def navigate(self, key: str) -> None:
        self.current = key
        self.render(full=True)

    def render(self, full: bool = False) -> None:
        c = self.ctrl
        self.nav.controls = [t.nav_item(label, icon, key == self.current,
                                        lambda e, k=key: self.navigate(k)) for key, label, icon in NAV]
        key, title, detail = c.status()
        self.status_box.content = t.status_card(key, title, detail)
        self.run_btn.content = "Parar" if c.running else "Iniciar"
        self.run_btn.icon = t.icon("pause" if c.running else "play", 16, "#FFFFFF")
        self.run_btn.disabled = c.flashing
        self.cap_btn.disabled = not c.running
        self.fw_box.visible = c.firmware_old
        self.update_bar.visible = (c.update_state in ("available", "downloading") and c.update_release is not None
                                   and updater.can_apply())
        if self.update_bar.visible:
            self.update_bar.content = self._update_row()
        if not c.waiting and self.capture.active:
            self.capture.cancel()
        view = self.views[self.current]
        if full or self.body.content is not view.control:
            self.body.content = view.control
        view.refresh()
        self.page.update()

    def _signature(self):
        c = self.ctrl
        return (c.status(), c.port, c.msg, c.log_seq, c.flash_progress, c.dirty, c.waiting, c.running,
                c.settings.get("sens"), c.name, c.flashing, c.firmware_old, c.update_state,
                round(c.update_progress, 2), c.update_error)

    async def _poll(self) -> None:
        while True:
            try:
                if self.ctrl.update_ready:      # o .exe novo ja abriu: fecha este sem perguntar
                    self.ctrl.update_ready = False
                    self._quit()
                    return
                for ev in self.ctrl.poll():
                    if ev[0] == "flash_done":
                        self._flash_finished(ev[1], ev[2])
                sig = self._signature()
                if sig != self._sig:
                    self._sig = sig
                    self.render()
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(0.1)

    def _flash_finished(self, ok: bool, resume_error) -> None:
        if ok:
            self.info("Placa pronta.")
            self.report(resume_error)
        else:
            self.info("Falha ao gravar — veja o Log.")


def run() -> None:
    tab = sys.argv[sys.argv.index("--tab") + 1] if "--tab" in sys.argv else "controles"   # so para depuracao
    if getattr(sys, "frozen", False):
        updater.cleanup(Path(sys.executable))       # apaga o SwitchKBM.exe.old de uma atualizacao anterior
    ctrl = Controller()

    def main(page: ft.Page) -> None:
        t.apply_page(page)
        Shell(page, ctrl, tab)

    try:
        ft.run(main, assets_dir=str(assets_dir()))
    finally:
        ctrl.shutdown()
