import serial, sys, time
# Uso: serlog.py PORTA ARQUIVO SEGUNDOS [--reset]
# Sem --reset so escuta (nao reinicia a placa ao abrir a porta).
port, out, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
reset = "--reset" in sys.argv[4:]
s = serial.Serial()
s.port, s.baudrate, s.timeout = port, 115200, 0.5
s.dtr = False; s.rts = False  # definidos antes de abrir: nao mexe no EN/BOOT
s.open()
if reset:
    s.rts = True; time.sleep(0.1); s.rts = False  # reinicia para capturar o boot
end = time.time() + secs
with open(out, "w", encoding="utf-8", errors="replace") as f:
    while time.time() < end:
        line = s.readline()
        if line:
            f.write(time.strftime("%H:%M:%S ") + line.decode("utf-8", "replace").rstrip() + "\n")
            f.flush()
