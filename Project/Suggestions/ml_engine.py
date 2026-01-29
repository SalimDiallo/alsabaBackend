import pandas as pd
import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import OneHotEncoder, MinMaxScaler
from .models import UserPreference
import structlog

logger = structlog.get_logger(__name__)

class AdvancedMLEngine:
    """
    Moteur de recommandation avancé utilisant K-Nearest Neighbors (KNN).
    Trouve les utilisateurs mathématiquement proches de l'offre proposée.
    """
    
    _model = None
    _encoder = None
    _scaler = None
    _user_ids = []

    @staticmethod
    def train_model():
        """
        Entraîne le modèle sur les préférences utilisateurs actuelles.
        À appeler périodiquement (ex: Celery Task toutes les 1h) ou au démarrage.
        """
        prefs = list(UserPreference.objects.all().values(
            'user_id', 'avg_transaction_amount_cents', 'preferred_currency_sell', 'preferred_currency_buy'
        ))
        
        if not prefs:
            return False

        df = pd.DataFrame(prefs)
        
        # 1. Feature Engineering
        # On encode les devises (Catégorique -> Numérique)
        AdvancedMLEngine._encoder = OneHotEncoder(sparse_output=False, handle_unknown='ignore')
        currency_features = AdvancedMLEngine._encoder.fit_transform(df[['preferred_currency_sell', 'preferred_currency_buy']])
        
        # On normalise le montant (0.0 à 1.0)
        AdvancedMLEngine._scaler = MinMaxScaler()
        amount_features = AdvancedMLEngine._scaler.fit_transform(df[['avg_transaction_amount_cents']])
        
        # Création du vecteur final X (Features combinées)
        X = np.hstack([amount_features, currency_features])
        
        # 2. Entraînement KNN (Non supervisé)
        # On cherche les 5 voisins les plus proches
        n_neighbors = min(len(df), 5)
        AdvancedMLEngine._model = NearestNeighbors(n_neighbors=n_neighbors, algorithm='auto')
        AdvancedMLEngine._model.fit(X)
        
        AdvancedMLEngine._user_ids = df['user_id'].tolist()
        logger.info("ml_model_trained", n_samples=len(df))
        return True

    @staticmethod
    def find_matching_users(offer):
        """
        Utilise le modèle pour prédire les utilisateurs intéressés.
        Retourne une liste de (user_id, score_ml).
        """
        if AdvancedMLEngine._model is None:
            # Tente d'entraîner si pas encore fait (Cold Start)
            success = AdvancedMLEngine.train_model()
            if not success:
                return []

        # Construction du vecteur de l'offre
        # L'offre est l'inverse de la préférence :
        # Offre VEND X et ACHÈTE Y -> On cherche User qui VEUT ACHETER X et VENDRE Y
        # Donc on mappe Offer.sell -> Pref.buy et Offer.buy -> Pref.sell
        
        # Attention : Le modèle a été entraîné sur [Pref.Sell, Pref.Buy].
        # On cherche un User dont [Pref.Sell, Pref.Buy] MATCHE [Offer.Buy, Offer.Sell]
        
        try:
            # Encodage
            target_currency_sell = offer.currency_buy # Le user doit vendre ce que l'offre achète
            target_currency_buy = offer.currency_sell # Le user doit acheter ce que l'offre vend
            
            cur_vec = AdvancedMLEngine._encoder.transform([[target_currency_sell, target_currency_buy]])
            amt_vec = AdvancedMLEngine._scaler.transform([[offer.amount_sell_cents]])
            
            offer_vector = np.hstack([amt_vec, cur_vec])
            
            # Prédiction
            distances, indices = AdvancedMLEngine._model.kneighbors(offer_vector)
            
            results = []
            # indices[0] contient les index du DataFrame, distances[0] les distances
            for i, idx_in_df in enumerate(indices[0]):
                user_id = AdvancedMLEngine._user_ids[idx_in_df]
                dist = distances[0][i]
                
                # Conversion Distance -> Score (0.0 distance = 100% match)
                # Score = 1 / (1 + distance) * 100
                score_ml = int((1 / (1 + dist)) * 100)
                
                results.append((user_id, score_ml))
                
            return results
            
        except Exception as e:
            logger.error("ml_prediction_failed", error=str(e))
            return []
