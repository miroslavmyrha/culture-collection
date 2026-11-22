# shellcheck shell=bash
# Sourced by the e2e scripts of deploy/: a throwaway deployment folder outside the repository
# with settings, secrets, a self-signed certificate for localhost and a local restic repository,
# all under $work, which the caller removes. The caller sets COMPOSE_PROJECT_NAME, the ports
# (HTTPS_PORT, HTTP_PORT) and the web network (WEB_SUBNET, PROXY_ADDRESS) first.
fail() { echo "FAILED: $1" >&2; exit 1; }
compose() { docker compose -f compose.yaml "$@"; }

work=$(mktemp -d)
export ENV_FILE=$work/env SECRETS_DIR=$work/secrets TLS_DIR=$work/certs STATE_DIR=$work/state
export RESTIC_REPOSITORY=$work/restic
export DJANGO_ADMIN_PATH=e2e-admin-$RANDOM/

cat > "$ENV_FILE" <<ENV
DJANGO_ALLOWED_HOSTS=localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost:$HTTPS_PORT
DJANGO_ADMIN_PATH=$DJANGO_ADMIN_PATH
WEBAUTHN_ORIGINS=https://localhost:$HTTPS_PORT
WEBAUTHN_RP_ID=localhost
ENV
mkdir -p "$TLS_DIR" "$RESTIC_REPOSITORY"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost \
  -addext subjectAltName=DNS:localhost -keyout "$TLS_DIR/privkey.pem" -out "$TLS_DIR/fullchain.pem" \
  >/dev/null 2>&1 || fail "openssl could not make the test certificate"
# The proxy runs as uid 101: it must read the key.
chmod 644 "$TLS_DIR/privkey.pem"
./deploy.sh secrets >/dev/null
./backup.sh init >/dev/null || fail "the restic repository"

# The stack and $work go when the caller exits. The logs go with the stack: print them first.
e2e_cleanup() {
  local status=$1
  [ "$status" -eq 0 ] || compose logs --tail 60 backend proxy scheduler 2>&1 || true
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work"
}
