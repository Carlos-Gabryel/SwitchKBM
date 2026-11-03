// Protocolo de quadros do bridge (porta de tools/kbm/proto.py).
export const SOF0 = 0xaa;
export const SOF1 = 0x55;
export const TYPE_STATE = 0x01;
export const TYPE_STATUS = 0x03;
export const MAX_PAYLOAD = 48;
export const FLAG_CONNECTED = 1 << 0;
export const STATE_LEN = 33;

export const BTN = {
  A: 0, B: 1, X: 2, Y: 3, L1: 4, R1: 5,
  L2_DIGITAL: 6, R2_DIGITAL: 7, L3: 8, R3: 9,
  DPAD_UP: 10, DPAD_DOWN: 11, DPAD_LEFT: 12, DPAD_RIGHT: 13,
  SELECT: 14, START: 15, SYSTEM: 16, CAPTURE: 17,
};

// CRC-8/ATM: poly 0x07, init 0
export function crc8(data) {
  let crc = 0;
  for (const b of data) {
    crc ^= b;
    for (let i = 0; i < 8; i++) crc = crc & 0x80 ? ((crc << 1) ^ 0x07) & 0xff : (crc << 1) & 0xff;
  }
  return crc;
}

export function encodeFrame(ftype, payload) {
  const out = new Uint8Array(payload.length + 5);
  out[0] = SOF0;
  out[1] = SOF1;
  out[2] = ftype;
  out[3] = payload.length;
  out.set(payload, 4);
  out[out.length - 1] = crc8(out.subarray(2, out.length - 1));
  return out;
}

// int() do Python (trunca) + limites
function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, Math.trunc(v)));
}

// Retorna o quadro completo (38 bytes) com o bridge_state_t (little-endian)
export function packState({
  seq = 0, flags = 0, battery = 0, buttons = 0, lx = 0, ly = 0, rx = 0, ry = 0,
  l2 = 0, r2 = 0, gyro = [0, 0, 0], accel = [0, 8192, 0], timestamp_ms = 0,
} = {}) {
  const p = new Uint8Array(STATE_LEN);
  const dv = new DataView(p.buffer);
  dv.setUint8(0, seq & 0xff);
  dv.setUint8(1, flags & 0xff);
  dv.setUint8(2, battery & 0xff);
  dv.setUint32(3, buttons >>> 0, true);
  dv.setInt16(7, clamp(lx, -512, 511), true);
  dv.setInt16(9, clamp(ly, -512, 511), true);
  dv.setInt16(11, clamp(rx, -512, 511), true);
  dv.setInt16(13, clamp(ry, -512, 511), true);
  dv.setUint16(15, clamp(l2, 0, 1023), true);
  dv.setUint16(17, clamp(r2, 0, 1023), true);
  for (let i = 0; i < 3; i++) dv.setInt16(19 + 2 * i, clamp(gyro[i], -32768, 32767), true);
  for (let i = 0; i < 3; i++) dv.setInt16(25 + 2 * i, clamp(accel[i], -32768, 32767), true);
  dv.setUint16(31, timestamp_ms & 0xffff, true);
  return encodeFrame(TYPE_STATE, p);
}

// Maquina de estados com resincronizacao. Bytes fora de quadros viram linhas de texto.
export class StreamParser {
  constructor() {
    this._st = 0;
    this._type = 0;
    this._len = 0;
    this._buf = [];
    this._raw = [];
    this._text = [];
    this.textLines = [];
    this._dec = new TextDecoder("utf-8");
  }

  _textByte(b) {
    if (b === 0x0a) {
      let line = this._dec.decode(Uint8Array.from(this._text));
      this._text = [];
      line = line.replace(/\r+$/, "");
      if (line) this.textLines.push(line);
    } else {
      this._text.push(b);
    }
  }

  // Quadro invalido: devolve o consumido como texto (menos o SOF0) e reprocessa o resto
  _abort() {
    const rest = this._raw.slice(1);
    this._st = 0;
    this._raw = [];
    this._buf = [];
    const out = [];
    for (const b of rest) out.push(...this._feedByte(b));
    return out;
  }

  _feedByte(b) {
    const st = this._st;
    if (st === 0) {
      if (b === SOF0) {
        this._st = 1;
        this._raw = [b];
      } else {
        this._textByte(b);
      }
    } else if (st === 1) {
      if (b === SOF1) {
        this._st = 2;
        this._raw.push(b);
      } else {
        this._st = 0;
        this._raw = [];
        if (b === SOF0) {
          this._st = 1;
          this._raw = [b];
        } else {
          this._textByte(b);
        }
      }
    } else if (st === 2) {
      this._type = b;
      this._raw.push(b);
      this._st = 3;
    } else if (st === 3) {
      this._raw.push(b);
      if (b > MAX_PAYLOAD) return this._abort();
      this._len = b;
      this._buf = [];
      this._st = b ? 4 : 5;
    } else if (st === 4) {
      this._raw.push(b);
      this._buf.push(b);
      if (this._buf.length >= this._len) this._st = 5;
    } else if (st === 5) {
      if (crc8([this._type, this._len, ...this._buf]) === b) {
        const f = { type: this._type, payload: Uint8Array.from(this._buf) };
        this._st = 0;
        this._raw = [];
        this._buf = [];
        return [f];
      }
      this._raw.push(b);
      return this._abort();
    }
    return [];
  }

  // Retorna lista de {type, payload}; linhas de texto ficam em textLines
  feed(data) {
    const frames = [];
    for (const b of data) {
      const r = this._feedByte(b);
      if (r.length) frames.push(...r);
    }
    return frames;
  }

  popText() {
    const l = this.textLines;
    this.textLines = [];
    return l;
  }
}

// Versao do firmware no payload do STATUS (byte 1); null se curto demais
export function statusFwVersion(payload) {
  return payload.length >= 2 ? payload[1] : null;
}
