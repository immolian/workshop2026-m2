"""Entraîne IsolationForest sur le trafic normal, calibre le score 0..1 avec le flood."""
import csv
import json
import math

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from features import FEATURES


def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append([float(r[name]) for name in FEATURES])
    return np.array(rows)


normal = load_csv("data/normal.csv")
flood = load_csv("data/flood.csv")

# 1. Entraînement UNIQUEMENT sur le trafic normal
model = make_pipeline(
    StandardScaler(),
    IsolationForest(n_estimators=200, random_state=42),
)
model.fit(normal)

d_norm = model.decision_function(normal)

# 2. flood.csv contient des moments d'attaque ET des moments calmes entre les flood.
#    On isole les lignes vraiment en pleine attaque : req_rate nettement au-dessus
#    de la moyenne normale (feature 0 = req_rate).
req_rate_normal_mean = normal[:, 0].mean()
attack_mask = flood[:, 0] > (req_rate_normal_mean * 2)
flood_attack = flood[attack_mask]

print(f"lignes flood total={len(flood)}  lignes vraiment en attaque={len(flood_attack)}")

d_flood_attack = model.decision_function(flood_attack)

print(f"normal        : min={d_norm.min():.3f} moyenne={d_norm.mean():.3f} max={d_norm.max():.3f}")
print(f"flood (attaque) : min={d_flood_attack.min():.3f} médiane={np.median(d_flood_attack):.3f} max={d_flood_attack.max():.3f}")

# 3. Calibration : un percentile raisonnable du normal (pas l'extrême) -> 0.5
#    la médiane des VRAIES lignes d'attaque -> 0.95
center = float(np.percentile(d_norm, 10))
med_attack = float(np.median(d_flood_attack))
k = math.log(19) / (center - med_attack)
assert k > 0, (
    f"Séparation insuffisante (center={center:.3f}, med_attack={med_attack:.3f}). "
    "Il faut plus de contraste entre normal et flood."
)


def to_score(d):
    return 1 / (1 + np.exp(k * (np.asarray(d) - center)))


print(f"score normal (pire cas) : {to_score(d_norm).max():.3f}")
print(f"score flood  (pire cas, le moins anormal) : {to_score(d_flood_attack).min():.3f}")

joblib.dump(model, "model.joblib")
json.dump({"center": center, "k": k}, open("calibration.json", "w"))
print("Fichiers sauvegardés : model.joblib, calibration.json")