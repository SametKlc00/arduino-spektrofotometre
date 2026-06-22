import csv
from datetime import datetime
import serial

PORT = "COM6"
BAUD = 9600
OUT = "tsl2591_olcum_kaydi.csv"

with serial.Serial(PORT, BAUD, timeout=2) as ser, open(OUT, "a", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp", "raw_line"])
    print("Kayıt başladı. Durdurmak için Ctrl+C.")

    while True:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue
        print(line)
        writer.writerow([datetime.now().isoformat(timespec="seconds"), line])
        f.flush()
