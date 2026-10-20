"""Tokens visuais e componentes base (mesma identidade do Distribuidor: tema escuro, destaque vermelho)."""
from __future__ import annotations

import flet as ft

BG, SIDEBAR, CARD, FIELD, HOVER = "#0E0F12", "#14161A", "#16181D", "#1A1D22", "#1F2329"
BORDER, TEXT, MUTED, FAINT = "#23252B", "#E8E9EC", "#9AA0AA", "#6B717B"
ACCENT, GREEN, AMBER = "#E8445A", "#3DD68C", "#F5A524"
RADIUS, RADIUS_SMALL, GAP, SIDEBAR_WIDTH, CONTROL_HEIGHT = 12, 8, 12, 236, 36

STATUS_COLORS = {"running": GREEN, "flashing": AMBER}     # parado = ACCENT (estado "ruim")


def text(value: str, size: int = 13, color: str = TEXT, bold: bool = False, **kw) -> ft.Text:
    return ft.Text(value, size=size, color=color, weight=ft.FontWeight.W_600 if bold else None, **kw)


def muted(value: str, size: int = 12, **kw) -> ft.Text:
    return text(value, size=size, color=MUTED, **kw)


def icon(name: str, size: int = 18, color: str = MUTED) -> ft.Image:
    return ft.Image(src=f"icons/{name}.svg", width=size, height=size, color=color,
                    color_blend_mode=ft.BlendMode.SRC_IN)


def border(color: str = BORDER, width: int = 1) -> ft.Border:
    side = ft.BorderSide(width, color)
    return ft.Border(top=side, right=side, bottom=side, left=side)


def card(content: ft.Control, padding: int = 14, on_click=None, selected: bool = False,
         **kw) -> ft.Container:
    return ft.Container(content=content, padding=padding, bgcolor=CARD, border_radius=RADIUS,
                        border=border(ACCENT if selected else BORDER), on_click=on_click,
                        ink=on_click is not None, **kw)


def button(label: str, on_click=None, primary: bool = True, icon_name: str | None = None,
           disabled: bool = False) -> ft.Button:
    ink = "#FFFFFF" if primary else TEXT
    style = ft.ButtonStyle(
        bgcolor={ft.ControlState.DISABLED: HOVER, ft.ControlState.DEFAULT: ACCENT if primary else HOVER},
        color={ft.ControlState.DISABLED: FAINT, ft.ControlState.DEFAULT: ink},
        shape=ft.StadiumBorder(), padding=ft.Padding(18, 8, 18, 8), elevation=0,
        text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600))
    return ft.Button(label, icon=icon(icon_name, 16, ink) if icon_name else None,
                     on_click=on_click, style=style, disabled=disabled, height=CONTROL_HEIGHT)


def icon_button(name: str, tooltip: str, on_click=None, color: str = MUTED, disabled: bool = False) -> ft.Container:
    return ft.Container(content=icon(name, 16, FAINT if disabled else color), width=32, height=32,
                        alignment=ft.Alignment.CENTER, border_radius=RADIUS_SMALL, tooltip=tooltip,
                        bgcolor=FIELD, border=border(), on_click=None if disabled else on_click,
                        ink=not disabled)


def dot(color: str) -> ft.Container:
    return ft.Container(width=8, height=8, border_radius=4, bgcolor=color)


def status_card(key: str, title: str, detail: str) -> ft.Container:
    color = STATUS_COLORS.get(key, ACCENT)
    bad = color == ACCENT
    return ft.Container(
        padding=10, border_radius=RADIUS_SMALL, bgcolor="#2A1519" if bad else CARD,
        border=border("#5A2630" if bad else BORDER),
        content=ft.Column([ft.Row([dot(color), text(title, 12, bold=True)], spacing=6),
                           muted(detail, 11)], spacing=4))


def notice(message: str, size: int = 11) -> ft.Container:
    """Aviso ambar (algo que merece atencao, mas nao impede de usar)."""
    return ft.Container(
        padding=10, border_radius=RADIUS_SMALL, bgcolor="#2A2112", border=border("#5A4519"),
        content=ft.Row([icon("triangle-alert", 14, AMBER), ft.Container(text(message, size, AMBER), expand=True)],
                       spacing=8, vertical_alignment=ft.CrossAxisAlignment.START))


def brand(size: int = 15) -> ft.Row:
    return ft.Row([ft.Image(src="icon.png", width=size + 13, height=size + 13), text("Switch KBM", size, bold=True)],
                  spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def nav_item(label: str, icon_name: str, selected: bool, on_click) -> ft.Container:
    color = TEXT if selected else MUTED
    return ft.Container(content=ft.Row([icon(icon_name, 16, color), text(label, 13, color)], spacing=10),
                        padding=ft.Padding(10, 8, 10, 8), border_radius=RADIUS_SMALL,
                        bgcolor=HOVER if selected else None, on_click=on_click, ink=True)


def field_style() -> dict:
    """Parametros comuns de TextField/Dropdown no tema escuro."""
    return dict(bgcolor=FIELD, border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
                border_radius=RADIUS_SMALL, text_size=13, content_padding=ft.Padding(10, 6, 10, 6))


def apply_page(page: ft.Page) -> None:
    page.title = "Switch KBM"
    page.bgcolor = BG
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme=ft.ColorScheme(primary=ACCENT, surface=CARD))
    page.padding = 0
    page.window.width, page.window.height = 900, 680
    page.window.min_width, page.window.min_height = 760, 560
