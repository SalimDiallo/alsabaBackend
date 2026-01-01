#!/bin/bash
source ./config.sh

if [[ ! -f token.tmp ]]; then
    print_error "Aucun token. Connecte-toi d'abord."
    exit 1
fi

source token.tmp

if [[ ! -f "$FRONT_IMAGE" ]]; then
    print_error "Image recto manquante : $FRONT_IMAGE"
    echo "Passe cette Ã©tape manuellement plus tard"
    exit 0
fi

print_step "4. Envoi document pour vÃ©rification KYC"

response=$(curl -s -X POST "${BASE_URL}/kyc/verify/" \
  -H "Authorization: bearer ${TOKEN}" \
  -F "document_type=id_card" \
  -F "front_image=@${FRONT_IMAGE}" \
  -F "back_image=@${BACK_IMAGE};type=image/jpeg" \
  -F "perform_document_liveness=true" \
  -F "min_age=18")

echo "$response" | jq .

STATUS=$(echo "$response" | jq -r '.kyc_status // .didit_status // "unknown"')

if [[ "$STATUS" == "verified" ]]; then
    print_success "KYC VÃ‰RIFIÃ‰ ! í¾‰"
else
    print_info "KYC refusÃ© ou en attente - Statut : $STATUS"
fi
