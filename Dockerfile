# ===================================
# Dockerfile pour Django avec PostgreSQL
# ===================================

FROM python:3.12-slim

# Variables d'environnement Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Répertoire de travail
WORKDIR /app

# Installation des dépendances système
RUN apt-get update && apt-get install -y \
    libpq-dev \
    build-essential \
    netcat-openbsd \
    postgresql-client \   
    && rm -rf /var/lib/apt/lists/*

# Copie du requirements.txt
COPY requirements.txt .

# Upgrade pip et installation des dépendances Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY Project/ .
# Copie du script d'entrée
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Correction des fins de ligne Windows (facultatif mais recommandé)
RUN sed -i 's/\r$//' /docker-entrypoint.sh

# Port exposé
EXPOSE 8000

# Script d'entrée
ENTRYPOINT ["/docker-entrypoint.sh"]

# Commande par défaut
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]