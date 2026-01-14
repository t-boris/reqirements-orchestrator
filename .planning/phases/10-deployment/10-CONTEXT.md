# Phase 10: Deployment - Context

**Gathered:** 2026-01-14
**Status:** Ready for planning

<vision>
## How This Should Work

Deploy to a single GCE VM (e2-small, already exists) running Docker Compose with the full stack. The bot connects to my personal Slack workspace, uses Gemini as the LLM provider, and stores data in PostgreSQL.

**Deployment flow:** Run a local deploy script that:
1. Uses `gcloud builds submit` to build the image
2. Pushes to Artifact Registry (GCP)
3. SSHs into the VM to pull + restart containers

One command that handles everything: `./deploy.sh` from my local machine.

**Services:** Full stack from main branch - Postgres, Redis, Backend, Frontend, Workers. All running in Docker Compose with `restart: always` so they recover automatically.

**Observability:** LangSmith tracing enabled for production debugging. Container logs stay local.

**Admin:** Dashboard exposed at `:8000/admin`, no auth (firewall restricts access).

</vision>

<essential>
## What Must Be Nailed

- **Dead simple deploy script** — One command from local machine that builds, pushes, and restarts everything
- **Reliable uptime** — Bot stays connected to Slack 24/7, auto-restarts on crash (`restart: always`)
- **Easy debugging** — LangSmith tracing + accessible container logs when something breaks
- **Auto migrations** — Alembic runs on container startup, no manual steps

</essential>

<specifics>
## Specific Ideas

### Existing Assets (from main branch)
- `Dockerfile` — Multi-stage build, Python 3.11, non-root user
- `docker-compose.yml` — Postgres, Redis, Backend, Frontend, Workers
- `deploy/setup-vm.sh` — VM setup script
- `.env` — All credentials already configured

### Deploy Flow
```bash
# Local machine
./deploy.sh

# Script does:
# 1. gcloud builds submit --tag gcr.io/PROJECT/maro
# 2. gcloud compute ssh VM -- 'docker-compose pull && docker-compose up -d'
```

### Configuration
- **VM:** e2-small (~$15/month), already exists
- **LLM:** Gemini (change DEFAULT_LLM_MODEL in .env)
- **Secrets:** Simple .env file on VM (acceptable for personal use)
- **Data:** Local Docker volumes (acceptable risk)
- **Environment:** Production only (no staging)

### Health & Recovery
- `/health` endpoint for Docker healthcheck
- `restart: always` on all containers
- Migrations run automatically on startup

</specifics>

<notes>
## Additional Context

### What Exists
- Full deployment infrastructure on main branch
- All API keys configured in .env (Slack, Jira, Gemini, OpenAI, Anthropic, LangSmith, Zep)
- GCE VM already provisioned

### Trade-offs Accepted
- Local volumes (no backup strategy) — acceptable for personal use
- No auto-deploy from GitHub — manual is fine for now
- Simple .env secrets — no need for Secret Manager
- No SSL/custom domain — IP access is fine

### Cost Optimization
- Keep it small: e2-small at ~$15/month is acceptable
- No preemptible VMs (need 24/7 uptime for Slack bot)

</notes>

---

*Phase: 10-deployment*
*Context gathered: 2026-01-14*
