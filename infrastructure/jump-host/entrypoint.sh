#!/usr/bin/env bash
set -euo pipefail

mkdir -p /var/run/sshd

# Write sshd drop-in config
cat > /etc/ssh/sshd_config.d/jumphost.conf << 'EOF'
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowTcpForwarding yes
GatewayPorts no
X11Forwarding no
MaxAuthTries 3
EOF

VALID_USERS="moist teatime carrot angua vimes"

# Distribute authorized_keys from the mounted adversary-keys file.
# Format: username ssh-... [comment]
# Lines starting with # are skipped. Unknown usernames are skipped.
if [ -f /run/adversary-keys ]; then
    while IFS= read -r line; do
        # Skip blank lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

        username=$(echo "$line" | awk '{print $1}')
        pubkey=$(echo "$line" | cut -d' ' -f2-)

        if echo "$VALID_USERS" | grep -qw "$username"; then
            auth_keys="/home/${username}/.ssh/authorized_keys"
            echo "$pubkey" >> "$auth_keys"
            chmod 600 "$auth_keys"
            chown "${username}:${username}" "$auth_keys"
        else
            echo "[entrypoint] Skipping unknown user: $username" >&2
        fi
    done < /run/adversary-keys
else
    echo "[entrypoint] Warning: /run/adversary-keys not mounted: no keys distributed" >&2
fi

# Copy adversary README to each user's home directory
if [ -f /run/adversary-readme.txt ]; then
    for u in $VALID_USERS; do
        cp /run/adversary-readme.txt "/home/${u}/README"
        chown "${u}:${u}" "/home/${u}/README"
    done
fi

exec /usr/sbin/sshd -D
