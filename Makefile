# Local production stack wrapper (SoT PART D1). Dev stack has no equivalent
# here on purpose — run docker-compose.dev.yml directly (see infra/README.md).

.PHONY: prod-up prod-down

prod-up:
	docker compose -f infra/docker-compose.prod.yml up -d --build

prod-down:
	docker compose -f infra/docker-compose.prod.yml down
