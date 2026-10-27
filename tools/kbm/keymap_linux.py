"""Tabela evdev (KEY_*, numeros de linux/input-event-codes.h) -> codigo VK do Windows.

Assim o Mapper, os binds e os perfis salvos continuam iguais nas duas plataformas (layout US:
as teclas de pontuacao viram VK_OEM_*). Sem dependencia do python-evdev: os numeros sao a ABI do kernel."""

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA = 0x110, 0x111, 0x112, 0x113, 0x114

# botoes do mouse (evdev) -> mesmos nomes que o winput emite
MOUSE_BUTTONS = {BTN_LEFT: "lmb", BTN_RIGHT: "rmb", BTN_MIDDLE: "mmb", BTN_SIDE: "x1", BTN_EXTRA: "x2"}

EVDEV_TO_VK = {
    30: 0x41,  # KEY_A
    48: 0x42,  # KEY_B
    46: 0x43,  # KEY_C
    32: 0x44,  # KEY_D
    18: 0x45,  # KEY_E
    33: 0x46,  # KEY_F
    34: 0x47,  # KEY_G
    35: 0x48,  # KEY_H
    23: 0x49,  # KEY_I
    36: 0x4A,  # KEY_J
    37: 0x4B,  # KEY_K
    38: 0x4C,  # KEY_L
    50: 0x4D,  # KEY_M
    49: 0x4E,  # KEY_N
    24: 0x4F,  # KEY_O
    25: 0x50,  # KEY_P
    16: 0x51,  # KEY_Q
    19: 0x52,  # KEY_R
    31: 0x53,  # KEY_S
    20: 0x54,  # KEY_T
    22: 0x55,  # KEY_U
    47: 0x56,  # KEY_V
    17: 0x57,  # KEY_W
    45: 0x58,  # KEY_X
    21: 0x59,  # KEY_Y
    44: 0x5A,  # KEY_Z
    2: 0x31,  # KEY_1
    3: 0x32,  # KEY_2
    4: 0x33,  # KEY_3
    5: 0x34,  # KEY_4
    6: 0x35,  # KEY_5
    7: 0x36,  # KEY_6
    8: 0x37,  # KEY_7
    9: 0x38,  # KEY_8
    10: 0x39,  # KEY_9
    11: 0x30,  # KEY_0
    59: 0x70,  # KEY_F1
    60: 0x71,  # KEY_F2
    61: 0x72,  # KEY_F3
    62: 0x73,  # KEY_F4
    63: 0x74,  # KEY_F5
    64: 0x75,  # KEY_F6
    65: 0x76,  # KEY_F7
    66: 0x77,  # KEY_F8
    67: 0x78,  # KEY_F9
    68: 0x79,  # KEY_F10
    87: 0x7A,  # KEY_F11
    88: 0x7B,  # KEY_F12
    183: 0x7C,  # KEY_F13
    184: 0x7D,  # KEY_F14
    185: 0x7E,  # KEY_F15
    186: 0x7F,  # KEY_F16
    187: 0x80,  # KEY_F17
    188: 0x81,  # KEY_F18
    189: 0x82,  # KEY_F19
    190: 0x83,  # KEY_F20
    191: 0x84,  # KEY_F21
    192: 0x85,  # KEY_F22
    193: 0x86,  # KEY_F23
    194: 0x87,  # KEY_F24
    82: 0x60,  # KEY_KP0
    79: 0x61,  # KEY_KP1
    80: 0x62,  # KEY_KP2
    81: 0x63,  # KEY_KP3
    75: 0x64,  # KEY_KP4
    76: 0x65,  # KEY_KP5
    77: 0x66,  # KEY_KP6
    71: 0x67,  # KEY_KP7
    72: 0x68,  # KEY_KP8
    73: 0x69,  # KEY_KP9
    55: 0x6A,  # KEY_KPASTERISK
    78: 0x6B,  # KEY_KPPLUS
    74: 0x6D,  # KEY_KPMINUS
    83: 0x6E,  # KEY_KPDOT
    98: 0x6F,  # KEY_KPSLASH
    96: 0x0D,  # KEY_KPENTER
    12: 0xBD,  # KEY_MINUS
    13: 0xBB,  # KEY_EQUAL
    26: 0xDB,  # KEY_LEFTBRACE
    27: 0xDD,  # KEY_RIGHTBRACE
    43: 0xDC,  # KEY_BACKSLASH
    39: 0xBA,  # KEY_SEMICOLON
    40: 0xDE,  # KEY_APOSTROPHE
    51: 0xBC,  # KEY_COMMA
    52: 0xBE,  # KEY_DOT
    53: 0xBF,  # KEY_SLASH
    41: 0xC0,  # KEY_GRAVE
    86: 0xE2,  # KEY_102ND
    89: 0xC1,  # KEY_RO
    57: 0x20,  # KEY_SPACE
    15: 0x09,  # KEY_TAB
    1: 0x1B,  # KEY_ESC
    28: 0x0D,  # KEY_ENTER
    14: 0x08,  # KEY_BACKSPACE
    58: 0x14,  # KEY_CAPSLOCK
    42: 0xA0,  # KEY_LEFTSHIFT
    54: 0xA1,  # KEY_RIGHTSHIFT
    29: 0xA2,  # KEY_LEFTCTRL
    97: 0xA3,  # KEY_RIGHTCTRL
    56: 0xA4,  # KEY_LEFTALT
    100: 0xA5,  # KEY_RIGHTALT
    125: 0x5B,  # KEY_LEFTMETA
    126: 0x5C,  # KEY_RIGHTMETA
    102: 0x24,  # KEY_HOME
    107: 0x23,  # KEY_END
    110: 0x2D,  # KEY_INSERT
    111: 0x2E,  # KEY_DELETE
    104: 0x21,  # KEY_PAGEUP
    109: 0x22,  # KEY_PAGEDOWN
    105: 0x25,  # KEY_LEFT
    103: 0x26,  # KEY_UP
    106: 0x27,  # KEY_RIGHT
    108: 0x28,  # KEY_DOWN
    69: 0x90,  # KEY_NUMLOCK
    70: 0x91,  # KEY_SCROLLLOCK
    99: 0x2C,  # KEY_SYSRQ
    119: 0x13,  # KEY_PAUSE
    127: 0x5D,  # KEY_COMPOSE
    124: 0xDC,  # KEY_YEN
}


def code_to_vk(code):
    """Codigo evdev -> VK (None se a tecla nao tem equivalente)."""
    return EVDEV_TO_VK.get(code)
