.PHONY: reset-local reset-history

## Remove all local Rudder release history and restart the development stack.
## This is intentionally local-only: it acts on docker-compose.dev.yml and
## release projects created by the local Rudder agent.
reset-local:
	bash scripts/reset-local.sh

## Backwards-friendly name for the same destructive local reset.
reset-history: reset-local
