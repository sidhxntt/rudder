FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# buildctl only — buildkitd itself runs as its own compose service.
# TARGETARCH is set by BuildKit; default covers a plain `docker build`.
ARG TARGETARCH=arm64
ARG BUILDKIT_VERSION=0.16.0
RUN curl -fsSL "https://github.com/moby/buildkit/releases/download/v${BUILDKIT_VERSION}/buildkit-v${BUILDKIT_VERSION}.linux-${TARGETARCH}.tar.gz" \
    | tar -xz -C /usr/local --strip-components=1 bin/buildctl

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "rudder_cp.main:app", "--host", "0.0.0.0", "--port", "8000"]
