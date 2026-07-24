# Compose Service Catalog Design

## Goal

Let Rudder import and operate multi-container applications predictably. A
repository-owned Compose manifest is the source of truth when present. For a
small, explicit catalog of common services, Rudder may instead generate a
reviewable Compose manifest from detected runtime metadata. No infrastructure
is inferred by an LLM or provisioned without confirmation.

## Scope and service tiers

### Repository Compose: general support

When a repository has `compose.yaml`, `compose.yml`, `docker-compose.yaml`, or
`docker-compose.yml`, Rudder validates and runs every declared service in one
isolated Compose project. This supports arbitrary application topology within
the platform safety policy, including web applications, workers, schedulers,
brokers, databases, search engines, observability tools, and model services.

Each declared Compose service becomes a first-class Rudder service on the
canvas. Services that publish a port are candidates for a public domain;
private services remain reachable only through the project network.

### Rudder-generated Compose: managed catalog

When no repository Compose file exists, Rudder will offer only tested,
deterministic templates. Import detection proposes roles and add-ons, while the
user confirms them before Rudder creates a project.

Initial catalog:

| Class | Generated options |
| --- | --- |
| App process | web, worker, scheduler, realtime gateway |
| Relational data | PostgreSQL, MySQL, MariaDB |
| Document data | MongoDB |
| Cache / lightweight queue | Redis, Memcached |
| Message broker | RabbitMQ, NATS |
| Search | Meilisearch, Typesense |
| Object storage | MinIO |
| Vector database | Qdrant |

Complex systems such as Kafka, OpenSearch, Temporal, Airflow, Prometheus,
Grafana, Loki, Ollama, and vLLM are supported through repository Compose, not
generated templates. This avoids unsafe or unreliable guesses about clusters,
storage, and resource requirements.

## Import flow

1. The user signs in through GitHub OAuth, selects an installed GitHub App
   connection, repository, and branch.
2. Rudder looks for a supported Compose filename at the selected ref.
3. If found, Rudder validates and normalizes that manifest, derives service
   roles and public-port candidates, and displays the exact plan for review.
4. If absent, Rudder reads supported manifests (initially `package.json` and
   process definitions) and proposes app roles plus catalog add-ons. The user
   selects the proposal and reviews the generated Compose plan.
5. On confirmation, Rudder creates service records, encrypted internal
   credentials, persistent named volumes where required, and a single Compose
   release deployment.

## Runtime and UI model

One Compose release owns all child containers. Rudder records a lifecycle for
the release and maps each service to that lifecycle, so a database, worker, or
broker never displays an unrelated `no deploys` state. Selecting any child
shows:

- its Compose role and whether it is public or private;
- the shared release state (`queued`, `building`, `live`, or `failed`);
- shared build/runtime logs with child-specific lifecycle events; and
- a clear "managed by Compose" control instead of a separate deploy action.

Only public web/realtime services receive a Rudder domain. Workers, schedulers,
databases, queues, and add-ons have private DNS and generated connection
variables. A multiple-public-service repository Compose import may expose one
or more explicitly declared public services; generated templates expose only
the web or realtime role selected by the user.

## Detection boundaries

Detection is evidence-based, not source-code speculation:

- package dependencies and scripts identify candidate runtimes, client
  libraries, and process commands;
- `Procfile` and compatible framework process definitions can identify `web`,
  `worker`, and scheduler candidates;
- existing connection variables take precedence and mark a dependency as
  externally managed;
- ambiguous cases are presented as optional suggestions, never silently
  provisioned.

## Safety policy

Imported manifests remain constrained: no host bind mounts or Docker socket,
privileged mode, host/custom network mode, fixed `container_name`, or direct
host port binding. Rudder owns project namespace, networking, encrypted
variables, persistent named volumes, health checks, and routing. Generated
plans use pinned supported images and named volumes for stateful services.

## Verification

Tests must cover manifest parsing, generated template validity, service-role
mapping, credential injection, private/public routing, lifecycle propagation,
and failed-release safety. End-to-end verification covers both a repository
Compose topology containing a web service, worker, and database, and a
generated Node topology with selected add-ons.
