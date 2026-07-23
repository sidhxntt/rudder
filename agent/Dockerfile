FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 9000

CMD ["python", "-m", "rudder_agent.main"]
