import test from "node:test";
import assert from "node:assert/strict";
import { BTN } from "../js/proto.js";
import { LAYOUT, nav, shortestPath, allNodes, parseCell, PAGE_TAB } from "../js/kb-layout.js";
import { TypingEngine, SWITCH_BTN, textDiff, PRESETS, MIN_MS, MAX_MS, migratePrefs, planCharForTest } from "../js/typing.js";

const M = (name) => 1 << BTN[name];
const DIRMASK = { [M("DPAD_UP")]: "up", [M("DPAD_DOWN")]: "down", [M("DPAD_LEFT")]: "left", [M("DPAD_RIGHT")]: "right" };

// Roda o motor a cada 1 ms e devolve os trechos [mask, inicio, fim]
function run(eng, until = 5000, step = 1) {
  const segs = [];
  let last = null;
  for (let t = 0; t <= until; t += step) {
    const m = eng.tick(t);
    if (!last || last[0] !== m) { last = [m, t, t]; segs.push(last); } else last[2] = t;
  }
  return segs;
}
const presses = (segs) => segs.filter((s) => s[0] !== 0).map((s) => s[0]);
const eng = (o = {}) => new TypingEngine({ holdMs: 42, gapMs: 42, ...o });
// botoes de um texto, rodando o relogio
const typeAll = (text, o) => { const e = eng(o); e.enqueue(text); return { e, p: presses(run(e, 60000)) }; };
const count = (p, m) => p.filter((x) => x === m).length;

test("tabela: A/B/Y trocam, + e L3; X, L e R nao existem", () => {
  assert.equal(SWITCH_BTN.A, M("B"));
  assert.equal(SWITCH_BTN.B, M("A"));
  assert.equal(SWITCH_BTN.Y, M("X"));
  assert.equal(SWITCH_BTN["+"], M("START"));
  assert.equal(SWITCH_BTN.L3, M("L3"));
  for (const k of ["X", "L", "R"]) assert.equal(SWITCH_BTN[k], undefined);
  assert.equal(LAYOUT.verified, true);
});

test("layout: 4x11 em todas as paginas; sym sem upper", () => {
  for (const [name, p] of Object.entries(LAYOUT.pages)) {
    for (const g of [p.lower, p.upper].filter(Boolean)) {
      assert.equal(g.length, 4, name);
      for (const row of g) assert.equal(row.length, 11, name);
    }
  }
  assert.equal(LAYOUT.pages.sym.upper, null);
});

test("q a partir do 1: so 1 passo para baixo", () => {
  const { e, p } = typeAll("q");
  assert.deepEqual(p, [M("DPAD_DOWN"), M("B")]);
  assert.equal(e.cursor, "r1c0");
});

test("ciclo de 12: r1c0 -> r1c10 sao 2 passos a esquerda por enter1", () => {
  assert.deepEqual(shortestPath("r1c0", "r1c10"), ["left", "left"]);
  assert.equal(nav("r1c0", "left"), "enter1");
  assert.equal(nav("enter1", "right"), "r1c0"); // memoria: volta ao c0
  assert.equal(nav("r1c10", "right"), "enter1");
  assert.equal(nav("enter1", "up"), null);
  assert.equal(nav("bksp", "down"), null);
});

test("arestas proibidas e abas", () => {
  assert.equal(nav("r0c3", "up"), null);
  for (let c = 6; c <= 10; c++) assert.equal(nav(`r3c${c}`, "down"), null);
  ["globe", "shift", "abc", "sym", "acc1", "acc2"].forEach((t, i) => {
    assert.equal(nav(`r3c${i}`, "down"), t);
    assert.equal(nav(t, "up"), `r3c${i}`);
    assert.equal(nav(t, "down"), null);
  });
  assert.equal(nav("globe", "left"), null); // sem wrap nas abas
  assert.equal(nav("acc2", "right"), null);
  assert.equal(nav("abc", "right"), "sym");
});

// ---- propriedade: nenhum plano usa aresta proibida / botao proibido ----
test("propriedade: planos so usam o grafo permitido, A so em alvo valido", () => {
  const chars = new Set();
  for (const p of Object.values(LAYOUT.pages)) for (const g of [p.lower, p.upper]) if (g) for (const row of g) for (const c of row) if (c) chars.add(c);
  assert.ok(chars.size > 200);
  const tabPage = Object.fromEntries(LAYOUT.tabs.filter((t) => t.page).map((t) => [t.id, t.page]));
  const allowed = new Set([M("DPAD_UP"), M("DPAD_DOWN"), M("DPAD_LEFT"), M("DPAD_RIGHT"), M("B"), M("L3")]);
  let plans = 0;
  for (const ch of chars) {
    for (const page of Object.keys(LAYOUT.pages)) {
      for (const node of allNodes()) {
        const e = eng();
        e.syncPage(page); e.syncCursor(node);
        const steps = planCharForTest(e, ch);
        assert.ok(steps.length > 0, `sem plano para ${ch}`);
        plans++;
        let cur = node, pg = page, shift = false, typed = null;
        for (const s of steps) {
          assert.ok(allowed.has(s.mask), `botao proibido ${s.mask} (${ch})`);
          const dir = DIRMASK[s.mask];
          if (dir) {
            const c = parseCell(cur);
            if (c) {
              assert.ok(!(dir === "up" && c.r === 0), `r0+cima em ${ch} de ${node}/${page}`);
              assert.ok(!(dir === "down" && c.r === 3 && c.c >= 6), `c6+baixo em ${ch} de ${node}/${page}`);
            }
            assert.ok(!shift, "direcional depois do L3");
            assert.equal(s.cursor, nav(cur, dir));
            cur = s.cursor;
          } else if (s.mask === M("L3")) {
            shift = true;
          } else {
            // A: so em aba de pagina ou celula nao vazia
            if (cur in tabPage) { assert.ok(!shift); pg = s.page; assert.equal(pg, tabPage[cur]); }
            else {
              const c = parseCell(cur);
              assert.ok(c, `A em ${cur} (${ch})`);
              const g = shift ? LAYOUT.pages[pg].upper : LAYOUT.pages[pg].lower;
              assert.ok(g, "L3 em pagina sem upper");
              assert.notEqual(g[c.r][c.c], null, `A em celula vazia (${ch})`);
              typed = g[c.r][c.c];
              shift = false;
            }
          }
          assert.ok(steps.filter((x) => x.mask === M("L3")).length <= 1);
        }
        assert.equal(typed, ch);
      }
    }
  }
  assert.ok(plans > 40000);
});

test("é = aba acc1 e a celula certa; õ = acc2", () => {
  const e = eng();
  const s = planCharForTest(e, "é");
  const ia = s.findIndex((x) => x.page);
  assert.equal(s[ia].page, "acc1");
  assert.equal(s[ia - 1].cursor, "acc1");
  assert.equal(s[s.length - 1].mask, M("B"));
  assert.equal(s[s.length - 2].cursor, "r1c8");
  const f = eng();
  const t = planCharForTest(f, "õ");
  assert.equal(t.find((x) => x.page).page, "acc2");
  assert.equal(t[t.length - 2].cursor, "r0c7");
  // rodando: pagina e cursor finais
  const { e: g } = typeAll("é");
  assert.equal(g.page, "acc1");
  assert.equal(g.cursor, "r1c8");
});

test("/ = sym", () => {
  const { e } = typeAll("/");
  assert.equal(e.page, "sym");
  assert.equal(e.cursor, "r3c9");
});

test("Q = L3 imediatamente antes do A", () => {
  const { p, e } = typeAll("Q");
  assert.deepEqual(p, [M("DPAD_DOWN"), M("L3"), M("B")]);
  assert.equal(e.cursor, "r1c0");
});

test("@ = abc com L3 (r1c10), nao sym, quando mais barato", () => {
  const { e, p } = typeAll("@");
  assert.equal(e.page, "abc");
  assert.equal(e.cursor, "r1c10");
  assert.equal(p[p.length - 2], M("L3"));
  assert.equal(p.length, 3 + 2); // baixo, esquerda x2, L3, A
});

test("ãã so troca de pagina uma vez; acento seguido de a volta a ABC", () => {
  const { p, e } = typeAll("ãã");
  assert.equal(count(p, M("B")), 3); // aba, ã, ã
  const { p: q, e: f } = typeAll("ãa");
  assert.equal(f.page, "abc");
  assert.equal(count(q, M("B")), 4); // aba acc1, ã, aba abc, a
  assert.equal(f.cursor, "r2c0");
  assert.equal(e.page, "acc1");
});

test("stripAccents: tudo vira base sem trocar de pagina", () => {
  const { p, e } = typeAll("ã", { stripAccents: true });
  assert.equal(e.page, "abc");
  assert.equal(e.cursor, "r2c0");
  assert.deepEqual(p, [M("DPAD_DOWN"), M("DPAD_DOWN"), M("B")]);
  const { e: g } = typeAll("É", { stripAccents: true });
  assert.equal(g.page, "abc");
});

test("sem acento disponivel: usa a base; dz com caron nao e caractere (celula vazia)", () => {
  const e = eng();
  e.enqueue("ǆ"); // dz com caron: sem celula, NFD nao resolve
  assert.deepEqual(presses(run(e, 500)), []);
  assert.deepEqual(e.skipped, ["ǆ"]);
  const f = eng();
  f.enqueue("·"); // celula sem caractere
  assert.deepEqual(presses(run(f, 500)), []);
  assert.deepEqual(f.skipped, ["·"]);
  const g = eng();
  g.enqueue("ǎ"); // a com caron: nao existe; vira a
  const p = presses(run(g, 1000));
  assert.equal(g.page, "abc");
  assert.equal(g.cursor, "r2c0");
  assert.equal(p[p.length - 1], M("B"));
});

test("submit volta o cursor ao inicio e mantem a pagina (o console a lembra)", () => {
  const e = eng();
  e.enqueue("é");
  e.enqueueSubmit();
  const p = presses(run(e, 5000));
  assert.equal(p[p.length - 1], M("START"));
  assert.equal(e.cursor, "r0c0");
  assert.equal(e.page, "acc1");
});

test("resetKeyboard, syncCursor, syncPage", () => {
  const e = eng();
  e.syncCursor("r2c5"); e.syncPage("acc2");
  assert.equal(e.cursor, "r2c5");
  assert.equal(e.page, "acc2");
  e.syncCursor("nada"); e.syncPage("nada");
  assert.equal(e.cursor, "r2c5");
  assert.equal(e.page, "acc2");
  e.enqueue("abc");
  e.resetKeyboard();
  assert.equal(e.cursor, "r0c0");
  assert.equal(e.page, "acc2"); // o console lembra a pagina ao reabrir
  assert.equal(e.pendingCount, 0);
  assert.equal(PAGE_TAB.acc2, "acc2");
});

test("espaco usa Y e nao mexe no cursor; backspace B; submit +", () => {
  const e = eng();
  e.enqueue(" ");
  assert.deepEqual(presses(run(e, 300)), [M("X")]);
  assert.equal(e.cursor, "r0c0");
  e.backspaceRequested();
  e.enqueueSubmit();
  assert.deepEqual(presses(run(e, 1000)), [M("A"), M("START")]);
  assert.equal(e.cursor, "r0c0");
});

test("manual: usa so o grafo; direcao proibida vira nada", () => {
  const e = eng();
  e.pressManual("up"); // r0 + cima: proibido
  assert.deepEqual(presses(run(e, 300)), []);
  assert.equal(e.cursor, "r0c0");
  e.pressManual("down");
  assert.deepEqual(presses(run(e, 300)), [M("DPAD_DOWN")]);
  assert.equal(e.cursor, "r1c0");
  for (const [at, d] of [["r3c7", "down"], ["enter1", "up"], ["bksp", "down"], ["globe", "down"]]) {
    const f = eng();
    f.syncCursor(at);
    f.pressManual(d);
    assert.deepEqual(presses(run(f, 300)), [], at + d);
    assert.equal(f.cursor, at);
  }
});

test("temporizacao exata de hold/gap", () => {
  const e = eng();
  e.enqueue("q"); // 1 baixo + A
  const segs = run(e, 300);
  assert.deepEqual(segs, [
    [M("DPAD_DOWN"), 0, 41], [0, 42, 83], [M("B"), 84, 125], [0, 126, 300],
  ]);
  assert.equal(e.cursor, "r1c0");
});

test("nunca dois passos sem soltar, mesmo com ticks espacados", () => {
  const e = eng({ holdMs: 25, gapMs: 25 });
  e.enqueue("we");
  const seq = [];
  for (let t = 0; t < 2000; t += 7) seq.push(e.tick(t));
  for (let i = 1; i < seq.length; i++) assert.ok(!(seq[i] && seq[i - 1] && seq[i] !== seq[i - 1]));
});

test("tick atrasado nao encurta o hold", () => {
  const e = eng();
  e.enqueue("1"); // ja esta no 1: so A
  assert.equal(e.tick(0), M("B"));
  assert.equal(e.tick(10), M("B"));
  assert.equal(e.tick(41), M("B"));
  assert.equal(e.tick(300), 0); // atrasou: so solta
  assert.equal(e.tick(310), 0); // gap conta a partir da soltura real
  e.enqueue("1");
  assert.equal(e.tick(341), 0);
  assert.equal(e.tick(342), M("B"));
});

test("caractere desconhecido e pulado", () => {
  const e = eng();
  e.enqueue("☃1");
  assert.deepEqual(presses(run(e, 600)), [M("B")]);
  assert.deepEqual(e.skipped, ["☃"]);
});

test("backspaceRequested: remove char nao iniciado, senao enfileira", () => {
  const e = eng();
  e.enqueue("12");
  e.backspaceRequested();
  assert.equal(e.pendingCount, 1);
  e.tick(0); // '1' iniciou
  e.backspaceRequested();
  e.backspaceRequested();
  assert.equal(e.pendingCount, 3);
  const p = presses(run(e, 2000));
  assert.equal(count(p, M("A")), 2);
});

test("backspace de caractere ignorado nao apaga letra real", () => {
  const e = eng();
  e.enqueue("1☃");
  e.backspaceRequested();
  e.enqueue("☃");
  run(e, 600);
  e.backspaceRequested();
  assert.deepEqual(presses(run(e, 1200)), []);
});

test("clearPending termina o passo atual e mantem cursor alinhado", () => {
  const e = eng();
  e.enqueue("qa");
  assert.equal(e.tick(0), M("DPAD_DOWN")); // r0c0 -> r1c0
  e.enqueue("zzz");
  e.clearPending();
  assert.equal(e.tick(20), M("DPAD_DOWN"));
  assert.equal(e.tick(42), 0);
  assert.deepEqual(presses(run(e, 1000)), []);
  assert.equal(e.cursor, "r1c0");
  assert.equal(e.pendingCount, 0);
  assert.equal(e.busy, false);
});

test("textDiff", () => {
  assert.deepEqual(textDiff("abc", "abd"), { backspaces: 1, insert: "d" });
  assert.deepEqual(textDiff("", "oi"), { backspaces: 0, insert: "oi" });
  assert.deepEqual(textDiff("oi", ""), { backspaces: 2, insert: "" });
  assert.deepEqual(textDiff("a´", "aé"), { backspaces: 1, insert: "é" });
  assert.deepEqual(textDiff("x", "x"), { backspaces: 0, insert: "" });
});

test("presets e faixa", () => {
  assert.deepEqual(PRESETS, { seguro: { hold: 50, gap: 50 }, normal: { hold: 42, gap: 42 }, rapido: { hold: 34, gap: 34 } });
  assert.equal(MIN_MS, 25);
  assert.equal(MAX_MS, 100);
  const e = new TypingEngine();
  assert.equal(e.holdMs, 42);
  assert.equal(e.gapMs, 42);
  e.setTiming(10);
  assert.equal(e.holdMs, 25);
  e.setTiming(500, 500);
  assert.equal(e.gapMs, 100);
});

test("migracao de preferencia antiga", () => {
  assert.deepEqual(migratePrefs({ preset: "normal", ms: 34, cursor: "q" }), { preset: "normal", ms: 42, stripAccents: false });
  assert.deepEqual(migratePrefs({ preset: "rapido", ms: 20 }), { preset: "rapido", ms: 34, stripAccents: false });
  assert.deepEqual(migratePrefs({ preset: "custom", ms: 20 }), { preset: "normal", ms: 42, stripAccents: false });
  assert.deepEqual(migratePrefs({ preset: "custom", ms: 60, stripAccents: true }), { preset: "custom", ms: 60, stripAccents: true });
  assert.deepEqual(migratePrefs({ preset: "turbo", ms: 30 }), { preset: "normal", ms: 42, stripAccents: false });
  assert.deepEqual(migratePrefs({ preset: "custom", ms: 101 }), { preset: "normal", ms: 42, stripAccents: false });
  assert.deepEqual(migratePrefs(null), { preset: "normal", ms: 42, stripAccents: false });
});

test("cursor final depois de uma frase", () => {
  const e = eng({ holdMs: 25, gapMs: 25 });
  e.enqueue("oi mundo");
  run(e, 60000);
  assert.equal(e.pendingCount, 0);
  assert.ok(e.charsPerSecond >= 0);
  assert.equal(e.page, "abc");
});
