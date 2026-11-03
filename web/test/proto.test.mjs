import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  crc8, encodeFrame, packState, StreamParser, TYPE_STATUS, TYPE_STATE, STATE_LEN, statusFwVersion,
} from "../js/proto.js";
import { FIRMWARE_VERSION } from "../js/version.js";
import { md5 } from "../js/md5.js";
import { createHash } from "node:crypto";

const vectors = JSON.parse(readFileSync(new URL("./vectors.json", import.meta.url), "utf-8"));
const hex = (u8) => Buffer.from(u8).toString("hex");
const unhex = (h) => Uint8Array.from(Buffer.from(h, "hex"));

test("crc8 bate com o Python", () => {
  for (const v of vectors.crc8) assert.equal(crc8(unhex(v.hex)), v.crc, v.hex);
});

test("encodeFrame bate com o Python", () => {
  for (const v of vectors.encodeFrame) assert.equal(hex(encodeFrame(v.type, unhex(v.payload))), v.frame);
});

test("packState bate com o Python (38 bytes)", () => {
  assert.equal(STATE_LEN, 33);
  for (const v of vectors.packState) {
    const fr = packState(v.args);
    assert.equal(fr.length, 38);
    assert.equal(hex(fr), v.frame, JSON.stringify(v.args));
  }
});

test("parser: lixo, texto e frames em pedacos", () => {
  const f1 = encodeFrame(TYPE_STATUS, Uint8Array.of(1, 1));
  const f2 = encodeFrame(TYPE_STATUS, Uint8Array.of(2, 0));
  const enc = new TextEncoder();
  const stream = Buffer.concat([
    Buffer.from([0x00, 0xaa, 0x13]), enc.encode("junk\nI (123) log line\r\n"), f1,
    Buffer.from([0xaa, 0x55, 0xff, 0x99]), enc.encode("texto\n"), f2,
  ]);
  const p = new StreamParser();
  const out = [];
  for (let i = 0; i < stream.length; i += 3) out.push(...p.feed(stream.subarray(i, i + 3)));
  assert.deepEqual(out.map((f) => [f.type, [...f.payload]]), [[TYPE_STATUS, [1, 1]], [TYPE_STATUS, [2, 0]]]);
  assert.ok(p.popText().join("\n").includes("I (123) log line"));
  assert.equal(p.popText().length, 0);
});

test("parser: CRC ruim ressincroniza", () => {
  const good = encodeFrame(TYPE_STATUS, Uint8Array.of(0, 1));
  const bad = Uint8Array.from(good);
  bad[bad.length - 1] ^= 0xff;
  const out = new StreamParser().feed(Buffer.concat([bad, good]));
  assert.deepEqual(out.map((f) => [f.type, [...f.payload]]), [[TYPE_STATUS, [0, 1]]]);
});

test("parser: frame cortado espera o resto", () => {
  const good = encodeFrame(TYPE_STATUS, Uint8Array.of(0, 1));
  const p = new StreamParser();
  assert.equal(p.feed(good.subarray(0, 4)).length, 0);
  const out = p.feed(good.subarray(4));
  assert.equal(out.length, 1);
  assert.equal(statusFwVersion(out[0].payload), 1);
});

test("parser: round-trip de um STATE", () => {
  const out = new StreamParser().feed(packState({ seq: 7, flags: 1, buttons: 1, timestamp_ms: 70000 }));
  assert.equal(out.length, 1);
  assert.equal(out[0].type, TYPE_STATE);
  const dv = new DataView(out[0].payload.buffer, out[0].payload.byteOffset);
  assert.equal(dv.getUint8(0), 7);
  assert.equal(dv.getUint32(3, true), 1);
  assert.equal(dv.getUint16(31, true), 70000 & 0xffff);
  assert.deepEqual([dv.getInt16(25, true), dv.getInt16(27, true), dv.getInt16(29, true)], [0, 8192, 0]);
});

test("FIRMWARE_VERSION confere com BRIDGE_FW_VERSION do header", () => {
  const h = readFileSync(new URL("../../common/bridge_proto/include/bridge_proto.h", import.meta.url), "utf-8");
  const m = h.match(/#define\s+BRIDGE_FW_VERSION\s+(\d+)/);
  assert.ok(m, "BRIDGE_FW_VERSION nao encontrado");
  assert.equal(FIRMWARE_VERSION, Number(m[1]));
});

test("md5 bate com node:crypto", () => {
  for (const n of [0, 1, 55, 56, 63, 64, 65, 1000, 4097]) {
    const d = Uint8Array.from({ length: n }, (_, i) => (i * 31 + 7) & 0xff);
    assert.equal(md5(d), createHash("md5").update(d).digest("hex"), "n=" + n);
  }
});
