#!/bin/bash
source ./config.sh

if [[ ! -f token.tmp ]]; then
    print_error "Aucun token. Connecte-toi d'abord avec 02_verify_otp.sh"
    exit 1
fi

source token.tmp

print_step "3. Récupération du profil utilisateur"

curl -s -X GET "${BASE_URL}/profile/" \
  -H "Authorization: bearer ${TOKEN}" | jq .

print_success "Profil affiché"
