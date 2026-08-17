FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# buildctl only — buildkitd itself runs as its own compose service.
# Cloud Build's classic Docker builder does not inject TARGETARCH. GKE's
# standard worker image is AMD64; local BuildKit builds can still override it.
ARG TARGETARCH=amd64
ARG BUILDKIT_VERSION=0.16.0
# No --strip-components: the tarball already contains bin/buildctl, so stripping
# the leading component lands the binary in /usr/local/ instead of /usr/local/bin/,
# where it is not on PATH.
RUN curl -fsSL "https://github.com/moby/buildkit/releases/download/v${BUILDKIT_VERSION}/buildkit-v${BUILDKIT_VERSION}.linux-${TARGETARCH}.tar.gz" \
    | tar -xz -C /usr/local bin/buildctl \
    && buildctl --version

WORKDIR /app

# The development Compose file bind-mounts the source tree at /app. Keep the
# image virtualenv outside that mount so development commands (including
# Alembic) remain available after the mount replaces /app.
ENV UV_PROJECT_ENVIRONMENT=/opt/rudder-venv

# The control-plane image must use the exact dependency graph tested in CI.
# Installing the project directly with pip ignores uv.lock and silently picks
# newer packages at image-build time. Keep dependency resolution separate from
# source copying so ordinary source edits also reuse this cached layer.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir "uv==0.11.27" \
    && uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

ENV PATH="/opt/rudder-venv/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "rudder_cp.main:app", "--host", "0.0.0.0", "--port", "8000"]
