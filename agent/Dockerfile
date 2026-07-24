FROM docker:27-cli AS docker-cli

FROM python:3.12-slim

# The SDK remains useful for the existing single-container API, while the
# Compose plugin is the allowlisted subprocess used for imported releases.
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 9000

CMD ["python", "-m", "rudder_agent.main"]
