#!/bin/bash
# Step 2 of tomorrow's deploy: ships the current working tree to the Lightsail
# instance created by provision.py, generates fresh secrets, and brings the
# stack up. Safe to re-run - re-ships the latest code and re-runs `compose up
# --build`, reusing the same .env.production (secrets aren't regenerated on
# repeat runs, so existing DB data isn't invalidated).
#
# Usage: bash scripts/deploy/deploy.sh   (run from the repo root)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
STATE_FILE="$HERE/.deploy_state.json"
ENV_FILE="$HERE/.env.production.generated"
PY="$REPO_ROOT/venv/Scripts/python.exe"

if [ ! -f "$STATE_FILE" ]; then
  echo "No $STATE_FILE - run provision.py first." >&2
  exit 1
fi

# $PY is the native Windows python.exe in venv/Scripts - it can't resolve Git Bash's
# POSIX-style /c/... paths, so convert to a Windows path before handing it over.
STATE_FILE_WIN="$(cygpath -w "$STATE_FILE")"

PUBLIC_IP=$("$PY" -c "import json;print(json.load(open(r'$STATE_FILE_WIN'))['public_ip'])")
KEY_FILE_WIN=$("$PY" -c "import json;print(json.load(open(r'$STATE_FILE_WIN'))['key_file'])")
BUCKET_NAME=$("$PY" -c "import json;print(json.load(open(r'$STATE_FILE_WIN'))['bucket_name'])")

# Back to POSIX form for the MSYS ssh/scp binaries.
KEY_FILE="$(cygpath -u "$KEY_FILE_WIN")"
chmod 600 "$KEY_FILE" || true

SSH="ssh -o StrictHostKeyChecking=accept-new -i $KEY_FILE ubuntu@$PUBLIC_IP"
SCP="scp -o StrictHostKeyChecking=accept-new -i $KEY_FILE"

echo "--- Waiting for SSH on $PUBLIC_IP ---"
for i in $(seq 1 30); do
  if $SSH -o ConnectTimeout=5 'echo ok' >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

echo "--- Waiting for cloud-init bootstrap to finish ---"
for i in $(seq 1 30); do
  if $SSH 'test -f /opt/emios/bootstrap.done' >/dev/null 2>&1; then
    $SSH 'cat /opt/emios/bootstrap.done'
    break
  fi
  sleep 10
done

echo "--- Generating backend/.env.production (first run only - reused on repeat deploys) ---"
if [ ! -f "$ENV_FILE" ]; then
  JWT_SECRET=$("$PY" -c "import secrets;print(secrets.token_urlsafe(48))")
  PG_PASSWORD=$("$PY" -c "import secrets;print(secrets.token_urlsafe(24))")
  NEO4J_PASSWORD=$("$PY" -c "import secrets;print(secrets.token_urlsafe(24))")

  cat > "$ENV_FILE" <<EOF
PORT=8000

POSTGRES_USER=emios
POSTGRES_PASSWORD=$PG_PASSWORD
POSTGRES_DB=emios

NEO4J_PASSWORD=$NEO4J_PASSWORD

JWT_SECRET_KEY=$JWT_SECRET

OPENAI_API_KEY=
GEMINI_API_KEY=

AWS_REGION=${AWS_REGION:-us-east-1}
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
BEDROCK_LLM_MODEL_ID=nvidia.nemotron-nano-12b-v2
BEDROCK_MAX_TOKENS=2048
S3_BUCKET_NAME=$BUCKET_NAME

ENABLE_LANGFUSE_TRACING=false
EOF
  echo "Wrote $ENV_FILE (gitignored - contains real secrets, not committed)."
  echo "NOTE: AWS_ACCESS_KEY_ID/SECRET are only baked in if they were set in this shell's"
  echo "environment when you ran this script - see the note this script prints at the end"
  echo "about switching to an instance role instead."
else
  echo "Reusing existing $ENV_FILE."
fi

echo "--- Packaging repo (excluding .git, venv, node_modules, caches, local storage) ---"
TARBALL="$HERE/emios-deploy.tar.gz"
tar -czf "$TARBALL" -C "$REPO_ROOT" \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='.claude' \
  --exclude='.pytest_cache' \
  --exclude='storage_fallback' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='__pycache__' \
  --exclude='scripts/deploy/emios-lightsail-key.pem' \
  --exclude='scripts/deploy/emios-prod-ec2-key.pem' \
  --exclude='scripts/deploy/emios-deploy.tar.gz' \
  --exclude='scripts/deploy/.aws_credentials' \
  --exclude='scripts/deploy/.deploy_state.json' \
  --exclude='scripts/deploy/.env.production.generated' \
  .

echo "--- Shipping code to the instance ---"
$SSH 'mkdir -p ~/emios'
$SCP "$TARBALL" "ubuntu@$PUBLIC_IP:~/emios/emios-deploy.tar.gz"
$SSH 'cd ~/emios && tar -xzf emios-deploy.tar.gz && rm emios-deploy.tar.gz'
$SCP "$ENV_FILE" "ubuntu@$PUBLIC_IP:~/emios/backend/.env.production"

echo "--- Bringing the stack up (this runs the Docker build on the instance - can take a few minutes) ---"
# podman compose isn't usable here (Ubuntu 22.04's podman 3.4.4 predates the compose
# subcommand) - drive the standalone docker-compose binary bootstrap.sh installs against
# podman's Docker-API-compatible socket (also enabled by bootstrap.sh) instead.
$SSH 'cd ~/emios && sudo DOCKER_HOST=unix:///run/podman/podman.sock docker-compose -f docker-compose.prod.yml --env-file backend/.env.production up -d --build --force-recreate'

echo "--- Health check ---"
sleep 5
for i in $(seq 1 12); do
  if curl -sf "http://$PUBLIC_IP:8000/api/health"; then
    echo
    echo "Backend is up: http://$PUBLIC_IP:8000"
    exit 0
  fi
  sleep 10
done

echo "Health check did not pass after 2 minutes - check logs with:"
echo "  $SSH 'cd ~/emios && sudo DOCKER_HOST=unix:///run/podman/podman.sock docker-compose -f docker-compose.prod.yml logs backend --tail 100'"
exit 1
