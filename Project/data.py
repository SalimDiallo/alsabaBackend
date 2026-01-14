import sqlite3

# Chemin vers ton fichier db.sqlite3 (change si besoin)
DB_PATH = "db.sqlite3"  # ← Mets le chemin complet si pas à la racine

def vider_toutes_les_tables():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Récupère la liste de toutes les tables (sauf tables système SQLite)
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """)
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            print("Aucune table trouvée dans la base.")
            return

        print(f"Trouvées {len(tables)} tables :")
        for table in tables:
            print(f"  - {table}")

        # Confirmation
        reponse = input("\nVoulez-vous vraiment VIDER (supprimer toutes les lignes) de ces tables ? (oui/non) : ").strip().lower()
        if reponse != "oui":
            print("Opération annulée.")
            return

        # Vidage de chaque table
        for table in tables:
            cursor.execute(f"DELETE FROM {table}")
            print(f"Table {table} vidée ({cursor.rowcount} lignes supprimées)")

        # Réinitialise les compteurs d'auto-incrément (rowid)
        cursor.execute("DELETE FROM sqlite_sequence")
        print("Compteurs d'auto-incrément réinitialisés.")

        conn.commit()
        print("\nOpération terminée avec succès. La base est maintenant vide (tables conservées).")

    except sqlite3.Error as e:
        print("Erreur SQLite :", e)
    
    finally:
        if conn:
            conn.close()

def supprimer_documents_kyc(
    db_path: str = "db.sqlite3",
    user_id: str = "5f7bf4b4-0831-4190-9163-47302ee0a27b",
    document_type: str = "id_card",
    auto_confirm: bool = False
) -> None:
    """
    Supprime les documents KYC d'un utilisateur pour un type de document spécifique.
    
    Args:
        db_path: Chemin vers le fichier SQLite (défaut: db.sqlite3)
        user_id: UUID de l'utilisateur (string)
        document_type: Type de document à supprimer ('id_card', 'passport', etc.)
        auto_confirm: Si True, supprime sans demander confirmation (attention !)
    
    Returns:
        None (affiche les résultats dans la console)
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Vérifie les documents existants
        cursor.execute("""
            SELECT id, document_type, verification_status, created_at 
            FROM kyc_documents 
            WHERE user_id = ? AND document_type = ?
        """, (user_id, document_type))
        
        rows = cursor.fetchall()
        
        if not rows:
            print(f"Aucun document trouvé pour user_id={user_id} et document_type={document_type}")
            return

        # 2. Affichage des documents trouvés
        print(f"{len(rows)} document(s) trouvé(s) pour suppression :")
        for row in rows:
            print(f"  - ID: {row[0]} | Type: {row[1]} | Statut: {row[2]} | Créé: {row[3]}")

        # 3. Confirmation (sauf si auto_confirm=True)
        if auto_confirm:
            print("Mode auto-confirm activé → suppression immédiate")
            confirm = "oui"
        else:
            confirm = input("\nSupprimer ces lignes ? (oui/non) : ").strip().lower()

        if confirm == "oui":
            cursor.execute("""
                DELETE FROM kyc_documents 
                WHERE user_id = ? AND document_type = ?
            """, (user_id, document_type))
            
            conn.commit()
            print(f"{cursor.rowcount} ligne(s) supprimée(s) avec succès.")
        else:
            print("Opération annulée.")

    except sqlite3.Error as e:
        print(f"Erreur SQLite : {e}")
    
    finally:
        if conn:
            conn.close()


# Exemple d'utilisation (tu peux commenter/décommenter selon besoin)
if __name__ == "__main__":
    vider_toutes_les_tables()