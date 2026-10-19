# PROJECT RESILIENCE-ALPHA — Workshop2026-M2-G\<n\>

Démonstrateur de **cyber-résilience et reprise autonome** sur une plateforme de
paiement fictive. Objectif noté : une attaque déclenche une anomalie, le système
la détecte, décide et exécute une remédiation **sans intervention humaine**, puis
une nouvelle transaction fictive réussit.

> Remplacer `<n>` par le numéro d'équipe dans le nom du dossier au rendu.

---

## Démarrage rapide

```bash
cp .env.example .env            # ajuster si besoin (secrets réels -> SOPS)
docker compose up -d --build    # ou : make up
docker compose ps               # tous les services doivent être "healthy"
```

Accès :
| Interface | URL | Exposé ? |
|---|---|---|
| API paiement (via WAF) | http://<HOST_IP>:8080 | oui (seule entrée applicative) |
| Grafana (supervision) | http://<HOST_IP>:3000 | oui (jury) |
| DB, Prometheus, Alertmanager, remédiation | — | **non** (réseau interne) |

> **IP du HomeLab** : remplacer `<HOST_IP>` par l'IP de la VM Docker (`HOST_IP` dans `.env`).
> Le `docker-compose.yml` n'a aucune IP figée : la stack écoute sur toutes les interfaces.


---

## Contrat d'interface — FIGÉ (ne pas modifier sans accord équipe)

Tout le monde code contre ces interfaces. Les changer casse la remédiation et le ML.

### Endpoints API (`payment-api`)
| Méthode | Route | Rôle |
|---|---|---|
| GET | `/health` | sonde de vie → `{"status":"ok"}` |
| GET | `/metrics` | métriques Prometheus |
| POST | `/transaction` | crée une transaction fictive |
| GET | `/balance/{account_id}` | solde fictif |
| POST | `/auth/login` | (service `auth`) renvoie un token |

### Métriques exposées (consommées par Prometheus → alertes)
- `http_requests_total{method,endpoint,status}`
- `request_latency_seconds` (histogram, label `endpoint`)
- `anomaly_score` (gauge 0..1, exposée par `ml-detector`)

### Contrat d'alerte → remédiation (annotations Prometheus)
```
action = restart | scale | block      # ce que fait le moteur
target = <nom_de_conteneur>           # sur quel conteneur
```

### Noms de conteneurs (stables — ciblés par la remédiation)
`db` · `auth` · `payment-api` · `waf` · `ml-detector` · `remediation-engine`
`prometheus` · `alertmanager` · `loki` · `promtail` · `grafana` · `docker-socket-proxy`

---

## Flux de reprise autonome

```
Attaque (PC/VM attaquant) ─► WAF ─► payment-api
        │                               │ métriques
        ▼                               ▼
   pic rate/latence/5xx          Prometheus ─► règle d'alerte
                                        │
                              Alertmanager (webhook)
                                        ▼
                             remediation-engine
                                        │ action via
                                        ▼
                             docker-socket-proxy ─► restart payment-api
                                        │
                     Nouvelle transaction fictive ─► 200 OK  ✅ reprise prouvée
   Tout est journalisé ─► Loki ─► Grafana (état avant/pendant/après)
```

**Modes :** `DRY_RUN=true` (défaut) = la remédiation **journalise sans agir**.
`make arm` passe en `DRY_RUN=false` = exécution réelle (à activer mercredi).

---

## Sécurité (notée — Axe 2)

- **Segmentation** : `backend-net` est `internal: true`. DB, secrets et interfaces
  de gestion ne sont jamais publiés sur le réseau pédagogique.
- **Moindre privilège Docker** : le moteur de remédiation n'accède **jamais** au
  socket Docker brut. Il passe par `docker-socket-proxy` (lecture conteneurs +
  POST restart uniquement ; `EXEC=0`, `IMAGES=0`, `VOLUMES=0`).
  > ⚠️ Limite connue : le proxy autorise `POST` au niveau conteneurs (pas un
  > toggle "restart" seul). Résidu de risque à documenter dans l'EBIOS ;
  > durcissement possible (ACL dédiée) si le temps le permet.
- **Secrets** : aucun secret en clair. `.env` est git-ignoré ; les secrets réels
  sont chiffrés via **SOPS** (`secrets/*.sops.yaml`). Hook **gitleaks** en
  pré-commit pour bloquer toute fuite.

---

## Règles Git

- Brancher depuis `main` : `feat/<composant>` (ex. `feat/remediation-engine`).
- **Conventional Commits** : `feat:`, `fix:`, `docs:`, `chore:` (traçabilité = Axe 5).
- `main` toujours déployable → merge via Pull Request relue.
- `pre-commit install` dès le clone (anti-fuite de secrets).
- Chaque membre configure `git config user.name` / `user.email` avant de commiter.

---

## Répartition

| Dossier | Owner | Pilier |
|---|---|---|
| `services/payment-api`, `services/auth`, `attack/` | Gabriel | Dév + Red Team |
| `observability/`, `ansible/`, `docker-compose.yml` | Claire | Infra |
| `services/ml-detector`, `services/rag-assistant` | Mahalia | IA / Data |
| `services/remediation-engine`, `services/frontend`, intégration | Tom | PM + remédiation |
| `docs/` (EBIOS, PCA/PRA, NIS2/DORA, Dossier.pdf) | Mathilde | Gouvernance |
