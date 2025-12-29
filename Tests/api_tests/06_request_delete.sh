#!/bin/bash
source ./config.sh

if [[ ! -f token.tmp ]]; then
    print_error "Aucun token."
    exit 1
fi

source token.tmp

print_step "6. Demande de suppression de compte"

response=$(curl -s -X POST "${BASE_URL}/account/delete/" \
  -H "Authorization: bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Test de suppression"}')

echo "$response" | jq .

DELETE_SESSION_KEY=$(echo "$response" | jq -r '.session_key // empty')

if [[ -n "$DELETE_SESSION_KEY" ]]; then
    print_success "OTP de suppression envoyé"
    echo "DELETE_SESSION_KEY=$DELETE_SESSION_KEY" > delete_session.tmp
else
    print_error "Échec demande suppression"
    exit 1
fi
