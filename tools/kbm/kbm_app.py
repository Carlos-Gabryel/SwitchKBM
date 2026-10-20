"""Switch KBM - programa para remapear teclado/mouse -> botoes do Switch e rodar o bridge.

Ponto de entrada: --bridge / --flash (subprocessos do proprio exe), --selftest, ou a UI Flet."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _fix_std_streams():
    for fd, name, mode in ((0, "stdin", "r"), (1, "stdout", "w"), (2, "stderr", "w")):
        if getattr(sys, name) is None:
            try:
                kw = {"buffering": 1} if mode == "w" else {}
                f = open(fd, mode, encoding="utf-8", closefd=False, **kw)
            except OSError:
                f = open(os.devnull, mode)
            setattr(sys, name, f)


def selftest():
    """Sem janela: roda as checagens do controller e da captura e confere que a UI Flet importa
    (no exe isso valida que o flet foi empacotado). Retorna 0/1."""
    import tempfile
    import traceback
    try:
        import capture
        import profiles as pf
        from controller import Controller
        c = Controller(pf.ProfileStore(base=tempfile.mkdtemp(prefix="kbmtest")))
        assert c.name == pf.DEFAULT_NAME, c.name
        assert c.rows["R1"][0] == "g"
        c.start_capture("B", 0)
        c.on_capture(*capture.key_result(0x47))
        assert c.rows["B"][0] == "g" and "g" not in c.rows["R1"], c.rows["B"]
        assert c.dirty and "saiu de R" in c.msg, c.msg
        c.start_capture("A", 0)
        c.on_capture(*capture.key_result(0x7B))          # F12 nao atribui
        assert c.rows["A"][0] != "f12"
        c.on_bridge_line("SENS deg_per_count=0.0550")
        assert abs(c.settings["sens"] - 0.055) < 1e-9
        assert c.save() and not c.dirty
        import flet  # noqa: F401
        import ui.app  # noqa: F401
    except Exception:
        traceback.print_exc()
        return 1
    print("selftest OK")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--bridge":
        _fix_std_streams()
        import kbm_bridge
        kbm_bridge.main(argv[1:])
        return 0
    if argv and argv[0] == "--flash":
        _fix_std_streams()
        import flasher
        return flasher.run(argv[1])
    if "--selftest" in argv:
        return selftest()
    from ui.app import run
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
