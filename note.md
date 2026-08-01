  They act as import presets:

  1. User still connects a GitHub repository and branch.
  2. Rudder checks that branch for compose.yml / compose.yaml.
  3. If it finds one, it uses the repository’s Compose architecture. The selected template does not overwrite it.
  4. If no Compose file exists, the template preselects Rudder-managed services—for example:
      - Node + PostgreSQL + Redis → adds private Postgres and Redis
      - Web + worker + Redis → adds Redis; web/worker commands are inferred from package.json or Procfile
      - Node + observability → adds Prometheus and Grafana

  5. Rudder generates the temporary Compose release plan, builds the app from that repo, and deploys it.

  So today, templates help Rudder decide the generated infrastructure; they do not create a repo, commit a compose.yml, or give the
  user editable template source files. Those would be a useful next enhancement.
