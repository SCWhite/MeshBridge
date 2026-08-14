#!/bin/bash

# MeshBridge Quick Installer Bootstrap
# Usage: curl -sSL https://raw.githubusercontent.com/SCWhite/MeshBridge/main/quick_install.sh | bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}    MeshBridge Explorer Bootstrap        ${NC}"
echo -e "${GREEN}=========================================${NC}"

# 1. Check if git is installed
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}[Installing git]${NC}"
    sudo apt update && sudo apt install -y git
fi

# 2. Define Clone Directory
INSTALL_DIR="$HOME/MeshBridge"

if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Directory $INSTALL_DIR already exists.${NC}"
    read -p "Do you want to overwrite it? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
    else
        echo "Installation aborted."
        exit 1
    fi
fi

# 3. Clone Repository
echo -e "${YELLOW}[Cloning MeshBridge repository]${NC}"
git clone https://github.com/SCWhite/MeshBridge.git "$INSTALL_DIR"

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to clone repository.${NC}"
    exit 1
fi

# 4. Run the local installer
cd "$INSTALL_DIR" || exit 1
echo -e "${GREEN}Repository cloned. Starting local installation...${NC}"

if [ -f "install.sh" ]; then
    chmod +x install.sh
    ./install.sh
else
    echo -e "${RED}Error: install.sh not found in the cloned repository.${NC}"
    exit 1
fi
