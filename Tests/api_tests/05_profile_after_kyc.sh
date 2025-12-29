#!/bin/bash
source ./config.sh

if [[ ! -f token.tmp ]]; then
    print_error "Aucun token."
    exit 1
fi

source token.tmp

print_step "5. Profil mis à jour après KYC"

curl -s -X GET "${BASE_URL}/profile/" \
  -H "Authorization: bearer ${TOKEN}" | jq .

print_success "Profil affiché (doit montrer kyc_status: verified si succès)"
