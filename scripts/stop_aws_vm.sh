#!/usr/bin/env bash
# ==============================================================================
# PayEase Autopay Recovery Voice Agent — Stop AWS VM Services
# Usage:
#   bash scripts/stop_aws_vm.sh
#   ./run.sh --stop
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
NC="\033[0m"

echo -e "${BOLD}${BLUE}"
echo "================================================================"
echo "    Stopping PayEase AWS VM Production Environment              "
echo "================================================================"
echo -e "${NC}"

echo -e "${YELLOW}▶ Stopping and removing containers...${NC}"
docker compose -f docker-compose.yml -f docker-compose.aws.yml down --remove-orphans

echo ""
echo -e "${GREEN}[✓] PayEase AWS services have been stopped successfully.${NC}"
