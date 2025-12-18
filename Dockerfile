# ===================================
# Dockerfile pour Django avec MySQL
# ===================================

# Image de base Python
FROM python:3.12-slim

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Répertoire de travail
WORKDIR /app

# Installation des dépendances système pour PostgreSQL
RUN apt-get update && apt-get install -y \
    libpq-dev \
    build-essential \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copie des fichiers de requirements
COPY requirements.txt .

# Installation des dépendances Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copie du projet
COPY Project/ .

# Copie du script d'entrée
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Port exposé
EXPOSE 8000

# Script d'entrée
ENTRYPOINT ["/docker-entrypoint.sh"]

# Commande par défaut
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
