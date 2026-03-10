FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    openssh-client \
    iputils-ping \
    net-tools \
    nmap \
    curl \
    wget \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Five adversary accounts: key-only auth enforced; keys mounted at runtime
RUN for u in moist teatime carrot angua vimes; do \
        useradd -m -s /bin/bash "$u"; \
        mkdir -p /home/$u/.ssh; \
        chmod 700 /home/$u/.ssh; \
        chown $u:$u /home/$u/.ssh; \
    done

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
