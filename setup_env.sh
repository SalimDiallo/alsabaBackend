#!/bin/bash
# Script pour configurer les variables d'environnement

echo "🔧 Configuration des variables d'environnement"
echo "=============================================="
echo ""

# Vérifier si .env existe déjà
if [ -f .env ]; then
    echo "⚠️  Le fichier .env existe déjà."
    read -p "Voulez-vous le remplacer ? (o/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Oo]$ ]]; then
        echo "❌ Opération annulée."
        exit 1
    fi
    mv .env .env.backup
    echo "✅ Ancien .env sauvegardé dans .env.backup"
fi

# Copier le fichier exemple
if [ -f env.example ]; then
    cp env.example .env
    echo "✅ Fichier .env créé à partir de env.example"
else
    echo "❌ Fichier env.example non trouvé !"
    exit 1
fi

# Générer une SECRET_KEY Django
echo ""
echo "🔑 Génération d'une SECRET_KEY Django..."
SECRET_KEY=$(python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())" 2>/dev/null || echo "django-insecure-$(openssl rand -hex 32)")

# Mettre à jour la SECRET_KEY dans .env
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sed -i '' "s|SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" .env
else
    # Linux
    sed -i "s|SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" .env
fi

echo "✅ SECRET_KEY générée et ajoutée au fichier .env"
echo ""
echo "📝 Prochaines étapes :"
echo "   1. Éditez le fichier .env : nano .env"
echo "   2. Remplissez les valeurs pour Flutterwave et Didit (optionnel)"
echo "   3. Lancez Docker : sudo docker-compose up -d"
echo ""
echo "💡 Pour voir toutes les variables disponibles, consultez GUIDE_ENV.md"

