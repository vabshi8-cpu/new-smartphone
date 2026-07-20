#!/usr/bin/env bash
set -e

# --- Start dockerd (in-container daemon) ---
mkdir -p /var/lib/docker /etc/docker
cat >/etc/docker/daemon.json <<EOF
{
  "storage-driver": "vfs",
  "iptables": false,
  "bridge": "none"
}
EOF

dockerd > /var/log/dockerd.log 2>&1 &
echo "[vpsforge] waiting for docker daemon..."
for i in {1..30}; do
  if docker info >/dev/null 2>&1; then
    echo "[vpsforge] docker up."
    break
  fi
  sleep 1
done

# --- Build the VPS node image once ---
if ! docker image inspect vpsforge-node:latest >/dev/null 2>&1; then
  echo "[vpsforge] building vpsforge-node image..."
  docker build -t vpsforge-node:latest -f /opt/vpsforge/vps_node.Dockerfile /opt/vpsforge || \
    echo "[vpsforge] node image build failed, bot will retry lazily."
fi

# --- XFCE + VNC ---
export USER=root
export HOME=/root
mkdir -p /root/.vnc
cat >/root/.vnc/xstartup <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
xrdb $HOME/.Xresources 2>/dev/null || true
startxfce4 &
EOF
chmod +x /root/.vnc/xstartup

vncserver -kill :1 >/dev/null 2>&1 || true
vncserver :1 -localhost no -SecurityTypes None -geometry ${VNC_RESOLUTION} --I-KNOW-THIS-IS-INSECURE

# --- Self-signed cert for websockify ---
if [ ! -f /root/self.pem ]; then
  openssl req -new -subj "/C=US/ST=NA/L=NA/O=vpsforge/CN=localhost" \
    -x509 -days 365 -nodes -out /root/self.pem -keyout /root/self.pem
fi

websockify -D --web=/usr/share/novnc/ --cert=/root/self.pem ${NOVNC_PORT} localhost:${VNC_PORT}

# --- Launch the Discord bot (if token provided) ---
if [ -n "$DISCORD_TOKEN" ]; then
  echo "[vpsforge] starting Discord bot..."
  python3 /opt/vpsforge/bot.py > /var/log/vpsforge-bot.log 2>&1 &
else
  echo "[vpsforge] DISCORD_TOKEN not set; skipping bot."
fi

echo "[vpsforge] ready. noVNC: http://<host>:${NOVNC_PORT}/vnc.html"
tail -f /var/log/dockerd.log /var/log/vpsforge-bot.log 2>/dev/null
