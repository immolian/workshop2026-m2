"""Enregistre les features dans un CSV. Usage : python collect.py <sortie.csv> <durée_secondes>"""
import csv
import sys
import time

from features import fetch_features, FEATURES

out_path = sys.argv[1]
duration = int(sys.argv[2])
end_time = time.time() + duration

with open(out_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["ts"] + FEATURES)
    while time.time() < end_time:
        row = fetch_features()
        writer.writerow([int(time.time())] + row)
        f.flush()
        print(row)
        time.sleep(5)

print(f"Terminé : {out_path}")