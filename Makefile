.PHONY: reset-local reset-history kind-up kind-down kind-control-plane verify-kind gke-preflight gke-bootstrap gke-verify

## Remove all local Rudder release history and restart the development stack.
## This is intentionally local-only: it acts on docker-compose.dev.yml and
## release projects created by the local Rudder agent.
reset-local:
	bash scripts/reset-local.sh

## Backwards-friendly name for the same destructive local reset.
reset-history: reset-local

## Create the isolated local Kind cluster, local registry bridge, and ingress.
kind-up:
	bash infra/kind/bootstrap.sh

## Delete only the local Kind cluster. The normal Docker development stack is untouched.
kind-down:
	kind delete cluster --name rudder-kind

## Restart only the control plane with the local Kubernetes runtime selected.
kind-control-plane:
	RUDDER_RUNTIME=kubernetes RUDDER_REGISTRY=kind-registry:5000 docker compose -f docker-compose.dev.yml -f docker-compose.kind.yml up -d --build --force-recreate control-plane

## Exercise the real Kubernetes adapter against Kind and verify a public ingress.
verify-kind:
	cd control-plane && uv run python scripts/verify_kind.py

## Read-only production gate: verifies Terraform ADC, live GKE health, and CPU quota.
gke-preflight:
	bash infra/gcp/scripts/preflight-gke.sh

## Install or reconcile shared GKE platform components from explicit operator inputs.
## Required RUDDER_* and pinned chart-version variables are validated by the script.
gke-bootstrap:
	bash infra/gcp/scripts/bootstrap-platform.sh

## Read-only verification of the shared Phase 4 GKE platform contract.
gke-verify:
	bash infra/gcp/scripts/verify-gke.sh
