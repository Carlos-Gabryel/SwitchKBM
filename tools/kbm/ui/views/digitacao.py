"""Digitacao: escreve texto no teclado da tela do Switch 2 (modo digitacao do bridge, F9)."""
from __future__ import annotations

import flet as ft

from kb_layout import LAYOUT
from typing_engine import MAX_MS, MIN_MS, PRESETS, text_diff
from ui import theme as t

WARNING = ("O app não vê a TV: confira se o teclado está aberto antes de digitar. Se o teclado estiver "
           "fechado, os comandos vão para o que estiver na tela.")
CLICK_HINT = "Clique onde o cursor está na TV se errar letras"
HELP = ("Enter envia · Esc limpa a fila e o campo · "
        "Setas (campo vazio) movem o cursor · Home (campo vazio) = teclado reaberto na TV")
PRESET_LABELS = {"seguro": "Seguro", "normal": "Normal", "rapido": "Rápido"}
CELL_W, CELL_H, GAP = 46, 38, 4
KEY_ALIASES = {"escape": "esc", "esc": "esc", "arrowup": "up", "up": "up", "arrowdown": "down", "down": "down",
               "arrowleft": "left", "left": "left", "arrowright": "right", "right": "right", "home": "home"}


def key_name(label: str) -> str:
    """Rotulo do KeyboardEvent do Flet ('Arrow Up', 'Escape', 'Home') -> 'up' | 'esc' | 'home' | ''."""
    return KEY_ALIASES.get(str(label).lower().replace(" ", "").replace("_", ""), "")


def _update(control) -> None:
    try:
        control.update()
    except RuntimeError:        # controle ainda fora da pagina
        pass


class DigitacaoView:
    def __init__(self, shell):
        self.shell, self.ctrl = shell, shell.ctrl
        self._prev = ""             # valor anterior do campo (para o diff)
        self.has_focus = False
        self._shown = None          # (pagina, cursor, ligado) desenhado no teclado
        # Sem shift_enter: com ele o focus() do Flet 1.0.2 nao pega; o Enter e tratado em _changed
        self.field = ft.TextField(multiline=True, min_lines=3, max_lines=6, disabled=True,
                                  hint_text="Ligue o modo digitação (F9) e escreva aqui…",
                                  on_change=self._changed,
                                  on_focus=self._focused, on_blur=self._blurred, **t.field_style())
        self.toggle = t.button("Ligar (F9)", self._toggle, icon_name="keyboard")
        self.msg = t.muted("", 12)
        self.c_pending, self.c_cps, self.c_skipped = t.text("0", 18, bold=True), t.text("0", 18, bold=True), t.text("0", 18, bold=True)
        self.cells: dict[str, tuple[ft.Container, ft.Text]] = {}      # id do no -> (caixa, texto)
        self.grid_ids: list[list[str]] = []
        self.keyboard = self._build_keyboard()
        self.presets = {k: t.button(v, lambda e, k=k: self._preset(k), primary=False)
                        for k, v in PRESET_LABELS.items()}
        self.ms_label = t.muted("", 12)
        self.slider = ft.Slider(mouse_cursor=t.CLICK, min=MIN_MS, max=MAX_MS, divisions=MAX_MS - MIN_MS, expand=True,
                                active_color=t.ACCENT, inactive_color=t.FIELD, thumb_color=t.ACCENT,
                                on_change=lambda e: self._custom(int(round(e.control.value))))
        self.strip = ft.Checkbox(label="Sem acentos (mais rápido)", active_color=t.ACCENT,
                                 on_change=lambda e: self.ctrl.set_typing_strip(e.control.value))
        self.test_btn = t.button("Testar velocidade", self._test, primary=False, icon_name="zap")
        self.reopen_btn = t.button("Teclado reaberto", self._reopen, primary=False, icon_name="rotate-ccw")
        stat = lambda label, value: ft.Column([value, t.muted(label, 11)], spacing=0)    # noqa: E731
        self.control = ft.Column([
            ft.Row([t.text("Digitação", 22, bold=True), ft.Container(expand=True), self.msg, self.toggle],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            t.notice(WARNING, 12),
            t.card(ft.Column([self.field, t.muted(HELP, 11)], spacing=8,
                             horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
            t.card(ft.Column([
                ft.Row([t.text("Teclado do Switch 2", 14, bold=True), ft.Container(expand=True),
                        stat("pendentes", self.c_pending), stat("letras/s", self.c_cps),
                        stat("ignorados", self.c_skipped)], spacing=24,
                       vertical_alignment=ft.CrossAxisAlignment.END),
                self.keyboard, t.muted(CLICK_HINT, 11)], spacing=10)),
            t.card(ft.Column([
                t.text("Velocidade", 14, bold=True),
                ft.Row([*self.presets.values(), self.slider, self.ms_label], spacing=10,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                t.muted("Mais rápido pode perder apertos no console; se errar letras, use Seguro.", 11),
                ft.Row([self.strip, ft.Container(expand=True), self.test_btn, self.reopen_btn], spacing=10,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=10)),
        ], spacing=t.GAP, scroll=ft.ScrollMode.AUTO, expand=True)

    # ---- teclado (prévia) ----
    def _cell(self, node: str, width: int = CELL_W, on_click=None) -> ft.Control:
        label = ft.Text("", size=13, color=t.TEXT)
        box = ft.Container(content=label, width=width, height=CELL_H, alignment=ft.Alignment.CENTER,
                           border_radius=t.RADIUS_SMALL, bgcolor=t.FIELD, border=t.border(),
                           on_click=on_click, on_hover=lambda e: None)     # sem hover: a cor segue o cursor
        self.cells[node] = (box, label)
        return t.clickable(box)

    def _build_keyboard(self) -> ft.Control:
        L = LAYOUT
        rows = []
        for r in range(L["rows"]):
            ids = ["r%dc%d" % (r, c) for c in range(L["cols"])]
            self.grid_ids.append(ids)
            cells = [self._cell(n, on_click=lambda e, n=n: self._click(n)) for n in ids]
            rid = L["right"][r]["id"]
            cells.append(self._cell(rid, on_click=lambda e, n=rid: self._click(n)))
            self.cells[rid][1].value = L["right"][r]["label"]
            rows.append(ft.Row(cells, spacing=GAP))
        tabs = []
        for tab in L["tabs"]:
            tid = tab["id"]
            tabs.append(self._cell(tid, on_click=lambda e, n=tid: self._click(n)))
            self.cells[tid][1].value = tab["label"]
            self.cells[tid][1].size = 12
        space = ft.Container(content=t.muted("Espaço", 12), height=CELL_H, width=(CELL_W + GAP) * 8 - GAP,
                             alignment=ft.Alignment.CENTER, border_radius=t.RADIUS_SMALL, bgcolor=t.FIELD,
                             border=t.border())
        rows.append(ft.Row(tabs, spacing=GAP))
        rows.append(ft.Row([ft.Container(width=(CELL_W + GAP) * 3), space], spacing=0))
        return ft.Column(rows, spacing=GAP, tight=True)

    def _paint_keyboard(self, page: str, cursor: str) -> None:
        L = LAYOUT
        grid = L["pages"].get(page, L["pages"]["abc"])["lower"]
        for r, ids in enumerate(self.grid_ids):
            for c, node in enumerate(ids):
                ch = grid[r][c]
                self.cells[node][1].value = ch or ""
        for node, (box, label) in self.cells.items():
            on = node == cursor
            tab_page = next((x.get("page") for x in L["tabs"] if x["id"] == node), None)
            box.bgcolor = t.ACCENT if on else t.FIELD
            box.border = t.border(t.GREEN if (tab_page and tab_page == page and not on) else t.BORDER)
            label.color = "#FFFFFF" if on else t.TEXT

    # ---- ações ----
    def _report(self, problem) -> None:
        if problem:
            self.shell.info(problem[1])
        self.shell.render()

    def _toggle(self, e=None) -> None:
        self._report(self.ctrl.typing_toggle())

    def _send(self, op: str, **kw) -> None:
        problem = self.ctrl.typing_send(op, **kw)
        if problem:
            self.msg.value = problem[1]
            _update(self.msg)

    def _click(self, node: str) -> None:
        if not self.ctrl.typing_on:
            return
        page = next((x.get("page") for x in LAYOUT["tabs"] if x["id"] == node), None)
        if page:
            self._send("page", id=page)
        self._send("cursor", id=node)

    def _focused(self, e=None) -> None:
        self.has_focus = True

    def _blurred(self, e=None) -> None:
        self.has_focus = False

    def _changed(self, e) -> None:
        new = e.control.value or ""
        back, ins = text_diff(self._prev, new)
        if ins == "\n" and not back:          # Enter
            self._submit()
            return
        if "\n" in new:                       # texto colado: o console nao tem quebra de linha
            new = new.replace("\n", " ")
            e.control.value = new
            _update(e.control)
            back, ins = text_diff(self._prev, new)
        self._prev = new
        if back:
            self._send("backspace", n=back)
        if ins:
            self._send("text", s=ins)

    def _submit(self, e=None) -> None:
        self._send("submit")
        self.clear_field()
        self.shell.page.run_task(self._focus)

    def clear_field(self) -> None:
        self._prev = ""
        self.field.value = ""
        _update(self.field)

    async def _focus(self) -> None:
        try:
            await self.field.focus()
        except Exception:
            pass

    def _preset(self, key: str) -> None:
        self.ctrl.set_typing_speed(preset=key)
        self.shell.render()

    def _custom(self, ms: int) -> None:
        self.ctrl.set_typing_speed(ms=ms)
        self.refresh()
        self.shell.page.update()

    def _test(self, e=None) -> None:
        self._send("text", s="qwertyuiop")

    def _reopen(self, e=None) -> None:
        self._send("reset")

    def on_key(self, e) -> bool:
        """Atalhos da página enquanto esta view está ativa. True se tratou."""
        if not self.ctrl.typing_on:
            return False
        name = key_name(e.key)
        if name == "esc":
            self._send("clear")
            self.clear_field()
        elif name in ("up", "down", "left", "right") and not self.field.value:
            self._send("nav", d=name)
        elif name == "home" and not self.field.value:
            self._send("reset")
        else:
            return False
        return True

    # ---- desenho ----
    def refresh(self) -> None:
        c = self.ctrl
        on = c.typing_on
        p = c.typing_prefs
        self.msg.value = ""
        self.toggle.content = "Desligar (F9)" if on else "Ligar (F9)"
        self.toggle.disabled = c.flashing
        self.field.disabled = not on
        self.field.hint_text = "Digite ou cole aqui" if on else "Ligue o modo digitação (F9) e escreva aqui…"
        for key, b in self.presets.items():
            b.style.bgcolor = {ft.ControlState.DEFAULT: t.ACCENT if p["preset"] == key else t.HOVER}
        self.slider.value = p["ms"]
        self.ms_label.value = "%d ms" % p["ms"]
        self.strip.value = p["stripAccents"]
        self.test_btn.disabled = self.reopen_btn.disabled = not on
        self.refresh_state()

    def refresh_state(self) -> None:
        """Parte que muda a ~10 Hz: teclado e contadores."""
        c = self.ctrl
        st = c.typing_state if c.typing_on else {}
        page, cursor = st.get("page", LAYOUT["startPage"]), st.get("cursor", LAYOUT["start"])
        if not c.typing_on:
            cursor = ""
        sig = (page, cursor)
        if sig != self._shown:
            self._shown = sig
            self._paint_keyboard(page, cursor)
        self.c_pending.value = str(st.get("pending", 0))
        self.c_cps.value = "%.1f" % float(st.get("cps", 0) or 0)
        self.c_skipped.value = str(st.get("skipped", 0))
