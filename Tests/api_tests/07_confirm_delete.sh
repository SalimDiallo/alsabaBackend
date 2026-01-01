#!/bin/bash
source ./config.sh

if [[ ! -f token.tmp || ! -f delete_session.tmp ]]; then
    print_error "Token ou session suppression manquant"
    exit 1
fi

source token.tmp
source delete_session.tmp

echo "Entre le code OTP reçu pour confirmer la suppression : "
read DELETE_OTP

print_step "7. Confirmation suppression"

response=$(curl -s -X POST "${BASE_URL}/account/delete/confirm/" \
  -H "Authorization: bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"code\": \"${DELETE_OTP}\", \"session_key\": \"${DELETE_SESSION_KEY}\"}")

echo "$response" | jq .

if [[ $(echo "$response" | jq -r '.success') == "true" ]]; then
    print_success "COMPTE SUPPRIMÉ (soft delete) !"
    rm -f token.tmp delete_session.tmp
else
    print_error "Échec confirmation"
fi
