import serial, sys, time
port, out, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
s = serial.Serial(port, 115200, timeout=0.5)
s.dtr = False; s.rts = True; time.sleep(0.1); s.rts = False  # reset board to capture boot
end = time.time() + secs
with open(out, "w", encoding="utf-8", errors="replace") as f:
    while time.time() < end:
        line = s.readline()
        if line:
            f.write(time.strftime("%H:%M:%S ") + line.decode("utf-8", "replace").rstrip() + "\n")
            f.flush()
