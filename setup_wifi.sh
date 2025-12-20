#!/bin/bash

# Wait for network interface to initialize (prevents missing wlan0 on fast boot)
sleep 5

# 1. Get wlan0 MAC address
# E.g. b8:27:eb:12:34:56 -> 123456 -> take last 4 digits 3456
RAW_MAC=$(cat /sys/class/net/wlan0/address)
# Remove colons, convert to uppercase, take the last 4 characters
SUFFIX=$(echo $RAW_MAC | tr -d ':' | tr 'a-z' 'A-Z' | tail -c 5)

TARGET_SSID="MeshBridge_$SUFFIX"
CON_NAME="MeshBridge-Hotspot"

echo "----------------------------------------"
echo "Detected MAC: $RAW_MAC"
echo "Target SSID: $TARGET_SSID"
echo "----------------------------------------"

# 2. Check if connection named MeshBridge-Hotspot already exists
if nmcli connection show "$CON_NAME" > /dev/null 2>&1; then
    # Get current SSID
    CURRENT_SSID=$(nmcli -g 802-11-wireless.ssid connection show "$CON_NAME")
    
    if [ "$CURRENT_SSID" == "$TARGET_SSID" ]; then
        echo "✅ Current SSID ($CURRENT_SSID) is correct. No change needed."
        # Ensure connection is up
        nmcli con up "$CON_NAME"
        exit 0
    else
        echo "⚠️  SSID mismatch (Current: $CURRENT_SSID). Updating..."
        # Delete old configuration
        nmcli connection delete "$CON_NAME"
    fi
else
    echo "ℹ️  Hotspot not created yet. Initializing..."
fi

# 3. Create new hotspot profile (Static IP 10.0.0.1)
echo "Creating hotspot: $TARGET_SSID ..."

nmcli con add type wifi ifname wlan0 con-name "$CON_NAME" autoconnect yes ssid "$TARGET_SSID"
# Set AP mode and static IP
nmcli con modify "$CON_NAME" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method manual ipv4.addresses 10.0.0.1/24

# 4. Activate hotspot
nmcli con up "$CON_NAME"

echo "🎉 Setup complete! New SSID is: $TARGET_SSID"