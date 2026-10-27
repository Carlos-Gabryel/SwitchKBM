"""Ajustes: inversao, andar devagar e pulso da roda."""
from __future__ import annotations

import flet as ft

import updater
from controller import APP_VERSION
from ui import theme as t

UPDATE_TEXT = {"idle": "", "checking": "Procurando…", "uptodate": "Você está na versão mais recente.",
               "downloading": "Baixando…"}


def _fmt(value, digits: int) -> str:
    try:
        return ("%." + str(digits) + "f") % float(value)
    except (TypeError, ValueError):
        return str(value)


class AjustesView:
    def __init__(self, shell):
        self.shell, self.ctrl = shell, shell.ctrl
        self.walk, self.walk_field = self._slider_pair("walk", 0.2, 0.9, 3)
        self.invh = self._switch("invh")
        self.invv = self._switch("invv")
        self.wheel = ft.TextField(width=90, text_align=ft.TextAlign.RIGHT,
                                  on_change=lambda e: self._set("wheel", e.control.value), **t.field_style())
        self.up_status = t.muted("", 12)
        self.up_check = t.button("Procurar atualização", self._check, primary=False, icon_name="refresh-cw")
        self.up_apply = t.button("Atualizar agora", self.shell.update_now, icon_name="download")
        self.up_bar = ft.ProgressBar(value=0, color=t.ACCENT, bgcolor=t.FIELD, visible=False)
        self.control = ft.Column([
            t.text("Ajustes", 22, bold=True),
            self._card("Inverter horizontal", "", self.invh),
            self._card("Inverter vertical", "", self.invv),
            self._card("Andar devagar", "Escala do analógico esquerdo enquanto a tecla está pressionada.",
                       ft.Row([self.walk, self.walk_field], spacing=10, expand=True), wide=True),
            self._card("Roda: pulso (ms)", "Quanto tempo o botão fica apertado a cada giro da roda.", self.wheel),
            t.card(ft.Column([
                ft.Row([t.text("Atualizações", 14, bold=True), t.muted(f"Versão atual {APP_VERSION}", 12)],
                       spacing=10),
                ft.Row([self.up_check, self.up_apply], spacing=10),
                self.up_status, self.up_bar,
            ], spacing=10)),
        ], spacing=t.GAP, expand=True, scroll=ft.ScrollMode.AUTO)

    def _slider_pair(self, key: str, lo: float, hi: float, digits: int):
        field = ft.TextField(width=90, text_align=ft.TextAlign.RIGHT,
                             on_change=lambda e, k=key: self._set(k, e.control.value), **t.field_style())
        slider = ft.Slider(min=lo, max=hi, expand=True, active_color=t.ACCENT, inactive_color=t.FIELD,
                           thumb_color=t.ACCENT,
                           on_change=lambda e, k=key, d=digits: self._slide(k, e.control.value, d))
        return slider, field

    def _switch(self, key: str) -> ft.Switch:
        return ft.Switch(active_color=t.ACCENT, on_change=lambda e, k=key: self._set(k, bool(e.control.value)))

    def _card(self, title: str, detail: str, control: ft.Control, wide: bool = False) -> ft.Container:
        label = ft.Column([t.text(title, 14, bold=True)] + ([t.muted(detail, 11)] if detail else []),
                          spacing=2, expand=not wide, width=230 if wide else None)
        return t.card(ft.Row([label, control], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER))

    def _set(self, key: str, value) -> None:
        self.ctrl.set_setting(key, value)
        self.shell.render()

    def _slide(self, key: str, value: float, digits: int) -> None:
        self.ctrl.set_setting(key, round(value, digits))
        self.shell.render()

    def _check(self, e=None) -> None:
        self.ctrl.start_check()
        self.shell.render()

    def _refresh_update(self) -> None:
        c = self.ctrl
        st = c.update_state
        if st == "available":
            text = f"Nova versão {c.update_release.tag.lstrip('v')} disponível."
            if not updater.can_apply():
                text += " " + updater.not_frozen_msg() + "."
        elif st == "error":
            text = "Não foi possível verificar/atualizar: %s" % c.update_error
        else:
            text = UPDATE_TEXT.get(st, "")
        if st != "available" and not updater.can_apply():
            text = (text + " " if text else "") + updater.not_frozen_msg() + "."
        self.up_status.value = text
        self.up_status.color = t.AMBER if st == "error" else t.MUTED
        busy = st in ("checking", "downloading")
        self.up_check.disabled = busy
        self.up_apply.visible = st in ("available", "downloading")
        self.up_apply.disabled = busy or c.flashing or not updater.can_apply()
        self.up_bar.visible = st == "downloading"
        self.up_bar.value = c.update_progress

    def refresh(self) -> None:
        self._refresh_update()
        s = self.ctrl.settings
        self.invh.value, self.invv.value = bool(s["invh"]), bool(s["invv"])
        for slider, field, key, digits in ((self.walk, self.walk_field, "walk", 3),):
            num = self.ctrl._num(s[key], slider.min)
            slider.value = min(slider.max, max(slider.min, num))
            if self.ctrl._num(field.value, None) != num:        # nao reescreve enquanto digita
                field.value = _fmt(num, digits)
        if self.ctrl._num(self.wheel.value, None) != self.ctrl._num(s["wheel"], None):
            self.wheel.value = _fmt(s["wheel"], 0)
