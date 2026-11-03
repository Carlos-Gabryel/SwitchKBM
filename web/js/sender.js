// Laco de envio a 200 Hz: build_state -> (stateOverride) -> packState -> Board.send.
import { packState } from "./proto.js";

export const PERIOD_MS = 5;

export class Sender {
  // getMapper: () => Mapper; isCaptured: () => bool
  constructor(board, getMapper, isCaptured) {
    this.board = board;
    this.getMapper = getMapper;
    this.isCaptured = isCaptured;
    this.stateOverride = null; // (st, nowMs) => st; usado pelo modo digitacao
    this.onStats = () => {};
    this.stats = { tx: 0, gapMax: 0, dropped: 0 };
    this.seq = 0;
    this._worker = null;
    this._last = 0;
    this._statT = 0;
    this._tx = 0;
    this._gap = 0;
    this._drop0 = 0;
  }

  start() {
    if (this._worker) return;
    this._worker = new Worker(new URL("./tick-worker.js", import.meta.url));
    this._worker.onmessage = () => this.tick(performance.now());
    this._last = this._statT = performance.now();
    this._tx = 0;
    this._gap = 0;
    this._drop0 = this.board.dropped;
    this._worker.postMessage("start");
  }

  stop() {
    if (!this._worker) return;
    this._worker.postMessage("stop");
    this._worker.terminate();
    this._worker = null;
  }

  tick(now) {
    const dt = (now - this._last) / 1000;
    if (this._tx && dt * 1000 > this._gap) this._gap = dt * 1000;
    this._last = now;
    let st = this.getMapper().build_state(now / 1000, dt, this.isCaptured());
    if (this.stateOverride) st = this.stateOverride(st, now) || st;
    const frame = packState({ ...st, seq: this.seq, timestamp_ms: Math.floor(now) & 0xffff });
    this.seq = (this.seq + 1) & 0xff;
    this.board.send(frame);
    this._tx++;
    if (now - this._statT >= 1000) {
      this.stats = { tx: this._tx, gapMax: this._gap, dropped: this.board.dropped - this._drop0 };
      this._statT = now;
      this._tx = 0;
      this._gap = 0;
      this._drop0 = this.board.dropped;
      this.onStats(this.stats);
    }
  }
}
