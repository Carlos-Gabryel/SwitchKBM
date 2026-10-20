"""Grava o firmware switch-side na placa via esptool (embutido no exe)."""
import json
import os
import sys

# Versao do firmware embutida neste programa; tem de ser igual a BRIDGE_FW_VERSION em
# common/bridge_proto/include/bridge_proto.h (um teste confere). A placa informa a dela no STATUS.
FIRMWARE_VERSION = 1


def firmware_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "firmware")
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "..", "switch-side", "build"))


def load_manifest(fw_dir):
    path = os.path.join(fw_dir, "flasher_args.json")
    if not os.path.isfile(path):
        raise FileNotFoundError("Firmware não encontrado (falta flasher_args.json em %s)." % fw_dir)
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    for rel in manifest.get("flash_files", {}).values():
        if not os.path.isfile(os.path.join(fw_dir, rel)):
            raise FileNotFoundError("Arquivo de firmware ausente: %s" % rel)
    return manifest


def esptool_args(port, fw_dir, manifest, baud=460800):
    extra = manifest.get("extra_esptool_args", {})
    args = ["--chip", extra.get("chip", "esp32"), "--port", port, "--baud", str(baud),
            "--before", extra.get("before", "default_reset"),
            "--after", extra.get("after", "hard_reset")]
    if not extra.get("stub", True):
        args.append("--no-stub")
    args.append("write_flash")
    args += list(manifest.get("write_flash_args", []))
    for off, rel in sorted(manifest["flash_files"].items(), key=lambda kv: int(kv[0], 16)):
        args += [off, os.path.abspath(os.path.join(fw_dir, rel))]
    return args


def command(port):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--flash", port]
    return [sys.executable, "-u", os.path.abspath(__file__), port]


def run(port):
    try:
        fw = firmware_dir()
        args = esptool_args(port, fw, load_manifest(fw))
        print("Gravando firmware em %s..." % port, flush=True)
        import esptool
        esptool.main(args)
    except SystemExit as e:
        if e.code in (None, 0):
            print("FLASH OK", flush=True)
            return 0
        print("FLASH ERRO: esptool terminou com código %s" % e.code, flush=True)
        return 1
    except Exception as e:
        print("FLASH ERRO: %s" % e, flush=True)
        return 1
    print("FLASH OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
