"""Node agent.

D3(b): this is the real component, built in Phase 1 and running on localhost.
Phase 2 changes where it runs, not what it is. The control plane owns desired
state; this process owns actual state on one host and never makes placement
decisions.

Container operations land here in Phase 1 step 6:
    POST   /containers          create + start from a deployment spec
    DELETE /containers/{id}     drain then stop
    GET    /containers/{id}     inspect actual state
"""

import os

from aiohttp import web


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_app() -> web.Application:
    app = web.Application()
    app.add_routes([web.get("/healthz", healthz)])
    return app


if __name__ == "__main__":
    web.run_app(
        create_app(),
        host=os.getenv("RUDDER_AGENT_BIND", "0.0.0.0"),
        port=int(os.getenv("RUDDER_AGENT_PORT", "9000")),
    )
