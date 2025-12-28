#!/bin/bash
source ./config.sh

print_step "1. Demande d'envoi OTP"

response=$(curl -s -X POST "${BASE_URL}/auth/phone/" \
  -H "Content-Type: application/json" \
  -d "{\"phone_number\": \"${TEST_PHONE}\", \"country_code\": \"${COUNTRY_CODE}\"}")

echo "$response" | jq .

SESSION_KEY=$(echo "$response" | jq -r '.session_key // empty')

if [[ -n "$SESSION_KEY" ]]; then
    print_success "OTP envoyé ! Session key sauvegardée."
    echo "SESSION_KEY=$SESSION_KEY" > session.tmp
else
    print_error "Échec envoi OTP"
    exit 1
fi
