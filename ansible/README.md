# Playbooks Ansible — owner: Claire

Automatisation des opérations du cahier des charges :
- `deploy.yml` : prépare l'hôte + `docker compose up -d` (déploiement reproductible)
- `reset.yml`  : remet l'environnement à un état propre (pour répéter la démo)

## Ansible vs Compose

- **Ansible** prépare la machine : paquets, Docker, utilisateurs, récupération du code,
  configuration (`.env`), puis lance la stack et vérifie qu'elle est saine.
- **Docker Compose** décrit les conteneurs eux-mêmes (`docker-compose.yml`) : images,
  réseaux, volumes, healthchecks, ordre de démarrage.

Ansible ne remplace pas Compose : il l'appelle, sur une machine qu'il a préparée.

## Prérequis

- Contrôleur (machine qui lance les playbooks) : `sudo apt install -y ansible sshpass`
- Cibles : Debian 12/13 minimale, serveur SSH, utilisateur `claire` avec sudo.
- Se connecter une première fois en SSH à chaque cible pour accepter son empreinte.

## Utilisation

Depuis ce dossier `ansible/` :

```bash
# VM de test (repartir du snapshot Proxmox "clean-os" avant chaque essai)
ansible-playbook deploy.yml -l ws26-docker-test -k -K

# VM d'intégration (mise à jour de la stack de l'équipe)
ansible-playbook deploy.yml -l ws26-docker -k -K
```

`-k` demande le mot de passe SSH, `-K` le mot de passe sudo.
Le playbook est idempotent : le relancer ne casse rien et ne refait que le nécessaire.

## Rejouer la démo : reset.yml

```bash
# Reset LÉGER (défaut) : base re-seedée, services métier recréés,
# historique Prometheus/Loki/Grafana CONSERVÉ -> jour de la démo, Clip Chrono
ansible-playbook reset.yml -l ws26-docker -k

# Reset COMPLET : docker compose down -v + rebuild, tout est effacé
# -> répétitions et debug
ansible-playbook reset.yml -l ws26-docker -k -e mode=full
```

Pas de `-K` : l'utilisateur est dans le groupe `docker`, sudo n'est pas nécessaire.
Dans les deux modes, la remédiation est remise en `DRY_RUN=true` (désarmée).
Pour la réarmer : `DRY_RUN=false` dans `.env`, puis `docker compose up -d remediation-engine`,
et vérifier avec `docker compose exec remediation-engine printenv DRY_RUN`.
