#!/usr/bin/env bash
# ==============================================================================
# PayEase Autopay Recovery Voice Agent — Unified Runner & Deployment CLI
#
# Usage:
#   ./run.sh --local          # Run locally in Docker (Frontend :5173, Backend :8000)
#   ./run.sh --aws            # Deploy on AWS VM (Frontend :80, Backend :8000, Auto-IP)
#   ./run.sh --status         # Check health of running containers
#   ./run.sh --logs [service] # Tail container logs (e.g. ./run.sh --logs backend)
#   ./run.sh --stop           # Stop all running containers
#   ./run.sh --test           # Run unit and integration tests
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for terminal output
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

function print_banner() {
    echo -e "${BOLD}${BLUE}"
    echo "================================================================"
    echo "       PayEase — Autopay Recovery Voice Agent Runner            "
    echo "================================================================"
    echo -e "${NC}"
}

function check_env_file() {
    if [ ! -f .env ]; then
        if [ -f .env.example ]; then
            echo -e "${YELLOW}[!] .env not found. Creating from .env.example...${NC}"
            cp .env.example .env
            echo -e "${GREEN}[✓] Created .env. Please review your API keys if needed.${NC}"
        else
            echo -e "${RED}[✗] Error: Neither .env nor .env.example found!${NC}"
            exit 1
        fi
    fi
}

function detect_aws_ip() {
    local detected_ip=""
    # 1. Try AWS EC2 metadata token (IMDSv2)
    local token
    token=$(curl -s --connect-timeout 2 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)
    if [ -n "$token" ]; then
        detected_ip=$(curl -s --connect-timeout 2 -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true)
    fi

    # 2. Fallback to IMDSv1
    if [ -z "$detected_ip" ]; then
        detected_ip=$(curl -s --connect-timeout 2 "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true)
    fi

    # 3. Fallback to public checkip
    if [ -z "$detected_ip" ]; then
        detected_ip=$(curl -s --connect-timeout 2 "https://checkip.amazonaws.com" 2>/dev/null | tr -d '\n\r' || true)
    fi

    echo "$detected_ip"
}

function log_cmd() {
    echo -e "${BOLD}${BLUE}▶ Executing command:${NC} ${GREEN}$*${NC}"
    "$@"
}

function ensure_docker_buildx() {
    local need_install=0
    if ! docker buildx version &>/dev/null; then
        need_install=1
    else
        local v_str
        v_str=$(docker buildx version 2>/dev/null | awk '{print $2}' | sed 's/^v//' | cut -d'-' -f1)
        local major minor
        major=$(echo "$v_str" | cut -d. -f1)
        minor=$(echo "$v_str" | cut -d. -f2)
        if [ "$major" -eq 0 ] && [ "$minor" -lt 17 ] 2>/dev/null; then
            need_install=1
        fi
    fi

    if [ "$need_install" -eq 1 ]; then
        echo -e "${YELLOW}[!] Docker Buildx >= 0.17 is required for Compose build. Installing...${NC}"
        local arch
        arch="$(uname -m)"
        case "$arch" in
            x86_64)  arch="amd64" ;;
            aarch64) arch="arm64" ;;
            arm64)   arch="arm64" ;;
            *)       arch="amd64" ;;
        esac

        mkdir -p "${HOME}/.docker/cli-plugins"
        local dl_url="https://github.com/docker/buildx/releases/download/v0.21.1/buildx-v0.21.1.linux-${arch}"
        echo -e "${BLUE}  Downloading buildx from ${dl_url}...${NC}"
        if curl -sSLf "$dl_url" -o "${HOME}/.docker/cli-plugins/docker-buildx"; then
            chmod +x "${HOME}/.docker/cli-plugins/docker-buildx"
            echo -e "${GREEN}[✓] Docker Buildx $(docker buildx version | awk '{print $2}') installed successfully.${NC}"
        else
            echo -e "${RED}[✗] Failed to download buildx binary automatically.${NC}"
        fi
    fi
}

function run_local() {
    print_banner
    check_env_file
    ensure_docker_buildx

    echo -e "${BOLD}${GREEN}▶ Launching Local Docker Environment...${NC}"
    echo -e "  - Frontend Dashboard: ${BOLD}http://localhost:5173${NC}"
    echo -e "  - FastAPI Backend:    ${BOLD}http://localhost:8000${NC}"
    echo -e "  - WebSocket Stream:   ${BOLD}ws://localhost:5173/ws${NC}"
    echo -e "  - Container Restart:  unless-stopped"
    echo ""

    export FRONTEND_PORT="${FRONTEND_PORT:-5173}"
    export BACKEND_PORT="${BACKEND_PORT:-8000}"
    export DOZZLE_PORT="${DOZZLE_PORT:-8888}"
    export DOCKER_RESTART="unless-stopped"

    log_cmd docker compose -f docker-compose.yml up -d --build

    echo ""
    echo -e "${GREEN}[✓] All services running locally!${NC}"
    echo -e "    Open dashboard:     ${BOLD}http://localhost:5173${NC}"
    echo -e "    Dozzle Live Logs:   ${BOLD}http://localhost:8888${NC}"
}

function run_aws() {
    print_banner
    check_env_file
    ensure_docker_buildx

    echo -e "${BOLD}${YELLOW}▶ Launching AWS VM Production Environment...${NC}"

    # Auto-detect or retrieve AWS public IP if not set in environment
    local aws_ip
    aws_ip=$(detect_aws_ip)

    if [ -n "$aws_ip" ]; then
        echo -e "  - Detected AWS Public IP: ${BOLD}${aws_ip}${NC}"
        if ! grep -q "^PUBLIC_BASE_URL=" .env || grep -q "^PUBLIC_BASE_URL=http://localhost" .env; then
            export PUBLIC_BASE_URL="http://${aws_ip}"
            echo -e "  - Auto-configured PUBLIC_BASE_URL: ${BOLD}http://${aws_ip}${NC}"
        fi
    else
        echo -e "  - Note: Could not auto-detect AWS Public IP. Using PUBLIC_BASE_URL from .env"
    fi

    export FRONTEND_PORT="${FRONTEND_PORT:-80}"
    export BACKEND_PORT="${BACKEND_PORT:-8000}"
    export DOZZLE_PORT="${DOZZLE_PORT:-8888}"
    export DOCKER_RESTART="always"

    echo -e "  - Frontend Web Port:  ${BOLD}:${FRONTEND_PORT}${NC} (Standard HTTP for VM)"
    echo -e "  - FastAPI Backend:    ${BOLD}:${BACKEND_PORT}${NC}"
    echo -e "  - Dozzle Log Viewer:  ${BOLD}:${DOZZLE_PORT}${NC}"
    echo -e "  - Container Restart:  always (Auto-recovery on VM reboot)"
    echo ""

    log_cmd docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build

    echo ""
    echo -e "${GREEN}[✓] Successfully deployed on AWS VM!${NC}"
    if [ -n "$aws_ip" ]; then
        echo -e "    Access Web Dashboard: ${BOLD}http://${aws_ip}${NC}"
        echo -e "    Dozzle Live Logs:     ${BOLD}http://${aws_ip}:8888${NC}"
        echo -e "    API Health Check:     ${BOLD}http://${aws_ip}/api/health${NC}"
    else
        echo -e "    Access Web Dashboard: ${BOLD}http://<YOUR-AWS-VM-IP>${NC}"
        echo -e "    Dozzle Live Logs:     ${BOLD}http://<YOUR-AWS-VM-IP>:8888${NC}"
    fi
}

function stop_all() {
    print_banner
    echo -e "${YELLOW}Stopping all containers...${NC}"
    log_cmd docker compose -f docker-compose.yml -f docker-compose.aws.yml down
    echo -e "${GREEN}[✓] All containers stopped.${NC}"
}

function show_status() {
    print_banner
    log_cmd docker compose ps
    echo ""
    echo -e "${BOLD}Health Check Probe:${NC}"
    curl -s http://localhost:8000/api/health || curl -s http://localhost:5173/api/health || echo "Could not reach health endpoint."
    echo ""
}

function show_logs() {
    local service="${1:-}"
    if [ -n "$service" ]; then
        log_cmd docker compose logs -f "$service"
    else
        log_cmd docker compose logs -f
    fi
}

function run_tests() {
    print_banner
    echo -e "${BOLD}${BLUE}Running unit and integration tests...${NC}"
    log_cmd uv run pytest tests/
}

# ── Argument Parsing ─────────────────────────────────────────────────────────
case "${1:-}" in
    --local|local)
        run_local
        ;;
    --aws|aws|--prod|prod)
        run_aws
        ;;
    --stop|stop|down)
        stop_all
        ;;
    --status|status|ps)
        show_status
        ;;
    --logs|logs)
        show_logs "${2:-}"
        ;;
    --test|test)
        run_tests
        ;;
    *)
        print_banner
        echo -e "Usage:"
        echo -e "  ${BOLD}./run.sh --local${NC}          Start full stack for local testing (Ports 5173, 8000)"
        echo -e "  ${BOLD}./run.sh --aws${NC}            Deploy full stack on AWS VM (Ports 80, 8000, Auto-IP)"
        echo -e "  ${BOLD}./run.sh --status${NC}         Show container statuses and health"
        echo -e "  ${BOLD}./run.sh --logs [svc]${NC}     Tail logs across all containers (or backend/agent/frontend)"
        echo -e "  ${BOLD}./run.sh --stop${NC}           Stop all running containers"
        echo -e "  ${BOLD}./run.sh --test${NC}           Run pytest verification suite"
        echo ""
        exit 1
        ;;
esac
