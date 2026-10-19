# frontend — dashboard de supervision (React + Tailwind) — owner: Tom

NB : le "frontal web" du sujet = ce dashboard de supervision, pas une UI de
paiement. Il doit rendre visible l'état du service AVANT / PENDANT / APRÈS
l'incident (exigence jury). Pour gagner du temps, Grafana (port 3000) peut
servir de dashboard principal ; ce React vient en complément si le temps le
permet.

À brancher sur : Prometheus (métriques temps réel) + /health des services
+ timeline des actions de remédiation (logs Loki).
