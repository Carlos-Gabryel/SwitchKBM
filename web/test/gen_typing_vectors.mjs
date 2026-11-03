// Gera typing-vectors.json: sequencia exata de mascaras por tick do motor JS (tempo simulado).
// O motor Python (tools/kbm/typing_engine.py) tem de reproduzir igual (tools/kbm/test_typing.py).
// Uso: node web/test/gen_typing_vectors.mjs
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { TypingEngine } from "../js/typing.js";
import { allNodes, LAYOUT } from "../js/kb-layout.js";

const nodes = allNodes();
const pages = Object.keys(LAYOUT.pages);
let seed = 12345;
const rnd = (n) => { seed = (Math.imul(seed, 1103515245) + 12345) >>> 0; return (seed >>> 8) % n; };
const pick = (a) => a[rnd(a.length)];

const phrases = [
  "Oi", "oi mundo", "Olá, como vai você?", "Ação e coração", "ÀÉÎÕÜ maiúsculas", "São Paulo - SP",
  "Teste 123 !?@#", "e-mail: fulano@exemplo.com", "aaa bbb ccc", "ããã ñññ", "ãa õe çã", "João & Maria (2024)",
  "100% certo = sim", "a/b\\c|d", "~`^{}[]<>", "ǆ ☃ x", "ǎ ǐ ǒ", "QWERTY Asdf", "Zebra Ωmega", "  espaços  ",
  "café com leite", "über straße", "łódź żółć", "ÿ ý ű ő", "1234567890", "...,,,---___", "£€°ª", "Pokémon",
  "A", "z", " ", "é", "É", "ñ", "Ñ", "/", "@", "€",
];
const timings = [[42, 42], [34, 34], [50, 50], [25, 25], [100, 100], [30, 60], [60, 30], [42, 25]];
const cases = [];

function run(spec) {
  const e = new TypingEngine({ holdMs: spec.hold, gapMs: spec.gap, stripAccents: spec.strip });
  e.syncPage(spec.page);
  e.syncCursor(spec.cursor);
  const apply = (ev) => {
    switch (ev.op) {
      case "text": e.enqueue(ev.s); break;
      case "backspace": for (let i = 0; i < ev.n; i++) e.backspaceRequested(); break;
      case "submit": e.enqueueSubmit(); break;
      case "clear": e.clearPending(); break;
      case "reset": e.resetKeyboard(); break;
      case "nav": e.pressManual(ev.d); break;
      case "cursor": e.syncCursor(ev.id); break;
      case "page": e.syncPage(ev.id); break;
      case "timing": e.setTiming(ev.hold, ev.gap); break;
    }
  };
  const runs = [];
  let quietFrom = null, i = 0;
  const evs = [...spec.events].sort((a, b) => a.at - b.at);
  let ei = 0;
  for (;; i++) {
    while (ei < evs.length && evs[ei].at <= i) apply(evs[ei++]);
    const m = e.tick(i * spec.step);
    if (runs.length && runs[runs.length - 1][0] === m) runs[runs.length - 1][1]++; else runs.push([m, 1]);
    if (!e.busy && ei >= evs.length) { quietFrom ??= i; if (i - quietFrom > 6000 / spec.step) break; } else quietFrom = null;
    if (i > 400000) throw new Error("nao terminou");
  }
  return {
    ...spec, ticks: i + 1, runs,
    final: { cursor: e.cursor, page: e.page, skipped: e.skipped, pending: e.pendingCount, busy: e.busy, cps: e.charsPerSecond },
  };
}

const base = () => {
  const [hold, gap] = pick(timings);
  return { hold, gap, strip: rnd(4) === 0, step: pick([1, 1, 1, 7]), page: pick(pages), cursor: pick(nodes), events: [] };
};

// 1) cada frase a partir de varios estados
for (const ph of phrases) {
  for (let k = 0; k < 6; k++) { const s = base(); s.events.push({ at: 0, op: "text", s: ph }); cases.push(run(s)); }
}
// 2) padrao (inicio), todas as combinacoes simples
for (const ph of phrases) {
  for (const strip of [false, true]) {
    cases.push(run({ hold: 42, gap: 42, strip, step: 1, page: "abc", cursor: "r0c0", events: [{ at: 0, op: "text", s: ph }] }));
  }
}
// 3) backspace, submit, nav, clear, reset, sincronizacao e mudanca de velocidade no meio
for (let k = 0; k < 120; k++) {
  const s = base();
  const n = 3 + rnd(6);
  let at = 0;
  for (let j = 0; j < n; j++) {
    at += rnd(3) === 0 ? rnd(400) : 0;
    const r = rnd(12);
    if (r < 4) s.events.push({ at, op: "text", s: pick(phrases) });
    else if (r === 4) s.events.push({ at, op: "backspace", n: 1 + rnd(4) });
    else if (r === 5) s.events.push({ at, op: "submit" });
    else if (r === 6) s.events.push({ at, op: "nav", d: pick(["up", "down", "left", "right"]) });
    else if (r === 7) s.events.push({ at, op: "clear" });
    else if (r === 8) s.events.push({ at, op: "reset" });
    else if (r === 9) s.events.push({ at, op: "cursor", id: pick(nodes) });
    else if (r === 10) s.events.push({ at, op: "page", id: pick(pages) });
    else s.events.push({ at, op: "timing", hold: 20 + rnd(100), gap: 20 + rnd(100) });
  }
  cases.push(run(s));
}
// 4) backspace logo depois de texto com caractere ignorado
for (const t of ["a☃", "☃☃b", "ǆa"]) {
  const s = { hold: 42, gap: 42, strip: false, step: 1, page: "abc", cursor: "r0c0",
    events: [{ at: 0, op: "text", s: t }, { at: 500, op: "backspace", n: 2 }, { at: 600, op: "text", s: "x" }] };
  cases.push(run(s));
}
// 5) setas manuais: todas as direcoes de todos os nos
for (const node of nodes) {
  for (const d of ["up", "down", "left", "right"]) {
    cases.push(run({ hold: 34, gap: 34, strip: false, step: 1, page: "abc", cursor: node, events: [{ at: 0, op: "nav", d }] }));
  }
}

const out = fileURLToPath(new URL("./typing-vectors.json", import.meta.url));
writeFileSync(out, JSON.stringify({ version: 1, cases }));
console.log(`${cases.length} casos -> ${out}`);
