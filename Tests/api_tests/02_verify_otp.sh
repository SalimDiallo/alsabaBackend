#!/bin/bash
source ./config.sh

if [[ ! -f session.tmp ]]; then
    print_error "Aucune session trouvée. Lance d'abord 01_request_otp.sh"
    exit 1
fi

source session.tmp

echo "Entre le code OTP reçu par SMS : "
read OTP_CODE

print_step "2. Vérification OTP"

response=$(curl -s -X POST "${BASE_URL}/auth/verify/" \
  -H "Content-Type: application/json" \
  -d "{\"phone_number\": \"${TEST_PHONE_E164}\", \"code\": \"${OTP_CODE}\", \"session_key\": \"${SESSION_KEY}\"}")

echo "$response" | jq .

TOKEN=$(echo "$response" | jq -r '.auth.token // empty')

if [[ -n "$TOKEN" ]]; then
    print_success "Connexion réussie ! Token sauvegardé."
    echo "TOKEN=$TOKEN" > token.tmp
    rm -f session.tmp
else
    print_error "Code invalide ou session expirée"
    exit 1
fi