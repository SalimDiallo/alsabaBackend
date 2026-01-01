#!/bin/bash

# Configuration commune à tous les tests
BASE_URL="http://127.0.0.1:8000/api/accounts"
TEST_PHONE="0628852135"           # À CHANGER avec ton numéro réel
COUNTRY_CODE="+212"
TEST_PHONE_E164="+212628852135"

# Chemins images KYC (adapte selon ton PC)
FRONT_IMAGE="../test_images/carte_identite_recto.jpg"
BACK_IMAGE="../test_images/carte_identite_verso.jpg"

# Couleurs
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_info() { echo -e "${YELLOW}ℹ $1${NC}"; }
print_step() { echo -e "${BLUE}>>> $1${NC}"; }
