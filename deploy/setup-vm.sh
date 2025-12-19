#!/bin/bash
# =============================================================================
# MARO - VM Setup Script
# Run this script after SSHing into the VM
# =============================================================================

set -e

echo "=========================================="
echo "MARO VM Setup"
echo "=========================================="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker installed. Please log out and log back in, then run this script again."
    exit 0
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

echo ""
echo "Docker version: $(docker --version)"
echo "Docker Compose version: $(docker-compose --version)"
echo ""

# Create app directory
APP_DIR="/opt/maro"
if [ ! -d "$APP_DIR" ]; then
    echo "Creating app directory..."
    sudo mkdir -p "$APP_DIR"
    sudo chown -R $USER:$USER "$APP_DIR"
fi

cd "$APP_DIR"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo ""
    echo "=========================================="
    echo "IMPORTANT: .env file not found!"
    echo "=========================================="
    echo ""
    echo "Please create .env file with your secrets:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
    echo "Required secrets:"
    echo "  - OPENAI_API_KEY"
    echo "  - SLACK_BOT_TOKEN"
    echo "  - SLACK_SIGNING_SECRET"
    echo "  - SLACK_APP_TOKEN"
    echo "  - JIRA_URL"
    echo "  - JIRA_USER"
    echo "  - JIRA_API_TOKEN"
    echo "  - POSTGRES_PASSWORD (for production)"
    echo ""
    exit 1
fi

echo "Starting MARO..."
echo ""

# Pull and build images
docker-compose -f docker-compose.prod.yml build

# Run migrations first
echo "Running database migrations..."
docker-compose -f docker-compose.prod.yml run --rm migrations

# Start services
echo "Starting services..."
docker-compose -f docker-compose.prod.yml up -d

echo ""
echo "=========================================="
echo "MARO is now running!"
echo "=========================================="
echo ""
echo "Services:"
echo "  - Frontend: http://$(curl -s ifconfig.me)"
echo "  - Backend API: http://$(curl -s ifconfig.me):8000"
echo ""
echo "Useful commands:"
echo "  - View logs: docker-compose -f docker-compose.prod.yml logs -f"
echo "  - Stop: docker-compose -f docker-compose.prod.yml down"
echo "  - Restart: docker-compose -f docker-compose.prod.yml restart"
echo ""
