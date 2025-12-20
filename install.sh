#!/bin/bash

# MeshBridge Local Installer
# Run this script AFTER cloning the repository.

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
cd "$SCRIPT_DIR"

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}    MeshBridge Setup Starting...         ${NC}"
echo -e "${GREEN}=========================================${NC}"

# 1. Check user (Should NOT be root)
if [ "$EUID" -eq 0 ]; then
  echo -e "${RED}Error: Please do NOT run this script as root.${NC}"
  echo "Run it as your normal user (e.g., pi). We will ask for sudo when needed."
  exit 1
fi

# =================================================================
# 1.5 Check WiFi Interface Status (Critical for Pi OS)
# =================================================================
echo -e "${YELLOW}[Checking WiFi Status]${NC}"

# Check if rfkill detects a soft block
if command -v rfkill &> /dev/null; then
    if rfkill list wifi | grep -q "Soft blocked: yes"; then
        echo -e "${RED}Warning: WiFi interface is currently 'Soft Blocked'!${NC}"
        echo "This usually happens on a fresh Raspberry Pi OS when the WLAN Country Code is not set."
        echo "Without this, the hotspot cannot start."
        echo ""
        echo -e "${YELLOW}Option 1: Automatically set country to 'TW' (Taiwan) and unblock.${NC}"
        echo -e "${YELLOW}Option 2: Exit and configure manually via 'sudo raspi-config'.${NC}"
        echo ""
        
        read -p "Do you want to set WiFi country to TW and unblock now? (y/n) " -n 1 -r
        echo ""
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Setting WiFi Country to TW..."
            # Non-interactive mode to set country to TW
            sudo raspi-config nonint do_wifi_country TW
            
            echo "Unblocking WiFi..."
            sudo rfkill unblock wifi
            
            # Wait a moment for the interface to come up
            sleep 3
            echo -e "${GREEN}WiFi has been unblocked and enabled!${NC}"
        else
            echo -e "${RED}Installation aborted.${NC}"
            echo "Please run 'sudo raspi-config' -> '5 Localisation Options' -> 'L4 WLAN Country' to set it manually."
            exit 1
        fi
    else
        echo -e "${GREEN}WiFi interface looks good (Unblocked).${NC}"
    fi
else
    echo "rfkill command not found, skipping check. (Assuming WiFi is okay)"
fi

echo ""

# =================================================================
# 2. Install System Dependencies
# =================================================================
echo -e "${YELLOW}[1/4] Installing system dependencies...${NC}"
sudo apt update
sudo apt install -y python3-venv python3-pip dnsmasq

# 3. Setup Python Environment
echo -e "${YELLOW}[2/4] Setting up Python virtual environment...${NC}"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and install requirements
source venv/bin/activate
echo "Installing Python packages from requirements.txt..."

if [ -f "requirements.txt" ]; then
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo -e "${RED}Error: requirements.txt not found!${NC}"
    exit 1
fi

# 4. Execute Configuration Scripts
echo -e "${YELLOW}[3/4] Configuring WiFi, DNS, and Services...${NC}"

# Ensure scripts are executable
chmod +x setup_wifi.sh setup_dns.sh setup_services.sh

# Run DNS Setup
echo "--- Running DNS Setup ---"
sudo ./setup_dns.sh

# Run WiFi Setup
echo "--- Running WiFi Setup ---"
sudo ./setup_wifi.sh

# Run Service Registration
echo "--- Registering Systemd Services ---"
sudo ./setup_services.sh

# 5. Completion
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}      Installation Complete! 🎉          ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo "System services have been registered and started."
echo "Please reboot your Raspberry Pi to ensure all network settings apply correctly."
echo ""
read -p "Do you want to reboot now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo reboot
fi
