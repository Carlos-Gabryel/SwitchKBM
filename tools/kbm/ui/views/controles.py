"""Controles: perfis e a lista de botoes do Switch -> teclas/mouse."""
from __future__ import annotations

import flet as ft

import bindings as bd
import profiles as pf
from controller import AIM_LABELS
from i18n import N_, tr
from mapping import display_name
from ui import theme as t

def _fmt(value, digits: int) -> str:
    try:
        return ("%." + str(digits) + "f") % float(value)
    except (TypeError, ValueError):
        return str(value)


WAIT_TEXT = N_("Pressione uma tecla… (Esc cancela)")
EXTRA_KEYS = ((N_("Botão lateral 1 do mouse"), "x1"), (N_("Botão lateral 2 do mouse"), "x2"),
              (N_("Roda ↑"), "wheel_up"), (N_("Roda ↓"), "wheel_down"), ("Esc", "esc"))


class ControlesView:
    def __init__(self, shell):
        self.shell, self.ctrl = shell, shell.ctrl
        self.cells: dict[tuple[str, int], tuple[ft.Container, ft.Text]] = {}
        self.extras: dict[str, ft.Text] = {}
        self.profile = ft.Dropdown(width=220, on_select=self._pick, **t.field_style())
        self.dirty_mark = t.text(tr("• não salvo"), 12, t.AMBER)
        self.msg = t.muted("", 12)
        self.aim = ft.Dropdown(
            expand=True, on_select=lambda e: self._set("aim", e.control.value),
            options=[ft.DropdownOption(key=v, text=tr(v)) for v in AIM_LABELS.values()], **t.field_style())
        self.sens_field = ft.TextField(width=80, text_align=ft.TextAlign.RIGHT,
                                       on_change=lambda e: self._set("sens", e.control.value), **t.field_style())
        self.sens = ft.Slider(mouse_cursor=t.CLICK, min=0.005, max=0.3, expand=True, active_color=t.ACCENT, inactive_color=t.FIELD,
                              thumb_color=t.ACCENT, on_change=lambda e: self._set("sens", round(e.control.value, 4)))
        self.ssens_field = ft.TextField(width=80, text_align=ft.TextAlign.RIGHT,
                                        on_change=lambda e: self._set("ssens", e.control.value), **t.field_style())
        self.ssens = ft.Slider(mouse_cursor=t.CLICK, min=0.1, max=3.0, expand=True, active_color=t.ACCENT, inactive_color=t.FIELD,
                               thumb_color=t.ACCENT, on_change=lambda e: self._set("ssens", round(e.control.value, 3)))
        self.sdz_field = ft.TextField(width=80, text_align=ft.TextAlign.RIGHT,
                                      on_change=lambda e: self._set("sdz", e.control.value), **t.field_style())
        self.sdz = ft.Slider(mouse_cursor=t.CLICK, min=0, max=200, divisions=200, expand=True, active_color=t.ACCENT, inactive_color=t.FIELD,
                             thumb_color=t.ACCENT, on_change=lambda e: self._set("sdz", int(round(e.control.value))))
        self.rows_col = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        self._build_rows()
        top = ft.Row([t.muted(tr("Perfil"), 12), self.profile,
                      t.icon_button("plus", tr("Novo"), self._new), t.icon_button("copy", tr("Duplicar"), self._dup),
                      t.icon_button("pencil", tr("Renomear"), self._rename),
                      t.icon_button("trash-2", tr("Excluir"), self._delete)],
                     spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        actions = ft.Row([t.button(tr("Salvar"), self._save, icon_name="save"),
                          t.button(tr("Restaurar padrão"), self._restore, primary=False, icon_name="rotate-ccw"),
                          self.dirty_mark], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        # so aparece o card de sensibilidade do modo de mira selecionado (ver refresh)
        self.gyro_card = t.card(ft.Column([t.text(tr("Sensibilidade do giroscópio"), 14, bold=True),
                                           t.muted(tr("Graus por contagem do mouse (F7/F8 ajustam)."), 11),
                                           ft.Row([self.sens, self.sens_field], spacing=8)], spacing=6),
                                expand=True)
        self.stick_card = t.card(ft.Column([t.text(tr("Sensibilidade do analógico"), 14, bold=True),
                                            t.muted(tr("Maior = mais rápido; F7/F8 ajustam."), 11),
                                            ft.Row([self.ssens, self.ssens_field], spacing=8),
                                            t.muted(tr("Zona morta do jogo (0–200). Ajuste até o menor movimento do mouse mexer a mira."), 11),
                                            ft.Row([self.sdz, self.sdz_field], spacing=8)], spacing=6),
                                 expand=True)
        aim_cards = ft.Row([
            t.card(ft.Column([t.text(tr("Modo de mira"), 14, bold=True),
                              t.muted(tr("Quem controla o giroscópio e o analógico direito."), 11), self.aim],
                             spacing=6), expand=True),
            self.gyro_card, self.stick_card,
        ], spacing=t.GAP, vertical_alignment=ft.CrossAxisAlignment.START)
        self.control = ft.Column(
            [t.text(tr("Controles"), 22, bold=True), top, actions, aim_cards, self.msg,
             t.card(self.rows_col, padding=10, expand=True)], spacing=t.GAP, expand=True)

    # ---- construcao ----
    def _build_rows(self) -> None:
        col = self.rows_col.controls
        col.append(self._header(tr("Botão do Switch"), tr("Tecla 1"), tr("Tecla 2")))
        for rid, label in bd.BUTTON_ROWS:
            col.append(self._row(rid, tr(label), 2))
        col.append(ft.Container(height=6))
        col.append(t.text(tr("Movimento (analógico esquerdo)"), 13, bold=True))
        for rid, label in bd.MOVE_ROWS:
            col.append(self._row(rid, tr(label), 1))
        col.append(ft.Container(t.muted(tr("Mira: mouse + setas (o modo de mira define quem controla o "
                                           "giroscópio e quem controla o analógico direito)."), 11),
                                padding=ft.Padding(4, 8, 4, 4)))

    def _header(self, a: str, b: str, c: str) -> ft.Row:
        return ft.Row([ft.Container(t.muted(a, 11), width=170), ft.Container(t.muted(b, 11), expand=True),
                       ft.Container(t.muted(c, 11), expand=True), ft.Container(width=32)], spacing=8)

    def _row(self, rid: str, label: str, nslots: int) -> ft.Row:
        cells = []
        for slot in range(2):
            if slot >= nslots:
                cells.append(ft.Container(expand=True))
                continue
            label_text = ft.Text("", size=12, color=t.TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
            box = ft.Container(label_text, height=30, padding=ft.Padding(10, 0, 10, 0), expand=True,
                               bgcolor=t.FIELD, border_radius=t.RADIUS_SMALL, border=t.border(),
                               alignment=ft.Alignment.CENTER)
            self.cells[(rid, slot)] = (box, label_text)
            cells.append(ft.GestureDetector(
                content=box, expand=True, mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda e, a=rid, b=slot: self._cell_click(a, b),
                on_secondary_tap=lambda e, a=rid, b=slot: self._cell_menu(a, b)))
        extra = t.muted("", 10)
        self.extras[rid] = extra
        name = ft.Column([t.text(label, 13), extra], spacing=0, tight=True)
        return ft.Row([ft.Container(name, width=170), *cells,
                       t.icon_button("x", tr("Limpar a linha"), lambda e, a=rid: self._clear(a))],
                      spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # ---- desenho ----
    def refresh(self) -> None:
        c = self.ctrl
        self.profile.options = [ft.DropdownOption(key=n, text=pf.label(n)) for n in c.names]
        self.profile.value = c.name
        self.dirty_mark.visible = c.dirty
        self.msg.value = c.msg
        s = c.settings
        self.aim.value = s["aim"]
        stick = s["aim"] == AIM_LABELS["stick"]
        self.gyro_card.visible = not stick
        self.stick_card.visible = stick
        num = c._num(s["sens"], self.sens.min)
        self.sens.value = min(self.sens.max, max(self.sens.min, num))
        if c._num(self.sens_field.value, None) != num:      # nao reescreve enquanto digita
            self.sens_field.value = _fmt(num, 4)
        num = c._num(s["ssens"], self.ssens.min)
        self.ssens.value = min(self.ssens.max, max(self.ssens.min, num))
        if c._num(self.ssens_field.value, None) != num:
            self.ssens_field.value = _fmt(num, 3)
        num = c._num(s["sdz"], self.sdz.min)
        self.sdz.value = min(self.sdz.max, max(self.sdz.min, num))
        if c._num(self.sdz_field.value, None) != num:
            self.sdz_field.value = _fmt(num, 0)
        for (rid, slot), (box, label) in self.cells.items():
            if c.waiting == (rid, slot):
                label.value, label.color = tr(WAIT_TEXT), t.ACCENT
                box.border = t.border(t.ACCENT)
            else:
                k = c.rows[rid][slot] if slot < len(c.rows[rid]) else ""
                label.value, label.color = (display_name(k), t.TEXT) if k else ("+", t.FAINT)
                box.border = t.border()
        for rid, extra in self.extras.items():
            extra.value = c.extras(rid)
            extra.visible = bool(extra.value)

    def _set(self, key: str, value) -> None:
        self.ctrl.set_setting(key, value)
        self.shell.render()

    # ---- teclas ----
    def _cell_click(self, rid: str, slot: int) -> None:
        c = self.ctrl
        if c.waiting:
            return          # o hook ja engole o clique e atribui o botao do mouse
        c.start_capture(rid, slot)

        def got(kind, value=None):
            self.shell.ui(lambda: (c.on_capture(kind, value), self.shell.render()))
        self.shell.capture.start(got)
        self.shell.render()

    def _cell_menu(self, rid: str, slot: int) -> None:
        if self.ctrl.waiting:
            return

        def pick(name):
            def go(e=None):
                self.shell.close_dialog()
                self.ctrl.assign(rid, slot, name)
                self.shell.render()
            return go

        def clear(e=None):
            self.shell.close_dialog()
            self.ctrl.clear_slot(rid, slot)
            self.shell.render()
        items = [t.button(tr(label), pick(name), primary=False) for label, name in EXTRA_KEYS]
        items.append(t.button(tr("Limpar"), clear, primary=False, icon_name="x"))
        self.shell.dialog(tr("%s — tecla %d") % (tr(bd.ROW_LABELS[rid]), slot + 1),
                          ft.Column(items, spacing=6, tight=True, width=300),
                          [t.button(tr("Fechar"), self.shell.close_dialog, primary=False)])

    def _clear(self, rid: str) -> None:
        self.ctrl.clear_row(rid)
        self.shell.render()

    # ---- perfis ----
    def _after_switch(self, problem=None) -> None:
        self.shell.report(problem)
        self.shell.render()

    def _pick(self, e) -> None:
        new = e.control.value
        c = self.ctrl
        if new == c.name:
            return
        e.control.value = c.name        # volta se cancelar; o render ajusta depois

        def go():
            self._after_switch(c.switch(new))
        self.shell.confirm_discard(go)

    def _new(self, e=None) -> None:
        def make(name):
            try:
                created = self.ctrl.new_profile(name)
            except ValueError as err:
                self.shell.info(str(err))
                return
            self._after_switch(self.ctrl.switch(created))
        self.shell.confirm_discard(lambda: self.shell.ask_name(tr("Nome do novo perfil:"), "", make))

    def _dup(self, e=None) -> None:
        def make(name):
            try:
                created = self.ctrl.dup_profile(name)
            except ValueError as err:
                self.shell.info(str(err))
                return
            self._after_switch(self.ctrl.switch(created))
        self.shell.ask_name(tr("Nome da cópia:"), pf.label(self.ctrl.name) + tr(" (cópia)"), make)

    def _rename(self, e=None) -> None:
        def go(name):
            if name in (self.ctrl.name, pf.label(self.ctrl.name)):
                return
            try:
                self.ctrl.rename(name)
            except (ValueError, OSError) as err:
                self.shell.info(str(err))
                return
            self.shell.render()
        self.shell.ask_name(tr("Novo nome:"), pf.label(self.ctrl.name), go)

    def _delete(self, e=None) -> None:
        def go():
            try:
                problem = self.ctrl.delete()
            except ValueError as err:
                self.shell.info(str(err))
                return
            self._after_switch(problem)
        self.shell.ask(tr("Excluir o perfil \"%s\"?") % pf.label(self.ctrl.name), go)

    def _save(self, e=None) -> None:
        self.shell.save()

    def _restore(self, e=None) -> None:
        def go():
            self.ctrl.restore_defaults()
            self.shell.render()
        self.shell.ask(tr("Restaurar os valores padrão neste perfil? (só vale ao salvar)"), go)
