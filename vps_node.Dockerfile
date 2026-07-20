FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y \
    sudo curl wget vim nano git ca-certificates openssh-server \
    net-tools iproute2 iputils-ping xz-utils tmux htop \
    python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*

# tmate static binary (works inside containers, no ptrace weirdness)
RUN curl -fsSL https://github.com/tmate-io/tmate/releases/download/2.4.0/tmate-2.4.0-static-linux-amd64.tar.xz \
      -o /tmp/tmate.tar.xz && \
    tar -xJf /tmp/tmate.tar.xz -C /tmp && \
    install -m 0755 /tmp/tmate-2.4.0-static-linux-amd64/tmate /usr/local/bin/tmate && \
    rm -rf /tmp/tmate*

# sshx client
RUN curl -sSf https://sshx.io/get | sh -s -- -q

# Default unprivileged user with passwordless sudo
RUN useradd -m -s /bin/bash vps && \
    echo "vps:vps" | chpasswd && \
    echo "vps ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

CMD ["/bin/bash", "-c", "tail -f /dev/null"]
