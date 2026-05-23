#!/usr/bin/env bash
# webcam-jetson installer — runs on the Jetson.
# Idempotent: safe to re-run after updates.
set -euo pipefail

MEDIAMTX_VERSION="${MEDIAMTX_VERSION:-1.9.3}"
ARCH="$(uname -m)"
case "$ARCH" in
    aarch64) MTX_ARCH="linux_arm64v8" ;;
    x86_64)  MTX_ARCH="linux_amd64" ;;
    armv7l)  MTX_ARCH="linux_armv7" ;;
    *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
SUDO="$(command -v sudo || true)"

log() { printf "\033[1;34m==>\033[0m %s\n" "$*"; }

log "Installing apt packages (ffmpeg, python3-venv, v4l-utils, curl)..."
$SUDO apt-get update -qq
$SUDO apt-get install -y --no-install-recommends \
    ffmpeg python3-venv python3-pip v4l-utils curl ca-certificates rsync

log "Adding ${TARGET_USER} to video group..."
$SUDO usermod -aG video "$TARGET_USER" || true

# --- mediamtx ---
INSTALLED_MTX_VER=""
if command -v mediamtx >/dev/null 2>&1; then
    INSTALLED_MTX_VER="$(mediamtx --version 2>&1 | head -1 | awk '{print $NF}' | tr -d v)"
fi
if [ "$INSTALLED_MTX_VER" != "$MEDIAMTX_VERSION" ]; then
    log "Downloading mediamtx v${MEDIAMTX_VERSION} (${MTX_ARCH})..."
    tmp="$(mktemp -d)"
    url="https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_${MTX_ARCH}.tar.gz"
    curl -fsSL --retry 3 "$url" -o "$tmp/mediamtx.tgz"
    tar -xzf "$tmp/mediamtx.tgz" -C "$tmp" mediamtx
    $SUDO install -m 0755 "$tmp/mediamtx" /usr/local/bin/mediamtx
    rm -rf "$tmp"
fi
log "mediamtx: $(mediamtx --version 2>&1 | head -1)"

# --- mediamtx config ---
log "Installing /etc/webcam-jetson/mediamtx.yml..."
$SUDO mkdir -p /etc/webcam-jetson
$SUDO install -m 0644 "$REPO_DIR/mediamtx.yml" /etc/webcam-jetson/mediamtx.yml

# --- python venv + webcam_server.py ---
log "Setting up venv at /opt/webcam-jetson..."
$SUDO mkdir -p /opt/webcam-jetson
$SUDO chown "$TARGET_USER:$TARGET_USER" /opt/webcam-jetson
if [ ! -x /opt/webcam-jetson/venv/bin/python ]; then
    sudo -u "$TARGET_USER" python3 -m venv /opt/webcam-jetson/venv
fi
sudo -u "$TARGET_USER" /opt/webcam-jetson/venv/bin/pip install --quiet --upgrade pip wheel
sudo -u "$TARGET_USER" /opt/webcam-jetson/venv/bin/pip install --quiet "aiohttp>=3.9"
install -m 0644 "$REPO_DIR/webcam_server.py" /opt/webcam-jetson/webcam_server.py

# --- recordings dir ---
$SUDO mkdir -p /var/lib/webcam-jetson/recordings
$SUDO chown -R "$TARGET_USER:$TARGET_USER" /var/lib/webcam-jetson

# --- systemd units (substitute __WCAM_USER__) ---
log "Installing systemd units..."
for unit in webcam-mediamtx.service webcam-server.service; do
    sed "s/__WCAM_USER__/${TARGET_USER}/g" "$REPO_DIR/systemd/$unit" \
        | $SUDO tee "/etc/systemd/system/$unit" >/dev/null
    $SUDO chmod 0644 "/etc/systemd/system/$unit"
done

$SUDO systemctl daemon-reload
$SUDO systemctl enable webcam-mediamtx.service webcam-server.service
$SUDO systemctl restart webcam-mediamtx.service
sleep 1
$SUDO systemctl restart webcam-server.service
sleep 1

log "Status:"
systemctl --no-pager --lines=0 status webcam-mediamtx.service webcam-server.service || true

HOSTNAME_SHORT="$(hostname)"
cat <<EOF

\033[1;32m==> done.\033[0m

URLs (Tailnet host: ${HOSTNAME_SHORT}):
  HTTP API   : http://${HOSTNAME_SHORT}:8080/healthz
  Snapshot   : http://${HOSTNAME_SHORT}:8080/snapshot.jpg
  MJPEG live : http://${HOSTNAME_SHORT}:8080/stream.mjpg
  RTSP       : rtsp://${HOSTNAME_SHORT}:8554/cam
  HLS        : http://${HOSTNAME_SHORT}:8888/cam/index.m3u8

Logs:
  journalctl -u webcam-mediamtx -f
  journalctl -u webcam-server -f

If you were just added to the video group, log out and back in for it to take effect.
EOF
