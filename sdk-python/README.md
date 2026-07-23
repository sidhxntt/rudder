# sdk-python

`rudder_sdk` — the Python client for the Rudder control plane. **Generated from
the live OpenAPI schema. Do not hand-edit `rudder_sdk/`.**

Generator: [`openapi-python-client`](https://github.com/openapi-generators/openapi-python-client)
`0.29.0`. Output is `attrs` models + one module per operation over `httpx`,
sync and async.

## Install

```bash
pip install -e sdk-python
```

The package is checked in — a build artifact, but the CLI imports it, and
checking it in is what makes the editable install work without a control plane
running.

## Regenerate

The schema lives in the running control plane, so regeneration needs it up:

```bash
docker compose -f docker-compose.dev.yml up -d
pip install 'openapi-python-client==0.29.0'
./sdk-python/regenerate.sh            # RUDDER_URL=http://host:8000 to point elsewhere
```

`regenerate.sh` replaces `rudder_sdk/` only. `pyproject.toml`, `README.md`,
`openapi-config.yml` and the script itself are hand-maintained: the generator
emits a Poetry `pyproject.toml` pinned to `python = "^3.11"`, and this repo is
3.12 + setuptools.

## Usage

```python
from rudder_sdk import AuthenticatedClient
from rudder_sdk.api.auth import create_token_auth_token_post
from rudder_sdk.api.projects import create_project, list_projects
from rudder_sdk.models import LoginRequest, ProjectCreate

with AuthenticatedClient(base_url="http://localhost:8000", token="") as anon:
    token = create_token_auth_token_post.sync(
        client=anon, body=LoginRequest(email="you@example.com", password="...")
    )

with AuthenticatedClient(base_url="http://localhost:8000", token=token.access_token) as client:
    project = create_project.sync(client=client, body=ProjectCreate(name="shop"))
    for p in list_projects.sync(client=client):
        print(p.id, p.name)
```

Every operation module exposes four callables:

| | returns |
|---|---|
| `sync(...)` | the parsed model, or `None` |
| `sync_detailed(...)` | `Response[...]` with `status_code`, `content`, `parsed` |
| `asyncio(...)` | parsed, awaited |
| `asyncio_detailed(...)` | `Response[...]`, awaited |

Use `*_detailed` whenever the status code matters — `sync()` collapses an error
response to `None` for endpoints whose error bodies the generator could not
model (see "Known generator gaps").

## Known generator gaps

Both are limitations of the source schema, recorded here so the next person does
not rediscover them:

1. **`ErrorBody` name collision.** `rudder_cp.schemas.auth.ErrorBody` and
   `rudder_cp.schemas.variables.ErrorBody` are two different Pydantic classes
   with the same `title`, so FastAPI emits
   `rudder_cp__schemas__auth__ErrorBody` and
   `rudder_cp__schemas__variables__ErrorBody`. The generator refuses to build
   two models named `ErrorBody`, drops the second, and therefore omits the
   404/422 responses from the three `variables` operations. The HTTP status and
   raw body are still on `Response`, so `*_detailed` loses nothing that matters.
   Fixing it means giving those two schemas distinct class names in the control
   plane — most of the API already uses the single shared `ErrorEnvelope`.

2. **SSE is not streamed.** `GET /deployments/{id}/build-log` is declared
   `text/event-stream`, which the generator has no concept of: the generated
   `stream_build_log_...` buffers the entire response and parses it as `Any`.
   Streaming clients (the CLI's `deploy --follow` / `logs -f`) call
   `client.get_httpx_client().stream(...)` against the same authenticated
   client instead. That is the client's own transport, not a second HTTP stack.
