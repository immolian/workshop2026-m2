# PROJECT RESILIENCE-ALPHA

Démonstrateur de **cyber-résilience et reprise autonome** sur une plateforme de
paiement fictive. Une attaque (DoS applicatif) sature le service, **deux
détecteurs indépendants** la repèrent, le moteur de remédiation **décide et agit
seul** (restart), puis **prouve la reprise** par une transaction canari réussie —
le tout **sans aucune intervention humaine**.

> **Résultat mesuré (VM, 20/10/2026)** : reprise autonome en **~3,7 s**
> (restart → `/health` → transaction canari → `recovery_confirmed`).
> Deux détecteurs convergent sur la même remédiation : **3,67 s** quand c'est le
> modèle ML qui déclenche, **3,71 s** quand c'est la latence. Défense en profondeur.

Ce README permet à un évaluateur de **déployer, armer, attaquer et vérifier** le
système de bout en bout sans l'équipe. La séquence de démo pas-à-pas validée est
dans [`docs/DEMO-runbook.md`](docs/DEMO-runbook.md) (source de vérité).

---

## 1. Architecture

### Les 5 piliers et où ils vivent dans le repo

| Pilier | Composant(s) | Dossier |
|---|---|---|
| SI métier (paiement) | `payment-api`, `auth`, `db` (PostgreSQL) | `services/payment-api`, `services/auth` |
| Cybersécurité | WAF (seule entrée), scénarios d'attaque | `services/frontend`, `attack/` |
| Observabilité | Prometheus, Alertmanager, Loki, Promtail, Grafana | `observability/` |
| IA / détection | `ml-detector` (IsolationForest) | `services/ml-detector` |
| IA / assistance | `rag-assistant` — **code présent, non déployé** (Ollama absent) | `services/rag-assistant` |
| Reprise autonome | `remediation-engine` + `docker-socket-proxy` | `services/remediation-engine` |
| Industrialisation | Déploiement/reset reproductibles (Ansible) | `ansible/` |

### Flux attaque → détection → remédiation → reprise

```
   PC/VM attaquant
        │  POST /transaction (flood authentifié)
        ▼
   WAF :8080 ───► payment-api ──(métriques)──► Prometheus
        (seule entrée exposée)                     │
                                                    ├─► règle HighLatency  (p95 > 0,5 s)
   ml-detector ──(anomaly_score)──► Prometheus ─────┼─► règle AnomalyDetected (score > 0,8)
   (IsolationForest, scrute les métriques)          │
                                                    ▼
                                            Alertmanager ──(webhook)──► remediation-engine
                                                                               │
                                     décision (cooldown + allowlist) ──────────┤
                                                                               ▼
                                                            docker-socket-proxy (POST restart)
                                                                               │
                                                                               ▼
                                                                    restart payment-api
                                                                               │
                        preuve de reprise :  /health OK  ──►  login auth (JWT)  ──►
                        transaction canari POST /transaction ──► 200 OK  ✅  recovery_confirmed
                                                                               │
   Tout est journalisé (JSON) ──► Promtail ──► Loki ──► Grafana (état avant / pendant / après)
```

**Point clé noté** : un simple restart ne prouve rien. La reprise n'est confirmée
qu'après une **vraie transaction métier** (canari authentifié par JWT sur un
compte seedé). Le moteur journalise `recovery_confirmed` ou `recovery_failed`.

### Segmentation réseau

- **`edge-net`** (bridge) : seul réseau atteignable depuis l'hôte. N'y publient
  que le **WAF** (`:8080`) et **Grafana** (`:3000`).
- **`backend-net`** (`internal: true`) : aucune route vers l'extérieur. DB,
  `payment-api`, `auth`, toute l'observabilité, le `ml-detector` et le moteur de
  remédiation y vivent **sans port publié sur l'hôte**.

---

## 2. Prérequis

**Machine cible** (déploie la stack) :
- Linux (Debian 12/13 validé), ~4 vCPU / 4 Go RAM / 15 Go disque.
- **Docker Engine + plugin Compose v2** (`docker compose`, pas `docker-compose`).
- Git.

**Déploiement automatisé** (optionnel) : un contrôleur avec **Ansible** +
`sshpass`, accès SSH sudo à la cible. Ansible installe Docker lui-même.

**Pour jouer l'attaque** : Python 3.11+ et `pip install -r attack/requirements.txt`
(dépend de `httpx`). Depuis la VM cible, tout est déjà présent dans les conteneurs.

---

## 3. Déploiement

### Option A — Docker Compose (manuel, le plus rapide)

```bash
cp .env.example .env
# Éditer .env : mettre HOST_IP = IP de la machine (sur la VM : `hostname -I`)
docker compose up -d --build
docker compose ps                 # attendre que tous les services soient "healthy"
```

Le premier build prend quelques minutes. `docker compose ps` doit afficher tous
les conteneurs en `healthy` (healthchecks définis sur chaque service).

> **Secrets** : `.env.example` fournit des **valeurs de démo** (lab fictif) qui
> suffisent à lancer la stack telle quelle. **Aucun secret réel n'est versionné**
> et le compose n'a aucune valeur de repli en dur : si une variable
> (`JWT_SECRET`, `POSTGRES_PASSWORD`, `GRAFANA_PASSWORD`) est **vidée**, la stack
> **refuse de démarrer**. En production : remplacer ces valeurs par des secrets
> forts (gérés via SOPS), dans le `.env` local jamais commité.

### Option B — Ansible (reproductible, depuis une Debian vierge)

Depuis le dossier `ansible/` (voir [`ansible/README.md`](ansible/README.md)) :

```bash
ansible-playbook deploy.yml -l ws26-docker -k -K     # -k: mdp SSH, -K: mdp sudo
```

Le playbook installe Docker, clone le repo, génère `.env`, renseigne `HOST_IP`,
lance la stack et **vérifie** que tout est `healthy` + que l'API répond via le WAF.
Idempotent : rejouable sans risque. L'inventaire (`ansible/inventory.ini`) cible la
VM d'intégration `ws26-docker` (`10.0.40.114`) et une VM de test jetable.

### Accès

| Interface | URL | Exposé à l'hôte ? | Identifiants |
|---|---|---|---|
| API paiement (via WAF) | `http://<HOST_IP>:8080` | **oui** — seule entrée applicative | — |
| Grafana (supervision) | `http://<HOST_IP>:3000` | **oui** — pour le jury | `admin` / valeur de `GRAFANA_PASSWORD` du `.env` (démo : `demo-admin-lab`) |
| DB, Prometheus, Alertmanager, Loki, `ml-detector`, remédiation, proxy Docker | — | **non** (réseau `backend-net` interne) | — |

> `<HOST_IP>` = valeur de `HOST_IP` dans `.env`. La stack écoute sur toutes les
> interfaces (aucune IP figée dans `docker-compose.yml`).

---

## 4. Jouer la démo

> Séquence complète et commentée : [`docs/DEMO-runbook.md`](docs/DEMO-runbook.md).
> Résumé des étapes clés ci-dessous.

### 4.1 Armer le moteur de remédiation

Par défaut `DRY_RUN=true` : le moteur **journalise sans agir** (état sûr). Pour la
démo, l'**armer** :

```bash
# Dans .env : DRY_RUN=false
docker compose up -d remediation-engine
docker compose exec remediation-engine printenv DRY_RUN   # DOIT afficher: false
```

> ⚠️ **Piège connu** : les resets (`reset.yml`) et un `.env` par défaut repassent
> en `DRY_RUN=true`. **Toujours** vérifier avec `printenv DRY_RUN` avant une démo.

### 4.2 Récupérer un token (compte de démo seedé `demo` / `demo123`)

```bash
JWT=$(docker compose exec -T auth python -c "import urllib.request,json;d=json.dumps({'username':'demo','password':'demo123'}).encode();r=urllib.request.urlopen(urllib.request.Request('http://localhost:8000/auth/login',data=d,headers={'Content-Type':'application/json'}));print(json.load(r)['access_token'])")
echo "${JWT:0:40}..."     # doit afficher un début de JWT
```

> `demo`/`demo123` est un **compte de démo fictif** documenté, seedé au démarrage.
> Aucun secret réel n'est présent dans le repo.

### 4.3 Ouvrir la supervision

Grafana → `http://<HOST_IP>:3000` → dashboard **« RESILIENCE-ALPHA — Supervision & reprise »**.
Garder visibles : débit, **latence p95** (ligne de seuil rouge à 0,5 s),
**anomaly_score** (seuil 0,8), et la **timeline de remédiation** (logs Loki).

### 4.4 Lancer l'attaque (DoS authentifié, palier de démo validé)

Depuis la **VM cible** (local) — palier validé = **300 workers** :

```bash
python3 attack/dos_flood.py --token "$JWT" --account acc_demo --concurrency 300 --duration 60
```

Depuis un **PC attaquant distinct** (ex. Kali), viser le WAF :

```bash
python3 attack/dos_flood.py --target http://<HOST_IP>:8080 --token "$JWT" --account acc_demo --concurrency 300 --duration 60
```

> **Garde-fou de périmètre** (`attack/_safety.py`) : les scripts **refusent** toute
> cible qui n'est pas loopback ou une **IP privée** (RFC 1918, dont `10.0.40.0/24`
> et `192.168.137.0/24`). Aucune cible publique n'est acceptée.
>
> **Sans `--token`** : le flood ne reçoit que des `401`, n'atteint pas l'API et ne
> déclenche rien. **Toujours** passer `--token "$JWT"`.
>
> **Durée** : garder `--duration ≥ 45 s` pour laisser l'alerte se déclencher
> (fenêtres de 30 s + `for: 15s`/`10s`).

---

## 5. Vérifier que ça marche (preuve de reprise)

**Sur le dashboard** : la latence p95 franchit la ligne rouge à **0,5 s** et
`anomaly_score` franchit **0,8** pendant l'attaque.

**Dans les logs du moteur** (séquence journalisée, corrélée par `incident_id`) :

```bash
docker compose logs --tail=50 remediation-engine | grep -iE "alertname|decision|recovery"
```

Séquence attendue :

```
alert_received      AnomalyDetected (et/ou HighLatency)   firing
decision            execute      target: payment-api
action_done         payment-api  running
verify_health_ok    payment-api
verify_canary_ok    payment-api  tx_id=...
recovery_confirmed  time_to_recover_s ≈ 3,7 s
```

**La preuve de succès** = le log `recovery_confirmed` **et** une nouvelle
transaction fictive réussie après l'incident, **sans aucune action humaine**.

### Règles d'alerte réelles (`observability/prometheus/rules.yml`)

| Alerte | Condition | Déclenche sur le DoS ? |
|---|---|---|
| `ServiceDown` | `up{job="payment-api"} == 0` pendant 10 s | panne franche (ex. `docker compose stop`) |
| `HighLatency` | p95 `request_latency_seconds` > **0,5 s** pendant 15 s | **oui** — signal fiable du DoS |
| `AnomalyDetected` | `anomaly_score` > **0,8** pendant 10 s | **oui** — détection ML |
| `HighErrorRate` | ratio 5xx > 25 % pendant 15 s | **rarement** — voir ci-dessous |

> **Pourquoi deux détecteurs et pas les 5xx** : au calibrage, `payment-api` met les
> requêtes **en file** au lieu de les rejeter (≈ 0 erreur serveur, même à ~280 req/s).
> `HighErrorRate` ne déclenche donc pas sur ce DoS. Le signal fiable est la **latence
> p95** (× ~30 : 0,022 s → 0,66 s), confirmée en parallèle par le **score ML**.

---

## 6. Sécurité (Axe 2)

- **Segmentation réseau** : `backend-net` est `internal: true`. DB, secrets et
  interfaces de gestion ne sont **jamais** publiés sur le réseau pédagogique. Seuls
  WAF et Grafana sont exposés.
- **Moindre privilège Docker** : le moteur n'accède **jamais** au socket Docker brut.
  Il passe par `docker-socket-proxy`, à périmètre restreint : `EXEC=0`, `IMAGES=0`,
  `VOLUMES=0`, `NETWORKS=0`, `INFO=0`. Pas de shell distant, pas de pull d'image.
- **Garde-fous du moteur** : **cooldown 60 s/cible** (anti restart-storm),
  **liste blanche** de cibles (`payment-api`, `auth` — une alerte visant `db` ou le
  proxy est refusée), et mode `DRY_RUN` sûr par défaut.
- **Secrets** : **aucun secret réel versionné**. Le compose et le code n'ont
  **aucune valeur de repli en dur** — la stack lit `JWT_SECRET`,
  `POSTGRES_PASSWORD` et `GRAFANA_PASSWORD` depuis le `.env` local et **refuse de
  démarrer** si l'un manque. `.env.example` ne contient que des **valeurs de démo**
  (lab fictif). `.env` est **git-ignoré** ; **gitleaks** en pré-commit
  (`.pre-commit-config.yaml`) bloque toute fuite ; chaîne **SOPS/age** amorcée
  (`.sops.yaml`, clé `age` à renseigner avant usage réel).

### Risque résiduel connu (à reprendre dans l'EBIOS)

- `docker-socket-proxy` autorise `POST` au **niveau conteneurs** (`POST=1`) : ce
  n'est pas un toggle « restart seul ». Un moteur compromis pourrait créer/piloter
  des conteneurs. Le `:ro` sur le socket ne protège pas des écritures d'API.
- `/webhook` du moteur **n'est pas authentifié** : tout service de `backend-net`
  peut demander un restart (borné par allowlist + cooldown → au pire un DoS lent).
- Pistes de durcissement : ACL/proxy dédié au seul restart, bearer token
  Alertmanager vérifié par le moteur, conteneurs cibles en `read_only`.

Le détail est documenté en tête de `services/remediation-engine/app.py`.

---

## 7. Structure du dépôt

```
.
├── docker-compose.yml          # Source de vérité du déploiement (services, réseaux, healthchecks)
├── .env.example                # Modèle de config (copier en .env, jamais commité)
├── Makefile                    # Raccourcis (up/arm/...) — make absent de la VM, cf. commandes directes
├── ansible/                    # Déploiement & reset reproductibles (deploy.yml, reset.yml)
├── attack/                     # Scénarios offensifs : dos_flood.py (primaire), sqli_probe.py + garde-fou
├── docs/
│   └── DEMO-runbook.md         # Séquence de démo validée (source de vérité)
├── observability/
│   ├── prometheus/             # Scrape + règles d'alerte (rules.yml)
│   ├── alertmanager/           # Route le webhook vers le moteur
│   ├── loki/ · promtail/       # Collecte et stockage des logs
│   └── grafana/provisioning/   # Datasources + dashboard de supervision (provisionnés)
└── services/
    ├── payment-api/            # API de paiement (FastAPI + PostgreSQL), métriques figées
    ├── auth/                   # Authentification JWT HS256 (/auth/login, /auth/verify)
    ├── ml-detector/            # IsolationForest -> gauge anomaly_score (model.joblib, calibration)
    ├── remediation-engine/     # Reçoit les alertes, restart via proxy, PROUVE la reprise (canari)
    ├── rag-assistant/          # Assistant RAG (app.py, ingest.py, ask.py) — NON déployé (Ollama absent)
    └── frontend/               # WAF nginx (reverse-proxy, seule entrée exposée)
```

---

## 8. Contributions par membre

| Membre | Pilier | Périmètre |
|---|---|---|
| **Gabriel** | Dév + Red Team | `services/payment-api`, `services/auth`, `attack/` |
| **Claire** | Infra / Observabilité | `observability/`, `ansible/`, `docker-compose.yml` |
| **Mahalia** | IA / Data | `services/ml-detector` ; `services/rag-assistant` (code livré, non déployé — Ollama absent) |
| **Tom** | Remédiation + Intégration + PM | `services/remediation-engine`, `services/frontend`, intégration |
| **Mathilde** | Gouvernance | `docs/` (EBIOS, PCA/PRA, NIS2/DORA) |

---

## 9. Limites connues & ce qu'on ferait différemment

- **WAF** : simple reverse-proxy nginx. Pas de rate-limiting ni de règles OWASP
  CRS (ModSecurity/Coraza) — prévu en durcissement. Il n'oppose donc pas encore de
  défense active au DoS ; c'est le moteur de remédiation qui assure la résilience.
- **`HighErrorRate`** conservée mais peu pertinente pour ce DoS (file d'attente,
  ≈ 0 erreur 5xx) : la détection repose sur la **latence** et le **ML**.
- **`scale` et `block`** sont des `TODO` explicites dans le moteur (hors périmètre
  du sprint) ; seul `restart` est implémenté.
- **`rag-assistant`** : le **code existe** (`app.py`, `ingest.py`, `ask.py` —
  assistant RAG en lecture seule, documentation de l'équipe, sans accès privilégié)
  mais le service **n'est pas déployé** : il dépend d'**Ollama** (modèle LLM +
  embeddings via `langchain_ollama`), absent de l'environnement. Sa définition reste
  commentée dans `docker-compose.yml` pour ne pas bloquer la stack.
- **SOPS** : chaîne amorcée mais clé `age` à renseigner — les seuls secrets du
  sprint sont des **valeurs de démo** (lab fictif), pas des secrets réels à protéger.
- **`make`** n'est pas installé sur la VM : utiliser les commandes `docker compose`
  directes de ce README plutôt que les cibles du `Makefile`.
- **Prochaines étapes** : durcissement WAF (CRS + rate-limit), authentification du
  `/webhook`, proxy Docker restreint au seul restart, dashboard React en complément
  de Grafana.
