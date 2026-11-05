#!/usr/bin/env bash
# Start the Pi'op stack with Docker Compose or Podman Compose.
set -euo pipefail

# Run from the directory this script lives in.
cd "$(dirname "${BASH_SOURCE[0]}")"

# Pick the compose command: $COMPOSE override, then docker, then podman.
if [ -n "${COMPOSE:-}" ]; then
  read -r -a compose <<< "$COMPOSE"
elif command -v docker >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v podman >/dev/null 2>&1; then
  compose=(podman compose)
else
  echo "error: neither docker nor podman was found on PATH" >&2
  exit 1
fi

# Create .env from the template on first run.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

# Read a KEY=value entry from .env without sourcing it.
env_value() {
  local value
  value=$(sed -n "s/^$1=//p" .env | tail -1 | tr -d '"'"'"'\r')
  echo "${value:-$2}"
}
FRONTEND_PORT=$(env_value FRONTEND_PORT 3000)
BACKEND_PORT=$(env_value BACKEND_PORT 8080)
# Values may be host:port (e.g. 127.0.0.1:3000); keep the port.
FRONTEND_HOST=""
if [[ "$FRONTEND_PORT" == *:* ]]; then
  FRONTEND_HOST=${FRONTEND_PORT%:*}
fi
FRONTEND_PORT=${FRONTEND_PORT##*:}
BACKEND_PORT=${BACKEND_PORT##*:}

"${compose[@]}" up -d --build "$@"

# Wait up to 60 seconds for the backend health endpoint.
healthy=0
for _ in $(seq 60); do
  if curl -fs -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health"; then
    healthy=1
    break
  fi
  sleep 1
done
if [ "$healthy" -eq 0 ]; then
  echo "warning: backend did not respond on /api/health within 60 seconds" >&2
  echo "         check the logs with: ${compose[*]} logs backend" >&2
fi

echo
echo "Pi'op is running:"
echo "  Site:        http://localhost:$FRONTEND_PORT"
# Show the first LAN address when one is available, unless the UI is bound to localhost.
if [ "$FRONTEND_HOST" != "127.0.0.1" ] && [ "$FRONTEND_HOST" != "localhost" ] \
  && ip=$(hostname -I 2>/dev/null | awk '{print $1}') && [ -n "$ip" ]; then
  echo "  On network:  http://$ip:$FRONTEND_PORT"
fi
echo "  Backend API: http://127.0.0.1:$BACKEND_PORT/api  (local only)"

# Show the generated admin password if the backend logged it.
pw_line=$("${compose[@]}" logs backend 2>/dev/null | grep "superadmin password" | tail -1 || true)
echo
if [ -n "$pw_line" ]; then
  echo "Admin login: $pw_line"
  echo "Save this password now and change it after your first login."
else
  echo "Admin password was printed on first start and is not in the current logs."
  echo "If you lost it on a fresh install, reset with: ${compose[*]} down -v && ./start.sh (deletes all data)."
fi
