#!/bin/bash

# ==============================================================================
# CONFIGURE YOUR VALUES HERE
# Replace the placeholder values below with your actual AlloyDB details.
# ==============================================================================
PROJECT_ID="gemini-adk-vertex-2025"
INSTANCE_ID="primary-instance"
CLUSTER_ID="online-boutique"
REGION="europe-west1"
# ==============================================================================

# --- Color Codes for Output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}--- AlloyDB Auth Proxy Connector ---${NC}\n"

# 1. Check if required tools are installed
if ! command -v alloydb-auth-proxy &> /dev/null; then
    echo -e "${RED}Error: 'alloydb-auth-proxy' command not found.${NC}"
    echo "Please install it and ensure it's in your system's PATH."
    exit 1
fi

# 2. Check if variables have been set
if [[ "$PROJECT_ID" == "your-project-id-here" || -z "$PROJECT_ID" ]]; then
    echo -e "${RED}Error: Please edit the script and set your PROJECT_ID at the top.${NC}"
    exit 1
fi

# 3. Construct the full instance connection name from the variables
INSTANCE_CONNECTION_NAME="projects/${PROJECT_ID}/locations/${REGION}/clusters/${CLUSTER_ID}/instances/${INSTANCE_ID}"

echo -e "${GREEN}Attempting to connect to:${NC}"
echo -e "${YELLOW}${INSTANCE_CONNECTION_NAME}${NC}\n"

# 4. Execute the proxy command 🚀
alloydb-auth-proxy "${INSTANCE_CONNECTION_NAME}"