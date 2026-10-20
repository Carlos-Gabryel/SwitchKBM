"""Ajustes: mira, sensibilidade, inversao, andar devagar e pulso da roda."""
from __future__ import annotations

import flet as ft

from controller import AIM_LABELS
from ui import theme as t


def _fmt(value, digits: int) -> str:
    try:
        return ("%." + str(digits) + "f") % float(value)
    except (TypeError, ValueError):
        return str(value)


class AjustesView:
    def __init__(self, shell):
        self.shell, self.ctrl = shell, shell.ctrl
        self.aim = ft.Dropdown(
            width=220, on_select=lambda e: self._set("aim", e.control.value),
            options=[ft.DropdownOption(key=v, text=v) for v in AIM_LABELS.values()], **t.field_style())
        self.sens, self.sens_field = self._slider_pair("sens", 0.005, 0.3, 4)
        self.walk, self.walk_field = self._slider_pair("walk", 0.2, 0.9, 3)
        self.invh = self._switch("invh")
        self.invv = self._switch("invv")
        self.wheel = ft.TextField(width=90, text_align=ft.TextAlign.RIGHT,
                                  on_change=lambda e: self._set("wheel", e.control.value), **t.field_style())
        self.control = ft.Column([
            t.text("Ajustes", 22, bold=True),
            self._card("Modo de mira", "Quem controla o giroscópio e quem controla o analógico direito.", self.aim),
            self._card("Sensibilidade", "Graus por contagem do mouse (F7/F8 ajustam com o bridge rodando).",
                       ft.Row([self.sens, self.sens_field], spacing=10, expand=True), wide=True),
            self._card("Inverter horizontal", "", self.invh),
            self._card("Inverter vertical", "", self.invv),
            self._card("Andar devagar", "Escala do analógico esquerdo enquanto a tecla está pressionada.",
                       ft.Row([self.walk, self.walk_field], spacing=10, expand=True), wide=True),
            self._card("Roda: pulso (ms)", "Quanto tempo o botão fica apertado a cada giro da roda.", self.wheel),
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

    def refresh(self) -> None:
        s = self.ctrl.settings
        self.aim.value = s["aim"]
        self.invh.value, self.invv.value = bool(s["invh"]), bool(s["invv"])
        for slider, field, key, digits in ((self.sens, self.sens_field, "sens", 4),
                                           (self.walk, self.walk_field, "walk", 3)):
            num = self.ctrl._num(s[key], slider.min)
            slider.value = min(slider.max, max(slider.min, num))
            if self.ctrl._num(field.value, None) != num:        # nao reescreve enquanto digita
                field.value = _fmt(num, digits)
        if self.ctrl._num(self.wheel.value, None) != self.ctrl._num(s["wheel"], None):
            self.wheel.value = _fmt(s["wheel"], 0)
