#!/usr/bin/env bash
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()    { printf "${YELLOW}[INFO]${NC}  %s\n" "$1"; }
success() { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
warn()    { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }

# ── Change to project directory ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Detect docker compose ───────────────────────────────────────────────────
if docker compose version &>/dev/null; then
    COMPOSE="docker compose"
elif docker-compose version &>/dev/null; then
    COMPOSE="docker-compose"
else
    printf "${RED}[ERROR]${NC} Docker Compose not found.\n"
    exit 1
fi

# ── Parse flags ──────────────────────────────────────────────────────────────
CLEAN=false
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=true ;;
        -h|--help)
            echo "Usage: ./stop.sh [--clean]"
            echo ""
            echo "  --clean   Remove volumes (PostgreSQL data, Redis data) after stopping."
            echo "            Prompts for confirmation before deleting."
            exit 0
            ;;
        *)
            printf "${RED}[ERROR]${NC} Unknown option: %s\n" "$arg"
            echo "Usage: ./stop.sh [--clean]"
            exit 1
            ;;
    esac
done

# ── Stop containers ─────────────────────────────────────────────────────────
info "Stopping Merchant Onboarding stack..."
$COMPOSE down
success "All containers stopped and removed"

# ── Clean volumes if requested ───────────────────────────────────────────────
if [ "$CLEAN" = true ]; then
    echo ""
    warn "This will delete all persistent data (PostgreSQL, Redis)."
    printf "  Are you sure? [y/N] "
    read -r confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        info "Removing volumes..."
        $COMPOSE down -v 2>/dev/null || true
        success "Volumes removed"
    else
        info "Skipped volume removal"
    fi
fi

echo ""
success "Merchant Onboarding stack is stopped."
