#!/usr/bin/env bash
# ==============================================================================
# PayEase Voice Agent — Automated AWS VM (EC2 / Lightsail) Bootstrap Script
#
# Supports: Ubuntu 22.04 LTS, Ubuntu 24.04 LTS, Debian 12
# Usage:
#   curl -sSL <raw-url>/setup_aws_vm.sh | bash
#   OR
#   bash scripts/setup_aws_vm.sh
# ==============================================================================

set -eo pipefail

echo "================================================================"
echo "    Preparing AWS VM for PayEase Autopay Recovery Voice Agent   "
echo "================================================================"

# 1. Update system packages
echo "▶ Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    ufw

# 2. Install official Docker Engine & Docker Compose Plugin
if ! command -v docker &> /dev/null; then
    echo "▶ Installing official Docker Engine..."
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# 3. Add current user to docker group
echo "▶ Configuring Docker group permissions..."
sudo usermod -aG docker "$USER" || true
sudo systemctl enable docker
sudo systemctl start docker

# 4. Optional UFW firewall configuration
if sudo ufw status | grep -q "Status: active"; then
    echo "▶ Opening ports 80, 443, 8000, 22 in UFW..."
    sudo ufw allow 22/tcp || true
    sudo ufw allow 80/tcp || true
    sudo ufw allow 443/tcp || true
    sudo ufw allow 8000/tcp || true
fi

echo ""
echo "================================================================"
echo " [✓] AWS VM Environment Prepared Successfully!                  "
echo "================================================================"
echo ""
echo "Next Steps to Deploy:"
echo "  1. If this is your first time adding user to docker group, log out and back in:"
echo "     exit"
echo "  2. Clone the repository and configure your .env file:"
echo "     cp .env.example .env"
echo "     nano .env"
echo "  3. Deploy the application with the AWS flag:"
echo "     ./run.sh --aws"
echo ""
echo "Note for AWS EC2 Security Groups:"
echo "  Ensure your EC2 Security Group has inbound rules for:"
echo "  - Port 80 (HTTP) -> 0.0.0.0/0"
echo "  - Port 443 (HTTPS) -> 0.0.0.0/0 (if using SSL)"
echo "  - Port 8000 (Custom TCP) -> 0.0.0.0/0 (optional, Nginx proxies port 80 to 8000)"
echo ""
