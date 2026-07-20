FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV DISPLAY=:1
ENV VNC_RESOLUTION=1920x1080
ENV VNC_PORT=5901
ENV NOVNC_PORT=6080

# --- Core desktop + tooling ---
RUN apt-get update -y && apt-get install --no-install-recommends -y \
    xfce4 xfce4-goodies xfce4-terminal \
    tigervnc-standalone-server tigervnc-common \
    novnc websockify \
    sudo xterm vim nano net-tools iproute2 iputils-ping \
    curl wget git tzdata ca-certificates gnupg lsb-release \
    software-properties-common apt-transport-https \
    dbus-x11 x11-utils x11-xserver-utils x11-apps \
    openssl python3 python3-pip python3-venv \
    build-essential unzip jq htop tmux screen \
    xubuntu-icon-theme \
    openssh-client openssh-server \
 && rm -rf /var/lib/apt/lists/*

# --- Firefox via Mozilla PPA (avoid snap) ---
RUN add-apt-repository ppa:mozillateam/ppa -y && \
    printf 'Package: *\nPin: release o=LP-PPA-mozillateam\nPin-Priority: 1001\n' \
      > /etc/apt/preferences.d/mozilla-firefox && \
    apt-get update -y && apt-get install -y firefox && \
    rm -rf /var/lib/apt/lists/*

# --- Docker Engine (docker-in-docker capable) ---
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
    > /etc/apt/sources.list.d/docker.list && \
    apt-get update -y && \
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin && \
    rm -rf /var/lib/apt/lists/*

# --- tmate (static binary, works inside containers) ---
RUN curl -fsSL https://github.com/tmate-io/tmate/releases/download/2.4.0/tmate-2.4.0-static-linux-amd64.tar.xz \
      -o /tmp/tmate.tar.xz && \
    tar -xJf /tmp/tmate.tar.xz -C /tmp && \
    install -m 0755 /tmp/tmate-2.4.0-static-linux-amd64/tmate /usr/local/bin/tmate && \
    rm -rf /tmp/tmate*

# --- sshx client ---
RUN curl -sSf https://sshx.io/get | sh -s -- -q

# --- Discord bot deps ---
RUN pip3 install --no-cache-dir --break-system-packages \
    "discord.py>=2.3.2" python-dotenv docker aiohttp

# --- noVNC symlink for clean URL ---
RUN ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

# --- Working dirs ---
WORKDIR /opt/vpsforge
COPY entrypoint.sh /opt/vpsforge/entrypoint.sh
COPY bot.py /opt/vpsforge/bot.py
COPY vps_node.Dockerfile /opt/vpsforge/vps_node.Dockerfile
RUN chmod +x /opt/vpsforge/entrypoint.sh

# VNC password bootstrap dir
RUN mkdir -p /root/.vnc && touch /root/.Xauthority

EXPOSE 5901 6080 2375

CMD ["/opt/vpsforge/entrypoint.sh"]
