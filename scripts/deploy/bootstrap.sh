#!/bin/bash
# Lightsail userData script - runs once as root via cloud-init on first boot of the
# instance created by provision.py. Installs everything needed to run
# docker-compose.prod.yml via podman before deploy.sh ever SSHes in, so deploy.sh
# doesn't have to wait through package installs on every run.
exec > /var/log/emios-bootstrap.log 2>&1
set -x

apt-get update -y
apt-get install -y podman git curl

# Prefer Ubuntu 22.04's docker-compose-v2 package (provides `docker compose`, which
# `podman compose` can shell out to). Fall back to the standalone v2 binary if that
# package isn't available in the configured repos.
apt-get install -y docker-compose-v2 || true

if ! command -v docker-compose >/dev/null 2>&1 && ! podman compose version >/dev/null 2>&1; then
  curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
fi

# Ubuntu 22.04 ships podman 3.4.4, which has no `compose` subcommand at all (added in
# podman 4.x) - deploy.sh drives the standalone docker-compose binary above against this
# socket instead (DOCKER_HOST=unix:///run/podman/podman.sock), since docker-compose needs
# a Docker-API-compatible endpoint and podman doesn't expose one by default.
systemctl enable --now podman.socket

# This account is capped to free-tier/smallest instance+bundle sizes (1GB RAM) on
# both EC2 and Lightsail - see RUNBOOK.md §6.2. Building the backend's Python image
# plus running Postgres + Neo4j + the app in 1GB alone risks OOM kills mid-deploy,
# so add swap unconditionally (harmless on bigger instances too).
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p /opt/emios
echo "bootstrap complete: $(date -u)" > /opt/emios/bootstrap.done
podman --version >> /opt/emios/bootstrap.done 2>&1 || true
(podman compose version || docker-compose --version) >> /opt/emios/bootstrap.done 2>&1 || true
