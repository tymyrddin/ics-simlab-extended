# ICS-SimLab Extended
# Targets handle the generate → build → start lifecycle.
# Requires: docker, docker compose, python3, pyyaml

CONFIG ?= orchestrator/ctf-config.yaml
JUMP_HOST_COMPOSE = infrastructure/jump-host/docker-compose.yml

p.PHONY: help generate build build-jump-host up down stop start start-jump-host stop-jump-host deploy firewall clean purge test test-unit test-artifacts test-smoke test-firewall

help:
	@echo "Usage:"
	@echo "  make generate          Read $(CONFIG), write all docker-compose.yml files"
	@echo "  make build             Build all zone images (runs generate first)"
	@echo "  make build-jump-host   Build the jump host image"
	@echo "  make up                Start all zones + jump host (runs generate first)"
	@echo "  make down              Stop and remove all zones + jump host"
	@echo "  make stop              Stop containers without removing them"
	@echo "  make firewall          Apply inter-zone iptables rules (sudo)"
	@echo "  make clean             down + remove all generated files"
	@echo "  make purge             clean + remove all images"
	@echo ""
	@echo "  make deploy            Alias for make up"
	@echo "  make start-jump-host   Start jump host only"
	@echo "  make stop-jump-host    Remove jump host container"
	@echo ""
	@echo "  make test-unit         Run unit tests (no Docker)"
	@echo "  make test-artifacts    Run generate.py then check all output files"
	@echo "  make test-smoke        Run smoke tests (requires Docker images)"
	@echo "  make test-firewall     Run firewall tests (requires root + Docker)"
	@echo "  make test              Run unit + artifact + smoke tests"
	@echo ""
	@echo "  CONFIG=path/to/ctf-config.yaml make generate   (use alternate config)"

generate:
	python3 orchestrator/generate.py $(CONFIG)

build: generate
	docker compose -f infrastructure/networks/docker-compose.yml build
	docker compose -f zones/enterprise/docker-compose.yml build
	docker compose -f zones/operational/docker-compose.yml build
	docker compose -f zones/control/docker-compose.yml build

build-jump-host: generate
	docker compose -f $(JUMP_HOST_COMPOSE) build

up: generate
	bash start.sh
	docker compose -f $(JUMP_HOST_COMPOSE) up -d

down:
	@[ -f $(JUMP_HOST_COMPOSE) ] && docker compose -f $(JUMP_HOST_COMPOSE) down || docker rm -f jump-host 2>/dev/null || true
	@[ -f stop.sh ] && bash stop.sh || true

stop:
	@[ -f stop.sh ] && bash stop.sh || echo "stop.sh not found — run 'make generate' first"

start:
	@[ -f start.sh ] && bash start.sh || echo "start.sh not found — run 'make generate' first"
	@[ -f $(JUMP_HOST_COMPOSE) ] && docker compose -f $(JUMP_HOST_COMPOSE) up -d || true

start-jump-host:
	docker compose -f $(JUMP_HOST_COMPOSE) up -d

stop-jump-host:
	@[ -f $(JUMP_HOST_COMPOSE) ] && docker compose -f $(JUMP_HOST_COMPOSE) down || true

deploy: up

clean: down
	rm -f start.sh stop.sh
	rm -f infrastructure/networks/docker-compose.yml
	rm -f zones/enterprise/docker-compose.yml
	rm -f zones/operational/docker-compose.yml
	rm -f zones/control/docker-compose.yml
	rm -f infrastructure/jump-host/docker-compose.yml
	rm -f infrastructure/jump-host/adversary-readme.txt

firewall:
	sudo bash infrastructure/firewall.sh

purge: clean
	docker compose -f infrastructure/networks/docker-compose.yml down --rmi all 2>/dev/null || true
	docker compose -f zones/enterprise/docker-compose.yml down --rmi all 2>/dev/null || true
	docker compose -f zones/operational/docker-compose.yml down --rmi all 2>/dev/null || true
	docker compose -f zones/control/docker-compose.yml down --rmi all 2>/dev/null || true
	-docker compose -f $(JUMP_HOST_COMPOSE) down --rmi all 2>/dev/null || true

test-unit:
	pytest tests/unit/ -v

test-artifacts: generate
	pytest tests/integration/ -v

test-smoke:
	@for f in tests/smoke/test_*.sh; do bash "$$f" || true; done

test-firewall:
	sudo bash tests/smoke/test_firewall.sh

test: test-unit test-artifacts test-smoke