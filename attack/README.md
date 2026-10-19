# Scénarios offensifs — owner: Gabriel

PÉRIMÈTRE STRICT : uniquement le SI fictif du groupe, sur le réseau du consortium.
Jamais le campus, un autre groupe ou un service tiers.

## Primaire (démontré au Clip Chrono) : DoS applicatif
`dos_flood.py` — flood concurrent de POST /transaction via le WAF (port 8080).
Effet observable : montée du rate + latence + 5xx -> alerte -> remédiation.

## Secondaire (Axe 2, hors Clip Chrono) : injection applicative
Tentative SQLi/payload malveillant bloquée par le WAF, loggée au SIEM/Loki.
Sert à prouver l'interconnexion des piliers, PAS la reprise de disponibilité.
