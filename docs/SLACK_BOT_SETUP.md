# MARO Slack Bot Setup Guide

Complete instructions for creating and configuring the MARO Slack bot.

---

## Prerequisites

- Slack workspace with admin permissions (or permission to install apps)
- GCP project with Cloud Build and Artifact Registry
- PostgreSQL database
- Jira Cloud instance with API access

---

## Step 1: Create Slack App

1. Go to https://api.slack.com/apps
2. Click **Create New App**
3. Choose **From an app manifest**
4. Select your workspace
5. Paste the manifest below (YAML format):

```yaml
display_information:
  name: MARO
  description: Managed Automated Requirements Orchestrator
  background_color: "#2c2d30"

features:
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: MARO
    always_online: true
  slash_commands:
    - command: /maro
      description: MARO bot controls and help
      usage_hint: "[help|enable|disable|status|track|sync|mode|debug|explain]"
      should_escape: false
    - command: /jira
      description: Create and search Jira tickets
      usage_hint: "[create|search|status]"
      should_escape: false
    - command: /help
      description: Show MARO help
      should_escape: false

oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - channels:join
      - channels:read
      - chat:write
      - chat:write.public
      - commands
      - files:write
      - groups:history
      - groups:read
      - im:history
      - im:read
      - im:write
      - mpim:history
      - mpim:read
      - pins:read
      - pins:write
      - reactions:read
      - reactions:write
      - users:read

settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - member_joined_channel
      - message.channels
      - message.groups
      - message.im
      - message.mpim
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
```

6. Click **Create**

---

## Step 2: Generate Tokens

### App-Level Token (for Socket Mode)

1. Go to **Settings** → **Basic Information**
2. Scroll to **App-Level Tokens**
3. Click **Generate Token and Scopes**
4. Name: `socket-mode`
5. Add scope: `connections:write`
6. Click **Generate**
7. Copy the token (starts with `xapp-`)

### Bot Token

1. Go to **Features** → **OAuth & Permissions**
2. Click **Install to Workspace**
3. Authorize the app
4. Copy **Bot User OAuth Token** (starts with `xoxb-`)

### Signing Secret

1. Go to **Settings** → **Basic Information**
2. Scroll to **App Credentials**
3. Copy **Signing Secret**

---

## Step 3: Environment Variables

Create a `.env` file (or set in your deployment):

```bash
# Slack
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-level-token
SLACK_SIGNING_SECRET=your-signing-secret

# Database
DATABASE_URL=postgresql://user:password@host:5432/maro

# Jira
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token
JIRA_PROJECT=PROJ

# LLM Provider (choose one)
GEMINI_API_KEY=your-gemini-key
# or
OPENAI_API_KEY=your-openai-key
# or
ANTHROPIC_API_KEY=your-anthropic-key

# Optional
LLM_PROVIDER=gemini  # gemini, openai, or anthropic
LOG_LEVEL=INFO
```

---

## Step 4: Database Setup

MARO uses PostgreSQL. Create the database:

```sql
CREATE DATABASE maro;
```

Tables are created automatically on first run.

---

## Step 5: Deploy to GCE

### Option A: Using Cloud Build (Recommended)

1. Push code to repository
2. Run Cloud Build:

```bash
gcloud builds submit --config=cloudbuild.yaml
```

3. SSH to GCE instance:

```bash
gcloud compute ssh maro-server --zone=us-central1-a
```

4. Create `/opt/maro/docker-compose.yml`:

```yaml
version: '3.8'

services:
  bot:
    image: us-central1-docker.pkg.dev/YOUR_PROJECT/maro/maro:latest
    container_name: maro-bot
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}
      - SLACK_APP_TOKEN=${SLACK_APP_TOKEN}
      - SLACK_SIGNING_SECRET=${SLACK_SIGNING_SECRET}
      - DATABASE_URL=postgresql://maro:${POSTGRES_PASSWORD}@postgres:5432/maro
      - JIRA_URL=${JIRA_URL}
      - JIRA_EMAIL=${JIRA_EMAIL}
      - JIRA_API_TOKEN=${JIRA_API_TOKEN}
      - JIRA_PROJECT=${JIRA_PROJECT}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - LLM_PROVIDER=gemini
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

  postgres:
    image: postgres:15-alpine
    container_name: maro-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_USER=maro
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=maro
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U maro"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

5. Create `/opt/maro/.env` with your variables

6. Start:

```bash
cd /opt/maro
docker compose pull
docker compose up -d
```

### Option B: Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python -m src
```

---

## Step 6: Verify Installation

1. Check bot is running:

```bash
docker compose ps
docker compose logs bot --tail=50
```

You should see:
```
⚡️ Bolt app is running!
Starting to receive messages from a new connection
```

2. In Slack:
   - Invite bot to a channel: `/invite @MARO`
   - Test: `/maro help`
   - Enable listening: `/maro enable`
   - Mention: `@MARO help me design an API`

---

## Slash Commands Reference

| Command | Description |
|---------|-------------|
| `/maro help` | Interactive help with examples |
| `/maro enable` | Enable bot in channel |
| `/maro disable` | Disable bot in channel |
| `/maro status` | Show channel status |
| `/maro track PROJ-123` | Track Jira issue |
| `/maro untrack PROJ-123` | Stop tracking issue |
| `/maro tracked` | List tracked issues |
| `/maro board` | Show/update pinned board |
| `/maro sync` | Show pending Jira changes |
| `/maro sync --auto` | Auto-apply obvious changes |
| `/maro mode` | Show/set channel mode |
| `/maro debug` | Debug mode controls |
| `/maro explain` | Explain last decision |
| `/jira create` | Start new ticket |
| `/jira search <query>` | Search Jira |
| `/jira status` | Session status |
| `/help` | Quick help |

---

## Troubleshooting

### Bot not responding

1. Check Socket Mode is enabled in Slack App settings
2. Verify `SLACK_APP_TOKEN` starts with `xapp-`
3. Check logs: `docker compose logs bot`

### "not_authed" error

- `SLACK_BOT_TOKEN` is invalid or expired
- Reinstall app to workspace to get new token

### Commands not working

- Verify slash commands are in the manifest
- Reinstall app after manifest changes
- Check bot has `commands` scope

### Database connection failed

- Verify `DATABASE_URL` format
- Check PostgreSQL is running: `docker compose ps`
- Check network connectivity between containers

### Jira errors

- Verify `JIRA_API_TOKEN` is valid
- Check `JIRA_EMAIL` matches the token owner
- Ensure user has project access

---

## Updating the Bot

```bash
# On your machine
git push origin HEAD:refs/heads/v1.1
gcloud builds submit --config=cloudbuild.yaml

# On GCE
gcloud compute ssh maro-server --zone=us-central1-a
cd /opt/maro
docker compose pull
docker compose up -d
```

---

## Security Notes

- Never commit `.env` files
- Rotate tokens periodically
- Use secrets manager in production
- Restrict bot to specific channels if needed
- Review OAuth scopes - remove unused ones
