#!/usr/bin/env bash
# ==============================================================================
# PayEase Voice Agent — Automated AWS VM (EC2 / Lightsail) Bootstrap Script
#
# Supports: Amazon Linux 2023, Amazon Linux 2, Ubuntu 20.04/22.04/24.04, Debian, RHEL
# Usage:
#   bash scripts/setup_aws_vm.sh
# ==============================================================================

set -eo pipefail

echo "================================================================"
echo "    Preparing AWS VM for PayEase Autopay Recovery Voice Agent   "
echo "================================================================"

CURRENT_USER="${SUDO_USER:-$USER}"

# 1. Detect Package Manager & Install Docker
if command -v dnf &> /dev/null; then
    echo "▶ Detected Amazon Linux 2023 / Fedora / RHEL (dnf)..."
    sudo dnf update -y
    sudo dnf install -y docker git curl ca-certificates
    sudo systemctl enable --now docker

elif command -v yum &> /dev/null; then
    echo "▶ Detected Amazon Linux 2 / CentOS / RHEL (yum)..."
    sudo yum update -y
    if command -v amazon-linux-extras &> /dev/null; then
        sudo amazon-linux-extras install -y docker || true
    fi
    sudo yum install -y docker git curl ca-certificates
    sudo systemctl enable --now docker

elif command -v apt-get &> /dev/null; then
    echo "▶ Detected Ubuntu / Debian (apt-get)..."
    sudo apt-get update -y
    sudo apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        git \
        ufw

    if ! command -v docker &> /dev/null; then
        echo "▶ Installing official Docker Engine..."
        sudo install -m 0755 -d /etc/apt/keyrings
        sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc 2>/dev/null || \
            sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc

        DISTRO_ID=$(. /etc/os-release && echo "$ID")
        CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${DISTRO_ID} \
          ${CODENAME} stable" | \
          sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

        sudo apt-get update -y
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
    sudo systemctl enable --now docker

    if command -v ufw &> /dev/null && sudo ufw status | grep -q "Status: active"; then
        echo "▶ Opening ports 80, 443, 8000, 8888, 22 in UFW..."
        sudo ufw allow 22/tcp || true
        sudo ufw allow 80/tcp || true
        sudo ufw allow 443/tcp || true
        sudo ufw allow 8000/tcp || true
        sudo ufw allow 8888/tcp || true
    fi
else
    echo "❌ Error: Unsupported package manager. Please install Docker manually."
    exit 1
fi

# 2. Ensure Docker Compose (CLI plugin) is installed
if ! docker compose version &> /dev/null; then
    echo "▶ Installing Docker Compose CLI plugin..."
    ARCH="$(uname -m)"
    case "$ARCH" in
        x86_64)  COMPOSE_ARCH="x86_64" ;;
        aarch64) COMPOSE_ARCH="aarch64" ;;
        arm64)   COMPOSE_ARCH="aarch64" ;;
        *)       COMPOSE_ARCH="x86_64" ;;
    esac
    sudo mkdir -p /usr/local/lib/docker/cli-plugins /usr/lib/docker/cli-plugins
    COMPOSE_URL="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${COMPOSE_ARCH}"
    sudo curl -SL "$COMPOSE_URL" -o /usr/local/lib/docker/cli-plugins/docker-compose
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    # Also link to /usr/lib for compatibility
    sudo ln -sf /usr/local/lib/docker/cli-plugins/docker-compose /usr/lib/docker/cli-plugins/docker-compose 2>/dev/null || true
fi

# 3. Add user to docker group & start service
echo "▶ Configuring Docker group permissions for user '${CURRENT_USER}'..."
sudo usermod -aG docker "$CURRENT_USER" || true
sudo systemctl enable docker || true
sudo systemctl start docker || true

echo ""
echo "================================================================"
echo " [✓] AWS VM Environment Prepared Successfully!                  "
echo "================================================================"
echo ""
echo "Docker Version: $(docker --version 2>/dev/null || echo 'Installed')"
echo "Docker Compose: $(docker compose version 2>/dev/null || echo 'Installed')"
echo ""
echo "▶ NOTE: To apply docker group permissions, either run:"
echo "    newgrp docker"
echo "  OR log out and back in:"
echo "    exit"
echo ""
echo "▶ Then launch the deployment:"
echo "    ./run.sh --aws"
echo ""
