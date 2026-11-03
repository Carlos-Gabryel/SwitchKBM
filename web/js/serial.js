// Placa ESP32 via Web Serial: leitura com StreamParser, escrita sem fila (descarta se ocupado).
import { StreamParser, TYPE_STATUS, statusFwVersion } from "./proto.js";

const MAX_LOG = 200;

export class Board {
  constructor() {
    this.port = null;
    this.reader = null;
    this.writer = null;
    this.connected = false;
    this.fwVersion = null;
    this.dropped = 0;
    this.log = [];
    this.error = "";
    this.onChange = () => {};
    this._writing = false;
    this._parser = new StreamParser();
    this._onSerialDisconnect = (e) => {
      if (this.port && e.target === this.port) this._lost("Placa desconectada.");
    };
  }

  static supported() {
    return typeof navigator !== "undefined" && "serial" in navigator;
  }

  _log(line) {
    this.log.push(line);
    if (this.log.length > MAX_LOG) this.log.splice(0, this.log.length - MAX_LOG);
  }

  async connect() {
    if (this.connected) return;
    this.error = "";
    const port = await navigator.serial.requestPort(); // cancelar lanca NotFoundError
    await this.open(port);
  }

  async open(port) {
    try {
      await port.open({ baudRate: 115200 });
      // Sem setSignals: logo apos abrir, DTR e RTS ficam ambos ativos, o que e neutro no circuito
      // de auto-reset; mudar um de cada vez (como o Chrome no Windows faz) pulsa o EN e reinicia a placa.
    } catch (e) {
      this.error = "Não foi possível abrir a porta: " + (e && e.message ? e.message : e);
      this.onChange();
      throw e;
    }
    this.port = port;
    this.writer = port.writable.getWriter();
    this.reader = port.readable.getReader();
    this.connected = true;
    this.fwVersion = null;
    this._parser = new StreamParser();
    navigator.serial.addEventListener("disconnect", this._onSerialDisconnect);
    this._readLoop(this.reader);
    this.onChange();
  }

  async _readLoop(reader) {
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        if (!value) continue;
        for (const f of this._parser.feed(value)) {
          if (f.type === TYPE_STATUS) {
            const v = statusFwVersion(f.payload);
            if (v !== null && v !== this.fwVersion) {
              this.fwVersion = v;
              this.onChange();
            }
          }
        }
        for (const line of this._parser.popText()) this._log(line);
      }
    } catch (e) {
      if (this.connected && reader === this.reader) this._lost("Erro de leitura: " + (e && e.message ? e.message : e));
      return;
    }
    if (this.connected && reader === this.reader) this._lost("Conexão com a placa encerrada.");
  }

  // Nunca enfileira: se a escrita anterior ainda nao terminou, descarta e conta
  send(frame) {
    if (!this.connected || !this.writer) return false;
    if (this._writing) {
      this.dropped++;
      return false;
    }
    this._writing = true;
    this.writer.write(frame).then(
      () => { this._writing = false; },
      (e) => {
        this._writing = false;
        if (this.connected) this._lost("Erro de escrita: " + (e && e.message ? e.message : e));
      },
    );
    return true;
  }

  _lost(msg) {
    this.error = msg;
    this._cleanup();
  }

  async disconnect() {
    this.error = "";
    await this._cleanup();
  }

  async _cleanup() {
    if (!this.port) return;
    const { port, reader, writer } = this;
    this.connected = false;
    this.port = this.reader = this.writer = null;
    this._writing = false;
    navigator.serial.removeEventListener("disconnect", this._onSerialDisconnect);
    this.onChange();
    try { await reader.cancel(); } catch { /* ignora */ }
    try { reader.releaseLock(); } catch { /* ignora */ }
    try { writer.releaseLock(); } catch { /* ignora */ }
    try { await port.close(); } catch { /* ignora */ }
  }
}
