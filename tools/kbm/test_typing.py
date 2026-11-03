"""Motor de digitacao: paridade exata com o motor JS (vetores) e propriedades do grafo."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proto import BTN  # noqa: E402
from kb_layout import LAYOUT, PAGE_TAB, all_nodes, nav, parse_cell, shortest_path  # noqa: E402
from typing_engine import (MAX_MS, MIN_MS, PRESETS, SWITCH_BTN, TypingEngine, migrate_prefs,  # noqa: E402
                           plan_char_for_test, text_diff)

VECTORS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web", "test",
                       "typing-vectors.json")


def M(name):
    return 1 << BTN[name]


DIRMASK = {M("DPAD_UP"): "up", M("DPAD_DOWN"): "down", M("DPAD_LEFT"): "left", M("DPAD_RIGHT"): "right"}


def run(eng, until=5000):
    segs = []
    for t in range(until + 1):
        m = eng.tick(t)
        if segs and segs[-1][0] == m:
            segs[-1][2] = t
        else:
            segs.append([m, t, t])
    return segs


def presses(segs):
    return [s[0] for s in segs if s[0] != 0]


def eng(**kw):
    return TypingEngine(42, 42, **kw)


def type_all(text, **kw):
    e = eng(**kw)
    e.enqueue(text)
    return e, presses(run(e, 60000))


def apply(e, ev):
    op = ev["op"]
    if op == "text":
        e.enqueue(ev["s"])
    elif op == "backspace":
        for _ in range(ev["n"]):
            e.backspace_requested()
    elif op == "submit":
        e.enqueue_submit()
    elif op == "clear":
        e.clear_pending()
    elif op == "reset":
        e.reset_keyboard()
    elif op == "nav":
        e.press_manual(ev["d"])
    elif op == "cursor":
        e.sync_cursor(ev["id"])
    elif op == "page":
        e.sync_page(ev["id"])
    elif op == "timing":
        e.set_timing(ev["hold"], ev["gap"])
    else:
        raise AssertionError(op)


class ParityTests(unittest.TestCase):
    def test_vectors_match_js_engine(self):
        with open(VECTORS, encoding="utf-8") as f:
            data = json.load(f)
        self.assertGreater(len(data["cases"]), 500)
        for n, c in enumerate(data["cases"]):
            e = TypingEngine(c["hold"], c["gap"], c["strip"])
            e.sync_page(c["page"])
            e.sync_cursor(c["cursor"])
            evs = sorted(c["events"], key=lambda x: x["at"])
            ei = 0
            runs = []
            for i in range(c["ticks"]):
                while ei < len(evs) and evs[ei]["at"] <= i:
                    apply(e, evs[ei])
                    ei += 1
                m = e.tick(i * c["step"])
                if runs and runs[-1][0] == m:
                    runs[-1][1] += 1
                else:
                    runs.append([m, 1])
            self.assertEqual(runs, c["runs"], "caso %d: %r" % (n, {k: c[k] for k in ("hold", "gap", "strip", "page", "cursor", "events")}))
            fin = c["final"]
            self.assertEqual((e.cursor, e.page, e.skipped, e.pending_count, e.busy),
                             (fin["cursor"], fin["page"], fin["skipped"], fin["pending"], fin["busy"]), "caso %d" % n)
            self.assertAlmostEqual(e.chars_per_second, fin["cps"], places=9)


class TableTests(unittest.TestCase):
    def test_table(self):
        self.assertEqual(SWITCH_BTN["A"], M("B"))
        self.assertEqual(SWITCH_BTN["B"], M("A"))
        self.assertEqual(SWITCH_BTN["Y"], M("X"))
        self.assertEqual(SWITCH_BTN["+"], M("START"))
        self.assertEqual(SWITCH_BTN["L3"], M("L3"))
        for k in ("X", "L", "R"):
            self.assertNotIn(k, SWITCH_BTN)

    def test_layout_shape(self):
        for name, p in LAYOUT["pages"].items():
            for g in (p["lower"], p["upper"]):
                if g:
                    self.assertEqual(len(g), 4, name)
                    for row in g:
                        self.assertEqual(len(row), 11, name)
        self.assertIsNone(LAYOUT["pages"]["sym"]["upper"])

    def test_graph(self):
        self.assertEqual(shortest_path("r1c0", "r1c10"), ["left", "left"])
        self.assertEqual(nav("r1c0", "left"), "enter1")
        self.assertEqual(nav("enter1", "right"), "r1c0")
        self.assertIsNone(nav("enter1", "up"))
        self.assertIsNone(nav("bksp", "down"))
        self.assertIsNone(nav("r0c3", "up"))
        for c in range(6, 11):
            self.assertIsNone(nav("r3c%d" % c, "down"))
        for i, t in enumerate(["globe", "shift", "abc", "sym", "acc1", "acc2"]):
            self.assertEqual(nav("r3c%d" % i, "down"), t)
            self.assertEqual(nav(t, "up"), "r3c%d" % i)
            self.assertIsNone(nav(t, "down"))
        self.assertIsNone(nav("globe", "left"))
        self.assertIsNone(nav("acc2", "right"))
        self.assertEqual(nav("abc", "right"), "sym")


class PropertyTests(unittest.TestCase):
    def test_plans_use_only_allowed_graph(self):
        chars = set()
        for p in LAYOUT["pages"].values():
            for g in (p["lower"], p["upper"]):
                if g:
                    chars.update(ch for row in g for ch in row if ch)
        self.assertGreater(len(chars), 200)
        tab_page = {t["id"]: t["page"] for t in LAYOUT["tabs"] if t.get("page")}
        allowed = {M("DPAD_UP"), M("DPAD_DOWN"), M("DPAD_LEFT"), M("DPAD_RIGHT"), M("B"), M("L3")}
        forbidden = M("Y") | M("L1") | M("R1") | M("L2_DIGITAL") | M("R2_DIGITAL")   # X, L, R do console
        plans = 0
        for ch in chars:
            for page in LAYOUT["pages"]:
                for node in all_nodes():
                    e = eng()
                    e.sync_page(page)
                    e.sync_cursor(node)
                    steps = plan_char_for_test(e, ch)
                    self.assertTrue(steps, ch)
                    plans += 1
                    cur, pg, shift, typed = node, page, False, None
                    self.assertLessEqual(sum(1 for s in steps if s["mask"] == M("L3")), 1)
                    for s in steps:
                        self.assertIn(s["mask"], allowed)
                        self.assertFalse(s["mask"] & forbidden)
                        self.assertLessEqual(bin(s["mask"]).count("1"), 1)   # nunca dois botoes juntos
                        d = DIRMASK.get(s["mask"])
                        if d:
                            c = parse_cell(cur)
                            if c:
                                self.assertFalse(d == "up" and c[0] == 0)
                                self.assertFalse(d == "down" and c[0] == 3 and c[1] >= 6)
                            self.assertFalse(shift, "direcional depois do L3")
                            self.assertEqual(s["cursor"], nav(cur, d))
                            cur = s["cursor"]
                        elif s["mask"] == M("L3"):
                            shift = True
                        elif cur in tab_page:
                            self.assertFalse(shift)
                            pg = s["page"]
                            self.assertEqual(pg, tab_page[cur])
                        else:
                            c = parse_cell(cur)
                            self.assertIsNotNone(c, "A em %s (%s)" % (cur, ch))
                            g = LAYOUT["pages"][pg]["upper" if shift else "lower"]
                            self.assertIsNotNone(g)
                            self.assertIsNotNone(g[c[0]][c[1]], "A em celula vazia (%s)" % ch)
                            typed = g[c[0]][c[1]]
                            shift = False
                    self.assertEqual(typed, ch)
        self.assertGreater(plans, 40000)


class BehaviorTests(unittest.TestCase):
    def test_q_from_start(self):
        e, p = type_all("q")
        self.assertEqual(p, [M("DPAD_DOWN"), M("B")])
        self.assertEqual(e.cursor, "r1c0")

    def test_oi_exact_timing(self):
        e = eng()
        e.enqueue("q")
        self.assertEqual([[m, a, b] for m, a, b in run(e, 300)],
                         [[M("DPAD_DOWN"), 0, 41], [0, 42, 83], [M("B"), 84, 125], [0, 126, 300]])

    def test_accents_and_pages(self):
        e, _ = type_all("é")
        self.assertEqual((e.page, e.cursor), ("acc1", "r1c8"))
        e, _ = type_all("/")
        self.assertEqual((e.page, e.cursor), ("sym", "r3c9"))
        e, p = type_all("Q")
        self.assertEqual(p, [M("DPAD_DOWN"), M("L3"), M("B")])
        e, p = type_all("ãa")
        self.assertEqual((e.page, e.cursor), ("abc", "r2c0"))
        self.assertEqual(p.count(M("B")), 4)

    def test_strip_accents(self):
        e, p = type_all("ã", strip_accents=True)
        self.assertEqual((e.page, e.cursor), ("abc", "r2c0"))
        self.assertEqual(p, [M("DPAD_DOWN"), M("DPAD_DOWN"), M("B")])

    def test_skipped_and_backspace(self):
        e = eng()
        e.enqueue("☃1")
        self.assertEqual(presses(run(e, 600)), [M("B")])
        self.assertEqual(e.skipped, ["☃"])
        f = eng()
        f.enqueue("1☃")
        f.backspace_requested()
        f.enqueue("☃")
        run(f, 600)
        f.backspace_requested()
        self.assertEqual(presses(run(f, 1200)), [])

    def test_submit_keeps_page(self):
        e = eng()
        e.enqueue("é")
        e.enqueue_submit()
        p = presses(run(e, 5000))
        self.assertEqual(p[-1], M("START"))
        self.assertEqual((e.cursor, e.page), ("r0c0", "acc1"))

    def test_reset_sync_clear(self):
        e = eng()
        e.sync_cursor("r2c5")
        e.sync_page("acc2")
        e.sync_cursor("nada")
        e.sync_page("nada")
        self.assertEqual((e.cursor, e.page), ("r2c5", "acc2"))
        e.enqueue("abc")
        e.reset_keyboard()
        self.assertEqual((e.cursor, e.page, e.pending_count), ("r0c0", "acc2", 0))
        self.assertEqual(PAGE_TAB["acc2"], "acc2")
        f = eng()
        f.enqueue("qa")
        self.assertEqual(f.tick(0), M("DPAD_DOWN"))
        f.enqueue("zzz")
        f.clear_pending()
        self.assertEqual(f.tick(20), M("DPAD_DOWN"))
        self.assertEqual(f.tick(42), 0)
        self.assertEqual(presses(run(f, 1000)), [])
        self.assertEqual((f.cursor, f.pending_count, f.busy), ("r1c0", 0, False))

    def test_manual_nav(self):
        e = eng()
        e.press_manual("up")
        self.assertEqual(presses(run(e, 300)), [])
        e.press_manual("down")
        self.assertEqual(presses(run(e, 300)), [M("DPAD_DOWN")])
        self.assertEqual(e.cursor, "r1c0")

    def test_diff_presets_prefs(self):
        self.assertEqual(text_diff("abc", "abd"), (1, "d"))
        self.assertEqual(text_diff("", "oi"), (0, "oi"))
        self.assertEqual(text_diff("oi", ""), (2, ""))
        self.assertEqual(text_diff("a´", "aé"), (1, "é"))
        self.assertEqual(PRESETS, {"seguro": (50, 50), "normal": (42, 42), "rapido": (34, 34)})
        e = TypingEngine()
        self.assertEqual((e.hold_ms, e.gap_ms), (42, 42))
        e.set_timing(10)
        self.assertEqual(e.hold_ms, MIN_MS)
        e.set_timing(500, 500)
        self.assertEqual(e.gap_ms, MAX_MS)
        self.assertEqual(migrate_prefs({"preset": "rapido", "ms": 20}),
                         {"preset": "rapido", "ms": 34, "stripAccents": False})
        self.assertEqual(migrate_prefs({"preset": "custom", "ms": 20}),
                         {"preset": "normal", "ms": 42, "stripAccents": False})
        self.assertEqual(migrate_prefs(None), {"preset": "normal", "ms": 42, "stripAccents": False})


if __name__ == "__main__":
    unittest.main()
