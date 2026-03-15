#!/usr/bin/env bash
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()    { printf "${CYAN}[INFO]${NC}  %s\n" "$1"; }
success() { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
warn()    { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
error()   { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

# ── Change to project directory ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check prerequisites ─────────────────────────────────────────────────────
info "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    error "Docker is not installed. Please install Docker first."
    exit 1
fi
success "Docker found"

if docker compose version &>/dev/null; then
    COMPOSE="docker compose"
elif docker-compose version &>/dev/null; then
    COMPOSE="docker-compose"
else
    error "Docker Compose (v2) is not available. Please install Docker Compose."
    exit 1
fi
success "Docker Compose found ($($COMPOSE version --short 2>/dev/null || $COMPOSE version))"

# ── Check for port conflicts ────────────────────────────────────────────────
info "Checking for port conflicts..."
PORTS_IN_USE=()
for port in 8000 3001 5432 6379 5555; do
    # Use lsof on macOS/Linux; fall back to ss
    if command -v lsof &>/dev/null; then
        if lsof -iTCP:"$port" -sTCP:LISTEN -P -n &>/dev/null; then
            PORTS_IN_USE+=("$port")
        fi
    elif command -v ss &>/dev/null; then
        if ss -tlnp "sport = :$port" 2>/dev/null | grep -q LISTEN; then
            PORTS_IN_USE+=("$port")
        fi
    fi
done

if [ ${#PORTS_IN_USE[@]} -gt 0 ]; then
    # Check if the ports are used by our own containers
    RUNNING_CONTAINERS=$($COMPOSE ps --status running -q 2>/dev/null | wc -l | tr -d ' ')
    if [ "$RUNNING_CONTAINERS" -gt 0 ]; then
        warn "Ports ${PORTS_IN_USE[*]} are in use (likely by existing merchant_onboarding containers)."
        warn "Continuing — docker compose up is idempotent."
    else
        error "Ports ${PORTS_IN_USE[*]} are already in use by other processes."
        error "Please free these ports before starting the stack."
        exit 1
    fi
else
    success "All required ports are available"
fi

# ── Generate .env if missing ────────────────────────────────────────────────
if [ ! -f .env ]; then
    info "No .env file found. Generating from .env.example..."

    if [ ! -f .env.example ]; then
        error ".env.example not found. Cannot generate .env."
        exit 1
    fi

    cp .env.example .env

    # Generate OAUTH_ENCRYPTION_KEY
    OAUTH_KEY=""
    if python3 -c "from cryptography.fernet import Fernet" &>/dev/null; then
        OAUTH_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    elif command -v openssl &>/dev/null; then
        OAUTH_KEY=$(openssl rand -base64 32)
    else
        warn "Could not generate OAUTH_ENCRYPTION_KEY — set it manually in .env"
    fi

    # Generate JWT_SECRET_KEY
    JWT_KEY=""
    if command -v openssl &>/dev/null; then
        JWT_KEY=$(openssl rand -hex 32)
    elif command -v python3 &>/dev/null; then
        JWT_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    else
        warn "Could not generate JWT_SECRET_KEY — set it manually in .env"
    fi

    # Platform-portable sed -i
    _sed_i() {
        if [[ "$OSTYPE" == darwin* ]]; then
            sed -i '' "$@"
        else
            sed -i "$@"
        fi
    }

    # Apply docker-internal connection strings
    _sed_i 's|^DATABASE_URL=.*|DATABASE_URL=postgresql://postgres:postgres@postgres:5432/postgres|' .env
    _sed_i 's|^REDIS_URL=.*|REDIS_URL=redis://redis:6379/0|' .env
    _sed_i 's|^CELERY_BROKER_URL=.*|CELERY_BROKER_URL=redis://redis:6379/1|' .env
    _sed_i 's|^CELERY_RESULT_BACKEND=.*|CELERY_RESULT_BACKEND=redis://redis:6379/2|' .env
    _sed_i 's|^API_KEYS=.*|API_KEYS=dev-key-1|' .env

    if [ -n "$OAUTH_KEY" ]; then
        _sed_i "s|^OAUTH_ENCRYPTION_KEY=.*|OAUTH_ENCRYPTION_KEY=${OAUTH_KEY}|" .env
    fi

    # Append JWT_SECRET_KEY if not already in .env
    if ! grep -q '^JWT_SECRET_KEY=' .env; then
        echo "" >> .env
        echo "JWT_SECRET_KEY=${JWT_KEY}" >> .env
    elif [ -n "$JWT_KEY" ]; then
        _sed_i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${JWT_KEY}|" .env
    fi

    success ".env generated with docker-internal defaults"
else
    success ".env already exists"
fi

# ── Build images ─────────────────────────────────────────────────────────────
info "Building Docker images..."
if ! $COMPOSE build; then
    error "Docker build failed. Check the output above."
    exit 1
fi
success "All images built"

# ── Start services ───────────────────────────────────────────────────────────
info "Starting services..."
if ! $COMPOSE up -d; then
    error "Failed to start services."
    $COMPOSE logs --tail=30
    exit 1
fi
success "All containers started"

# ── Wait for health checks ──────────────────────────────────────────────────
MAX_WAIT=120  # seconds
POLL_INTERVAL=3

wait_for() {
    local name="$1"
    local check_cmd="$2"
    local elapsed=0

    printf "  Waiting for %-20s" "$name..."
    while [ $elapsed -lt $MAX_WAIT ]; do
        if eval "$check_cmd" &>/dev/null; then
            printf " ${GREEN}ready${NC} (%ds)\n" "$elapsed"
            return 0
        fi
        sleep "$POLL_INTERVAL"
        elapsed=$((elapsed + POLL_INTERVAL))
    done
    printf " ${RED}timeout after %ds${NC}\n" "$MAX_WAIT"
    return 1
}

info "Waiting for services to become healthy..."
HEALTH_OK=true

wait_for "PostgreSQL" "$COMPOSE exec -T postgres pg_isready -U postgres" || HEALTH_OK=false
wait_for "Redis" "$COMPOSE exec -T redis redis-cli ping" || HEALTH_OK=false
wait_for "API Server" "curl -sf http://localhost:8000/health" || HEALTH_OK=false

wait_for "Admin Dashboard" "curl -sf http://localhost:3001/ -o /dev/null" || warn "Admin Dashboard not responding (may still be building)"

if [ "$HEALTH_OK" = false ]; then
    error "Some services failed to start. Showing recent logs:"
    echo ""
    $COMPOSE logs --tail=20
    exit 1
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
printf "${GREEN}${BOLD}"
echo "  =================================================="
echo "  Merchant Onboarding Stack is running!"
echo "  =================================================="
printf "${NC}\n"
printf "  ${BOLD}API Server:${NC}        http://localhost:8000\n"
printf "  ${BOLD}Admin Dashboard:${NC}   http://localhost:3001\n"
printf "  ${BOLD}Flower (Celery):${NC}   http://localhost:5555  (admin/admin)\n"
echo ""
printf "  ${BOLD}Merchant Portal:${NC}   (separate repo — see idealo-merchant-portal)\n"
echo ""
printf "  ${BOLD}Default API Key:${NC}   dev-key-1\n"
echo ""
printf "  ${BOLD}Quick test:${NC}\n"
echo "    curl http://localhost:8000/health"
echo "    curl -X POST http://localhost:8000/api/v1/auth/merchant/register \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"email\": \"test@example.com\", \"password\": \"SecureP@ss123\"}'"
echo ""
printf "  ${BOLD}Stop:${NC}\n"
echo "    ./stop.sh"
echo ""
