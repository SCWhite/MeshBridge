#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo"
  exit 1
fi

echo "Setting up DNS forwarding and Captive Portal..."

# 1. Backup original configuration file
if [ -f /etc/dnsmasq.conf ]; then
    cp /etc/dnsmasq.conf /etc/dnsmasq.conf.bak.$(date +%Y%m%d%H%M%S)
    echo "Original configuration backed up to /etc/dnsmasq.conf.bak.xxxx"
fi

# 2. Write new configuration
# This overwrites the existing dnsmasq.conf to ensure a clean environment
cat <<EOF > /etc/dnsmasq.conf
# MeshBridge auto-generated configuration
# Listen on WiFi interface
interface=wlan0

# Set DHCP range (matching 10.0.0.1 gateway)
dhcp-range=10.0.0.10,10.0.0.250,12h

# [Critical] Captive Portal settings
# Redirect all DNS queries (/#/) to local IP
address=/#/10.0.0.1
EOF

# 3. Restart service to apply changes
systemctl restart dnsmasq
systemctl enable dnsmasq

echo "✅ DNS setup complete! Service has been restarted."