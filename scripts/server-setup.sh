#!/usr/bin/env bash
# One-time server bootstrap (safe to re-run). From the repo root on your Mac:
#   ssh -i ~/prejudge.pem ubuntu@3.82.224.157 'bash -s' < scripts/server-setup.sh
# Adds a 2 GB swap file, installs Docker Engine + the Compose plugin, creates ~/prejudge.
set -euo pipefail

if ! swapon --show | grep -q /swapfile; then
  echo "== adding 2 GB swap"
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-prejudge-swap.conf >/dev/null
  sudo sysctl -q --system
fi

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  echo "== installing Docker Engine + Compose plugin (download.docker.com)"
  sudo apt-get update -q
  sudo apt-get install -yq ca-certificates curl rsync
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -q
  sudo apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
fi
sudo usermod -aG docker "$USER"

mkdir -p ~/prejudge/site ~/prejudge/backups ~/prejudge/backend
echo "== done"
free -m | sed -n '1,3p'
sudo docker --version
sudo docker compose version
