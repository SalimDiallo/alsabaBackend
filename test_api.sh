#!/bin/bash
# Script de test pour l'API ALSABA

echo "🧪 Tests de l'API ALSABA"
echo "========================"
echo ""

# Couleurs
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BASE_URL="http://127.0.0.1:8000/api/accounts"

# 1. Vérifier que le serveur répond
echo -e "${YELLOW}1. Vérification du serveur...${NC}"
if curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/auth/phone/" | grep -q "405\|400\|200"; then
    echo -e "${GREEN}✅ Serveur accessible${NC}"
else
    echo -e "${RED}❌ Serveur non accessible. Vérifiez que docker-compose est démarré${NC}"
    echo "   Commande: sudo docker-compose up -d"
    exit 1
fi

echo ""
echo -e "${YELLOW}2. Test de l'endpoint d'authentification (Request OTP)...${NC}"
PHONE_NUMBER="684499227"
COUNTRY_CODE="+212"

RESPONSE=$(curl -s -X POST "$BASE_URL/auth/phone/" \
  -H "Content-Type: application/json" \
  -d "{
    \"phone_number\": \"$PHONE_NUMBER\",
    \"country_code\": \"$COUNTRY_CODE\"
  }")

echo "Réponse: $RESPONSE"

# Extraire session_key si présent
SESSION_KEY=$(echo $RESPONSE | grep -o '"session_key":"[^"]*' | cut -d'"' -f4)

if [ ! -z "$SESSION_KEY" ]; then
    echo -e "${GREEN}✅ OTP envoyé avec succès${NC}"
    echo "   Session Key: $SESSION_KEY"
    echo ""
    echo -e "${YELLOW}📝 Pour tester la vérification OTP:${NC}"
    echo "   POST $BASE_URL/auth/verify/"
    echo "   Body: {\"phone_number\": \"+212$PHONE_NUMBER\", \"code\": \"CODE_RECU\", \"session_key\": \"$SESSION_KEY\"}"
else
    echo -e "${RED}❌ Erreur lors de l'envoi de l'OTP${NC}"
fi

echo ""
echo -e "${YELLOW}3. Endpoints disponibles:${NC}"
echo "   - POST $BASE_URL/auth/phone/          (Demander OTP)"
echo "   - POST $BASE_URL/auth/verify/         (Vérifier OTP)"
echo "   - GET  $BASE_URL/profile/            (Profil utilisateur - nécessite auth)"
echo "   - POST $BASE_URL/kyc/verify/          (Vérification KYC - nécessite auth)"
echo "   - POST $BASE_URL/delete/              (Demander suppression - nécessite auth)"
echo "   - POST $BASE_URL/delete/confirm/       (Confirmer suppression - nécessite auth)"

echo ""
echo -e "${YELLOW}📚 Pour tester avec curl:${NC}"
echo "   curl -X POST $BASE_URL/auth/phone/ \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"phone_number\": \"684499227\", \"country_code\": \"+212\"}'"

echo ""
echo -e "${YELLOW}📚 Pour tester avec le fichier HTTP:${NC}"
echo "   Utilisez VS Code avec l'extension REST Client"
echo "   Ou utilisez le fichier: Tests/api_tests/tests.http"

