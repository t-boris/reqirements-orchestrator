#!/bin/bash
# =============================================================================
# MARO v2 - GCP VM Setup Script
# =============================================================================
# This script sets up a fresh GCP VM for running MARO v2.
# Run this script on the VM after creating it.
#
# Usage: ./setup-vm.sh
# =============================================================================

set -e

echo "=== MARO v2 VM Setup ==="

# =============================================================================
# System Updates
# =============================================================================
echo ">>> Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# =============================================================================
# Install Docker
# =============================================================================
echo ">>> Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker installed. You may need to log out and back in for group changes."
else
    echo "Docker already installed."
fi

# =============================================================================
# Install Docker Compose
# =============================================================================
echo ">>> Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
else
    echo "Docker Compose already installed."
fi

# =============================================================================
# Create Application Directory
# =============================================================================
echo ">>> Setting up application directory..."
APP_DIR="/opt/maro-v2"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# =============================================================================
# Clone Repository (if not exists)
# =============================================================================
if [ ! -d "$APP_DIR/.git" ]; then
    echo ">>> Cloning repository..."
    cd /opt
    git clone https://github.com/yourusername/maro-v2.git maro-v2 || true
fi

cd $APP_DIR

# =============================================================================
# Environment Setup
# =============================================================================
echo ">>> Setting up environment..."
if [ ! -f "$APP_DIR/.env.production" ]; then
    echo "WARNING: .env.production not found!"
    echo "Please create .env.production with your configuration."
    echo "You can use .env.example as a template."
fi

# =============================================================================
# Start Services
# =============================================================================
echo ">>> Starting services..."
docker-compose -f docker-compose.prod.yml up -d

# =============================================================================
# Verify Services
# =============================================================================
echo ">>> Verifying services..."
sleep 10
docker-compose -f docker-compose.prod.yml ps

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Create .env.production if not exists (copy from .env.example)"
echo "2. Update .env.production with your API keys and secrets"
echo "3. Run: docker-compose -f docker-compose.prod.yml up -d"
echo "4. Check logs: docker-compose -f docker-compose.prod.yml logs -f app"
echo ""
