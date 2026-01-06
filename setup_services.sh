#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo"
  exit 1
fi

# Get the script directory (ensure correct source path)
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")

echo "Installing Systemd services..."

# Check if source files exist
if [ ! -f "$SCRIPT_DIR/meshbridge-wifi.service" ] || [ ! -f "$SCRIPT_DIR/meshbridge.service" ]; then
    echo "Error: .service files not found. Please ensure you have downloaded the complete project files."
    exit 1
fi

# 1. Copy service files to system directory
echo "Copying configuration files to /etc/systemd/system/ ..."
cp "$SCRIPT_DIR/meshbridge-wifi.service" /etc/systemd/system/
cp "$SCRIPT_DIR/meshbridge.service" /etc/systemd/system/

# Replace hardcoded paths with actual script directory
echo "Updating paths in service files..."
sed -i "s|/home/pi/MeshBridge|$SCRIPT_DIR|g" /etc/systemd/system/meshbridge-wifi.service
sed -i "s|/home/pi/MeshBridge|$SCRIPT_DIR|g" /etc/systemd/system/meshbridge.service

# Set permissions (standard is 644)
chmod 644 /etc/systemd/system/meshbridge-wifi.service
chmod 644 /etc/systemd/system/meshbridge.service

# 2. Reload Systemd
echo "Reloading Systemd daemon..."
systemctl daemon-reload

# 3. Enable and start services
echo "Enabling services..."
systemctl enable meshbridge-wifi.service
systemctl enable meshbridge.service

echo "Starting services..."
systemctl restart meshbridge-wifi.service
systemctl restart meshbridge.service

echo "✅ Service installation complete! MeshBridge will now start automatically on boot."
echo "Check status: sudo systemctl status meshbridge.service"