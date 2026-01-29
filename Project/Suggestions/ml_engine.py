import pandas as pd
import numpy as np
import os
import joblib
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
    
    # Chemin vers le fichier de persistence du modèle
    MODEL_PATH = os.path.join(os.path.dirname(__file__), 'persistent_model.joblib')

    @staticmethod
    def _save_model():
        """Sauvegarde l'état du modèle sur le disque"""
        try:
            data = {
                'model': AdvancedMLEngine._model,
                'encoder': AdvancedMLEngine._encoder,
                'scaler': AdvancedMLEngine._scaler,
                'user_ids': AdvancedMLEngine._user_ids
            }
            joblib.dump(data, AdvancedMLEngine.MODEL_PATH)
            logger.info("ml_model_saved_to_disk", path=AdvancedMLEngine.MODEL_PATH)
        except Exception as e:
            logger.error("ml_model_save_failed", error=str(e))

    @staticmethod
    def _load_model():
        """Charge l'état du modèle depuis le disque"""
        if not os.path.exists(AdvancedMLEngine.MODEL_PATH):
            return False
            
        try:
            data = joblib.load(AdvancedMLEngine.MODEL_PATH)
            AdvancedMLEngine._model = data['model']
            AdvancedMLEngine._encoder = data['encoder']
            AdvancedMLEngine._scaler = data['scaler']
            AdvancedMLEngine._user_ids = data['user_ids']
            logger.info("ml_model_loaded_from_disk", n_users=len(AdvancedMLEngine._user_ids))
            return True
        except Exception as e:
            logger.error("ml_model_load_failed", error=str(e))
            return False

    @staticmethod
    def train_model():
        """
        Entraîne le modèle sur les préférences utilisateurs actuelles et le persiste.
        """
        prefs = list(UserPreference.objects.all().values(
            'user_id', 'avg_transaction_amount_cents', 'preferred_currency_sell', 'preferred_currency_buy'
        ))
        
        if not prefs:
            logger.warning("ml_train_no_data")
            return False

        df = pd.DataFrame(prefs)
        
        try:
            # 1. Feature Engineering
            AdvancedMLEngine._encoder = OneHotEncoder(sparse_output=False, handle_unknown='ignore')
            currency_features = AdvancedMLEngine._encoder.fit_transform(df[['preferred_currency_sell', 'preferred_currency_buy']])
            
            AdvancedMLEngine._scaler = MinMaxScaler()
            amount_features = AdvancedMLEngine._scaler.fit_transform(df[['avg_transaction_amount_cents']])
            
            X = np.hstack([amount_features, currency_features])
            
            # 2. Entraînement KNN
            n_neighbors = min(len(df), 5)
            AdvancedMLEngine._model = NearestNeighbors(n_neighbors=n_neighbors, algorithm='auto')
            AdvancedMLEngine._model.fit(X)
            
            AdvancedMLEngine._user_ids = df['user_id'].tolist()
            
            # 3. Persistence
            AdvancedMLEngine._save_model()
            
            logger.info("ml_model_trained_successfully", n_samples=len(df))
            return True
        except Exception as e:
            logger.error("ml_training_error", error=str(e))
            return False

    @staticmethod
    def find_matching_users(offer):
        """
        Utilise le modèle pour prédire les utilisateurs intéressés.
        Charge le modèle depuis le disque si nécessaire.
        """
        if AdvancedMLEngine._model is None:
            # Tente de charger depuis le disque
            if not AdvancedMLEngine._load_model():
                # Si pas de fichier, entraîne (Cold Start)
                if not AdvancedMLEngine.train_model():
                    return []

        try:
            # L'offre est l'inverse de la préférence (Vendre X, Acheter Y -> User qui veut Acheter X, Vendre Y)
            target_currency_sell = offer.currency_buy
            target_currency_buy = offer.currency_sell
            
            cur_vec = AdvancedMLEngine._encoder.transform([[target_currency_sell, target_currency_buy]])
            amt_vec = AdvancedMLEngine._scaler.transform([[offer.amount_sell_cents]])
            
            offer_vector = np.hstack([amt_vec, cur_vec])
            
            distances, indices = AdvancedMLEngine._model.kneighbors(offer_vector)
            
            results = []
            for i, idx_in_df in enumerate(indices[0]):
                if idx_in_df < len(AdvancedMLEngine._user_ids):
                    user_id = AdvancedMLEngine._user_ids[idx_in_df]
                    dist = distances[0][i]
                    score_ml = int((1 / (1 + dist)) * 100)
                    results.append((user_id, score_ml))
                
            return results
            
        except Exception as e:
            logger.error("ml_prediction_failed", error=str(e))
            return []
