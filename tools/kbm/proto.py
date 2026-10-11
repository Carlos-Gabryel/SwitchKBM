"""Protocolo de quadros do bridge (ver common/bridge_proto/include/bridge_proto.h)."""
import struct

SOF0 = 0xAA
SOF1 = 0x55
TYPE_STATE = 0x01
TYPE_STATUS = 0x03
MAX_PAYLOAD = 48
FLAG_CONNECTED = 1 << 0

BTN = {
    "A": 0, "B": 1, "X": 2, "Y": 3, "L1": 4, "R1": 5,
    "L2_DIGITAL": 6, "R2_DIGITAL": 7, "L3": 8, "R3": 9,
    "DPAD_UP": 10, "DPAD_DOWN": 11, "DPAD_LEFT": 12, "DPAD_RIGHT": 13,
    "SELECT": 14, "START": 15, "SYSTEM": 16, "CAPTURE": 17,
}

STATE_FMT = "<BBBI4h2H3h3hH"
STATE_LEN = struct.calcsize(STATE_FMT)  # 33


def crc8(data: bytes) -> int:
    """CRC-8/ATM: poly 0x07, init 0."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def encode_frame(ftype: int, payload: bytes) -> bytes:
    body = bytes([ftype, len(payload)]) + bytes(payload)
    return bytes([SOF0, SOF1]) + body + bytes([crc8(body)])


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


def pack_state(seq=0, flags=0, battery=0, buttons=0, lx=0, ly=0, rx=0, ry=0,
               l2=0, r2=0, gyro=(0, 0, 0), accel=(0, 8192, 0), timestamp_ms=0) -> bytes:
    """Retorna o quadro completo (38 bytes) com o bridge_state_t."""
    payload = struct.pack(
        STATE_FMT, seq & 0xFF, flags & 0xFF, battery & 0xFF, buttons & 0xFFFFFFFF,
        _clamp(lx, -512, 511), _clamp(ly, -512, 511),
        _clamp(rx, -512, 511), _clamp(ry, -512, 511),
        _clamp(l2, 0, 1023), _clamp(r2, 0, 1023),
        *[_clamp(g, -32768, 32767) for g in gyro],
        *[_clamp(a, -32768, 32767) for a in accel],
        timestamp_ms & 0xFFFF)
    return encode_frame(TYPE_STATE, payload)


class StreamParser:
    """Maquina de estados com resincronizacao. Bytes fora de quadros viram linhas de texto."""

    def __init__(self):
        self._st = 0
        self._type = 0
        self._len = 0
        self._buf = bytearray()
        self._raw = bytearray()      # bytes do quadro em andamento (para devolver ao texto se falhar)
        self._text = bytearray()
        self.text_lines = []

    def _text_byte(self, b):
        if b == 0x0A:
            line = self._text.decode("utf-8", "replace").rstrip("\r")
            self._text.clear()
            if line:
                self.text_lines.append(line)
        else:
            self._text.append(b)

    def _abort(self):
        """Quadro invalido: devolve o que foi consumido como texto, exceto o 1o byte (SOF0),
        e reprocessa o resto para nao perder um SOF verdadeiro."""
        rest = bytes(self._raw[1:])
        self._st = 0
        self._raw.clear()
        self._buf.clear()
        out = []
        for b in rest:
            out.extend(self._feed_byte(b))
        return out

    def _feed_byte(self, b):
        frames = []
        st = self._st
        if st == 0:
            if b == SOF0:
                self._st = 1
                self._raw = bytearray([b])
            else:
                self._text_byte(b)
        elif st == 1:
            if b == SOF1:
                self._st = 2
                self._raw.append(b)
            else:
                self._st = 0
                self._raw.clear()
                if b == SOF0:
                    self._st = 1
                    self._raw = bytearray([b])
                else:
                    self._text_byte(b)
        elif st == 2:
            self._type = b
            self._raw.append(b)
            self._st = 3
        elif st == 3:
            self._raw.append(b)
            if b > MAX_PAYLOAD:
                return self._abort()
            self._len = b
            self._buf = bytearray()
            self._st = 4 if b else 5
        elif st == 4:
            self._raw.append(b)
            self._buf.append(b)
            if len(self._buf) >= self._len:
                self._st = 5
        elif st == 5:
            if crc8(bytes([self._type, self._len]) + bytes(self._buf)) == b:
                frames.append((self._type, bytes(self._buf)))
                self._st = 0
                self._raw.clear()
                self._buf = bytearray()
            else:
                self._raw.append(b)
                return self._abort()
        return frames

    def feed(self, data: bytes):
        """Retorna lista de (type, payload). Linhas de texto ficam em self.text_lines."""
        frames = []
        for b in data:
            frames.extend(self._feed_byte(b))
        return frames

    def pop_text(self):
        lines, self.text_lines = self.text_lines, []
        return lines
