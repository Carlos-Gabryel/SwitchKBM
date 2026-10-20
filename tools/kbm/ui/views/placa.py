"""Placa: porta COM, gravacao do firmware e log."""
from __future__ import annotations

import flet as ft

from controller import FIRMWARE_OLD_MSG
from ui import theme as t

LOG_MAX = 500


class PlacaView:
    def __init__(self, shell):
        self.shell, self.ctrl = shell, shell.ctrl
        self.port = ft.Dropdown(expand=True, on_select=self._pick, **t.field_style())
        self.prep = t.button("Preparar placa", self._prepare, icon_name="zap")
        self.bar = ft.ProgressBar(value=0, color=t.ACCENT, bgcolor=t.FIELD, visible=False)
        self.state = t.muted("", 12)
        self.fw_notice = ft.Container(content=t.notice(FIRMWARE_OLD_MSG, 12), visible=False)
        self.log = ft.ListView(expand=True, auto_scroll=True, spacing=0)
        self._seen = 0
        self.control = ft.Column([
            t.text("Placa", 22, bold=True),
            self.fw_notice,
            t.card(ft.Column([
                t.text("Porta", 14, bold=True),
                ft.Row([self.port, t.icon_button("refresh-cw", "Atualizar", self._refresh_ports)], spacing=8),
            ], spacing=10)),
            t.card(ft.Column([
                t.text("Firmware", 14, bold=True),
                t.muted("Grava na placa o firmware do Switch. Faça isso numa placa nova ou se ela parar "
                        "de responder. Não desconecte o cabo até terminar (~30 s).", 12),
                ft.Row([self.prep, self.state], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.bar,
            ], spacing=10)),
            t.card(ft.Column([t.text("Log", 14, bold=True),
                              ft.Container(self.log, bgcolor=t.FIELD, border_radius=t.RADIUS_SMALL,
                                           padding=8, expand=True)], spacing=8, expand=True),
                   expand=True),
        ], spacing=t.GAP, expand=True)

    def refresh(self) -> None:
        c = self.ctrl
        self.port.options = [ft.DropdownOption(key=dev, text=label) for dev, label in c.ports]
        self.port.value = c.port or None
        self.fw_notice.visible = c.firmware_old
        self.prep.disabled = c.flashing
        self.bar.visible = c.flash_progress is not None
        self.bar.value = c.flash_progress
        self.state.value = c.msg if (c.flashing or c.msg in ("Placa pronta.", "Falha ao gravar o firmware.")) else ""
        self._sync_log()

    def _sync_log(self) -> None:
        c = self.ctrl
        new = c.log_seq - self._seen
        if new <= 0:
            return
        lines = list(c.log)[-min(new, len(c.log)):]
        self._seen = c.log_seq
        self.log.controls.extend(ft.Text(line, size=11, font_family="Consolas", color=t.MUTED, selectable=True)
                                 for line in lines)
        del self.log.controls[:-LOG_MAX]

    def _pick(self, e) -> None:
        self.ctrl.set_port(e.control.value or "")
        self.shell.render()

    def _refresh_ports(self, e=None) -> None:
        self.ctrl.refresh_ports()
        self.shell.render()

    def _prepare(self, e=None) -> None:
        problem = self.ctrl.prepare_check()
        if problem:
            if problem[1]:
                self.shell.info(problem[1])
            return

        def go():
            self.shell.report(self.ctrl.flash())
            self.shell.render()
        self.shell.ask("Gravar o firmware na placa em %s? Não desconecte o cabo até terminar (~30 s)."
                       % self.ctrl.port, go, yes="Gravar")
