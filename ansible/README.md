# Playbooks Ansible — owner: Claire

Automatisation des opérations du cahier des charges :
- deploy.yml  : prépare l'hôte + `docker compose up -d` (déploiement reproductible)
- reset.yml   : remet l'environnement à un état propre (pour répéter la démo)
Objectif : expliquer la place d'Ansible (provisioning/orchestration) vs Compose.
