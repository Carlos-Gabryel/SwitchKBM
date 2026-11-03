import { test } from "node:test";
import assert from "node:assert/strict";
import { BUTTON_ROWS, MOVE_ROWS, profileToRows, rowsToProfile, assignKey, clearRow, extras, checkKey } from "../js/bindings.js";
import { defaultProfile } from "../js/profiles.js";

test("linhas: mesma ordem e rotulos do programa", () => {
  assert.deepEqual(BUTTON_ROWS.slice(0, 4), [["B", "A"], ["A", "B"], ["Y", "X"], ["X", "Y"]]);
  assert.equal(BUTTON_ROWS.length, 18);
  assert.deepEqual(MOVE_ROWS.map((r) => r[1]), ["Frente", "Trás", "Esquerda", "Direita", "Andar devagar"]);
});

test("perfil padrao -> linhas -> perfil preserva binds e movimento", () => {
  const p = defaultProfile();
  const back = rowsToProfile(profileToRows(p), {}, p);
  assert.deepEqual(back.binds, p.binds);
  assert.deepEqual(back.move, p.move);
  assert.equal(back.gyro_sensitivity, p.gyro_sensitivity);
});

test("atribuir move a tecla de onde estava; reservada e recusada", () => {
  const rows = profileToRows(defaultProfile());
  const r = assignKey(rows, "B", 1, "q"); // q era L1
  assert.equal(r.moved, "L1");
  assert.equal(r.rows.L1[0], "");
  assert.equal(r.rows.B[1], "q");
  assert.throws(() => assignKey(rows, "B", 1, "f7"), /F7 é reservada \(hotkey do programa\)/);
  assert.equal(checkKey("zzz"), "tecla desconhecida: zzz");
  assert.deepEqual(clearRow(rows, "B"), { ...rows, B: ["", ""] });
});

test("extras: mais de duas teclas aparecem como '+ X'", () => {
  const rows = profileToRows({ binds: { a: "X", b: "X", c: "X" }, move: {} });
  assert.equal(extras(rows, "X", (k) => k.toUpperCase()), "+ C");
  assert.equal(extras(rows, "move:up", (k) => k), "");
});
