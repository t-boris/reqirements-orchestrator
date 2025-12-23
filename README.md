# MARO v2 - Multi-Agent Requirements Orchestrator

A Slack bot for requirements engineering with Jira integration, powered by LangGraph.

## Features

- **LangGraph Workflow**: State machine with reflexion pattern (draft → critique → refine)
- **Zep Memory**: Long-term memory with semantic search and knowledge graph
- **Jira Integration**: Create, update, and search issues via MCP
- **Human-in-the-Loop**: Approval workflow with "Approve Always" support
- **Personas**: Specialized agents (Architect, Product Manager, Security Analyst)

## Quick Start

```bash
# Copy environment file
cp .env.example .env

# Edit with your API keys
nano .env

# Start services
docker-compose up -d
```

## Slack Commands

- `/req-status` - Show current state
- `/req-config` - Configure channel settings
- `/req-clean` - Clear memory and state
- `/req-approve list` - List permanent approvals
- `/req-approve delete <id>` - Remove an approval
