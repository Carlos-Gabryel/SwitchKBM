import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Config, Mapper, pyRound, KEY_NAMES } from "../js/mapping.js";

const vectors = JSON.parse(readFileSync(new URL("./vectors.json", import.meta.url), "utf-8"));

test("pyRound arredonda metade para par", () => {
  const casos = [[0.5, 0], [1.5, 2], [2.5, 2], [3.5, 4], [-0.5, 0], [-1.5, -2], [-2.5, -2],
    [2.4, 2], [2.6, 3], [-2.6, -3], [255.5, 256], [0, 0]];
  for (const [x, y] of casos) assert.equal(pyRound(x), y, String(x));
  assert.ok(Object.is(pyRound(-0.2), 0));
});

for (const sc of vectors.mapping) {
  test("mapping: " + sc.name, () => {
    const notes = [];
    const m = new Mapper(new Config(sc.config), (s) => notes.push(s), () => 0.5);
    sc.events.forEach((ev, i) => {
      const where = `${sc.name} #${i} ${ev.op}`;
      switch (ev.op) {
        case "key_down":
          assert.equal(m.key_down(ev.key) ?? "", ev.ret, where);
          break;
        case "key_up": m.key_up(ev.key); break;
        case "mouse_button": m.mouse_button(ev.name, ev.down); break;
        case "wheel": m.wheel(ev.dir, ev.now); break;
        case "mouse_move": m.mouse_move(ev.dx, ev.dy); break;
        case "release_all": m.release_all(); break;
        case "build":
          assert.deepEqual(m.build_state(ev.now, ev.dt, ev.captured), ev.expect, where);
          break;
        default: assert.fail("op desconhecida " + ev.op);
      }
      if (ev.notes.length) assert.deepEqual(notes, ev.notes, where + " notes");
      notes.length = 0;
    });
  });
}

test("f9 so devolve toggle_typing na borda e nunca vira botao", () => {
  const m = new Mapper(new Config({ binds: { f9: "A", space: "B" } }));
  assert.equal(m.key_down("f9"), "toggle_typing");
  assert.equal(m.key_down("f9"), "repeat");
  assert.equal(m.build_state(1, 0.005, true).buttons, 0);
  m.key_up("f9");
  assert.equal(m.key_down("f9"), "toggle_typing");
});

test("accel_noise usa o RNG injetado", () => {
  const m = new Mapper(new Config({ accel_noise: 10 }), () => {}, () => 0);
  m.mouse_move(10, 0);
  const st = m.build_state(1, 0.005, true);
  assert.deepEqual(st.accel, [-10, 8192 - 10, -10]);
});

test("nomes de KEY_NAMES sem duplicatas", () => {
  assert.equal(new Set(KEY_NAMES).size, KEY_NAMES.length);
});
