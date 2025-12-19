# MARO - Multi-Agent Requirements Orchestrator

Event-driven requirements gathering from Slack discussions using a Knowledge Graph.

## Features

- **Slack Integration**: Listen to channel discussions and extract requirements
- **Knowledge Graph**: NetworkX-based graph for requirements relationships
- **AutoGen Agents**: PM, Architect, GraphAdmin for collaborative analysis
- **Jira Sync**: Export requirements to Jira issues
- **Web Dashboard**: React Flow visualization

## Quick Start

```bash
# Clone
git clone https://github.com/t-boris/reqirements-orchestrator.git
cd reqirements-orchestrator

# Configure
cp .env.example .env
# Edit .env with your secrets

# Run with Docker
docker-compose up -d
```

## Architecture

Hexagonal architecture with:
- **Core**: Graph models, Event Store, Services
- **Adapters**: Slack, Jira, LLM, Persistence
- **API**: FastAPI REST endpoints

## Slack Commands

- `/req-status` - Show graph summary
- `/req-nfr` - Add non-functional requirement
- `/req-clean` - Delete graph
- `/req-reset` - Clear and recreate knowledge base

## License

MIT
