.PHONY: up down logs ps attack arm disarm
up:       ## Démarre la stack
	docker compose up -d --build
down:     ## Arrête tout
	docker compose down
logs:     ## Logs de la remédiation
	docker compose logs -f remediation-engine
ps:
	docker compose ps
attack:   ## Lance le DoS (depuis le PC/VM attaquant)
	python3 attack/dos_flood.py
arm:      ## Active la remédiation réelle (DRY_RUN=false)
	DRY_RUN=false docker compose up -d remediation-engine
disarm:   ## Repasse en mode log seul
	DRY_RUN=true docker compose up -d remediation-engine
