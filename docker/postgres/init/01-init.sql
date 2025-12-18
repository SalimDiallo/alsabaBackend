-- ===================================
-- Script d'initialisation PostgreSQL
-- Exécuté au premier démarrage du conteneur
-- ===================================

-- Extensions utiles pour PostgreSQL
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Message de confirmation
DO $$
BEGIN
    RAISE NOTICE 'Base de données ALSABA initialisée avec succès!';
END $$;
