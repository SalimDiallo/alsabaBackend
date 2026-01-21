import time
import uuid
from datetime import datetime, timedelta
import structlog
from django.conf import settings
from enum import Enum

logger = structlog.get_logger(__name__)

class DocumentType(Enum):
    ID_CARD = "ID_CARD"
    PASSPORT = "PASSPORT"
    DRIVER_LICENSE = "DRIVER_LICENSE"
    RESIDENCE_PERMIT = "RESIDENCE_PERMIT"

class VerificationStatus(Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"

class DiditKYCService:
    BASE_URL = "https://verification.didit.me/v3/id-verification/"
    
    # Données simulées pour différents types de documents
    SIMULATED_DOCUMENTS = {
        DocumentType.ID_CARD: {
            "document_number": "ID12345678",
            "first_name": "JEAN",
            "last_name": "DUPONT",
            "birth_date": "1985-06-15",
            "expiry_date": "2030-12-31",
            "nationality": "FRA",
            "mrz": "IDFRADUPONT<<JEAN<<<<<<<<<<<<<<<<\n1234567890FRA8506159M3012312<<<<<<<<<<<<<<04",
            "issuing_country": "FRA",
            "document_type": "ID_CARD"
        },
        DocumentType.PASSPORT: {
            "document_number": "P12345678",
            "first_name": "MARIE",
            "last_name": "MARTIN",
            "birth_date": "1990-03-22",
            "expiry_date": "2028-06-30",
            "nationality": "FRA",
            "mrz": "P<FRAMARTIN<<MARIE<<<<<<<<<<<<<<<<\nP123456789FRA9003229F2806307<<<<<<<<<<<<<<08",
            "issuing_country": "FRA",
            "document_type": "PASSPORT"
        },
        DocumentType.DRIVER_LICENSE: {
            "document_number": "DL98765432",
            "first_name": "PIERRE",
            "last_name": "DURAND",
            "birth_date": "1978-11-08",
            "expiry_date": "2027-08-15",
            "nationality": "FRA",
            "mrz": None,
            "issuing_country": "FRA",
            "document_type": "DRIVER_LICENSE"
        }
    }

    def __init__(self):
        """Initialisation avec clé API simulée"""
        self.simulated_api_key = getattr(settings, 'DIDIT_API_KEY', 'simulated-key-123456')
        self.timeout = 60
        self.simulation_mode = True  # Mode simulation activé
        
        # Statistiques de simulation
        self._simulation_stats = {
            "total_requests": 0,
            "approved": 0,
            "rejected": 0,
            "pending": 0
        }

    def verify_id_document(
        self,
        front_image,
        back_image=None,
        perform_document_liveness=False,
        minimum_age=None,
        expiration_date_not_detected_action="DECLINE",
        invalid_mrz_action="DECLINE",
        inconsistent_data_action="DECLINE",
        preferred_characters="latin",
        save_api_request=True,
        vendor_data=None,
    ):
        """Simulation complète de la vérification de document"""
        
        # Incrémenter les statistiques
        self._simulation_stats["total_requests"] += 1
        
        # Validation locale simulée
        front_valid, front_msg = self.validate_image_before_upload(front_image)
        if not front_valid:
            logger.warning("simulation_invalid_front", message=front_msg)
            return {
                "success": False, 
                "message": f"Recto invalide: {front_msg}", 
                "code": "invalid_front_image"
            }

        if back_image:
            back_valid, back_msg = self.validate_image_before_upload(back_image)
            if not back_valid:
                logger.warning("simulation_invalid_back", message=back_msg)
                return {
                    "success": False, 
                    "message": f"Verso invalide: {back_msg}", 
                    "code": "invalid_back_image"
                }

        # Simulation du traitement
        logger.info("didit_simulation_request", 
                   vendor_data=vendor_data[:50] if vendor_data else None,
                   perform_liveness=perform_document_liveness)
        
        # Simulation d'un délai de traitement (0.5 à 2 secondes)
        time.sleep(self._simulate_processing_delay())
        
        try:
            # Générer une réponse simulée
            request_id = str(uuid.uuid4())
            document_type = self._detect_document_type_from_image(front_image)
            
            # Décision simulée basée sur plusieurs facteurs
            verification_result = self._simulate_verification_decision(
                document_type=document_type,
                minimum_age=minimum_age,
                perform_liveness=perform_document_liveness,
                expiration_action=expiration_date_not_detected_action,
                vendor_data=vendor_data
            )
            
            # Mettre à jour les statistiques
            self._update_simulation_stats(verification_result["status"])
            
            # Construire la réponse complète
            response = {
                "success": True,
                "request_id": request_id,
                "status": verification_result["status"],
                "id_verification": {
                    "status": verification_result["status"],
                    "document": verification_result["document_data"],
                    "checks": verification_result["checks"],
                    "verification_score": verification_result["score"],
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "vendor_data": vendor_data
                },
                "raw": {
                    "request_id": request_id,
                    "id_verification": verification_result,
                    "simulation_mode": True,
                    "processing_time_ms": verification_result["processing_time"]
                }
            }
            
            logger.info("didit_simulation_success", 
                       request_id=request_id,
                       status=verification_result["status"],
                       document_type=document_type.value)
            
            return response

        except Exception as e:
            logger.error("didit_simulation_error", error=str(e))
            return {
                "success": False, 
                "message": f"Erreur de simulation : {str(e)}", 
                "code": "simulation_error"
            }

    def _simulate_verification_decision(self, document_type, minimum_age, perform_liveness, expiration_action, vendor_data):
        """Simule la décision de vérification"""
        
        # Récupérer les données du document simulé
        document_data = self.SIMULATED_DOCUMENTS.get(document_type, self.SIMULATED_DOCUMENTS[DocumentType.ID_CARD]).copy()
        
        # Ajouter un ID unique pour ce document
        document_data["id"] = str(uuid.uuid4())
        
        # Simuler différents scores et statuts
        import random
        import hashlib
        
        # Utiliser le vendor_data pour générer une "seed" déterministe
        seed = vendor_data or str(uuid.uuid4())
        seed_hash = int(hashlib.md5(seed.encode()).hexdigest(), 16)
        random.seed(seed_hash % 1000)
        
        # Score de vérification (80% de succès, 15% manuel, 5% rejet)
        score_distribution = random.random()
        
        if score_distribution < 0.80:  # 80% approuvé
            status = VerificationStatus.APPROVED.value
            score = random.uniform(85.0, 99.9)
            self._simulation_stats["approved"] += 1
        elif score_distribution < 0.95:  # 15% revue manuelle
            status = VerificationStatus.MANUAL_REVIEW.value
            score = random.uniform(60.0, 84.9)
            self._simulation_stats["pending"] += 1
        else:  # 5% rejeté
            status = VerificationStatus.REJECTED.value
            score = random.uniform(30.0, 59.9)
            self._simulation_stats["rejected"] += 1
        
        # Vérifier l'âge minimum si spécifié
        if minimum_age:
            birth_date = datetime.strptime(document_data["birth_date"], "%Y-%m-%d")
            age = (datetime.now() - birth_date).days // 365
            if age < minimum_age:
                status = VerificationStatus.REJECTED.value
                score = 40.0
        
        # Simuler les vérifications effectuées
        checks = {
            "document_authenticity": {
                "passed": status != VerificationStatus.REJECTED.value,
                "score": score * 0.3
            },
            "data_consistency": {
                "passed": random.choice([True, False]) if status == VerificationStatus.MANUAL_REVIEW.value else True,
                "score": score * 0.25
            },
            "image_quality": {
                "passed": True,
                "score": random.uniform(90.0, 100.0)
            },
            "mrz_validation": {
                "passed": document_data.get("mrz") is not None,
                "score": 100.0 if document_data.get("mrz") else 0.0
            },
            "liveness_check": {
                "passed": perform_liveness,
                "score": 100.0 if perform_liveness else 0.0,
                "performed": perform_liveness
            },
            "expiration_check": {
                "passed": datetime.now() < datetime.strptime(document_data["expiry_date"], "%Y-%m-%d"),
                "action": expiration_action,
                "score": 100.0 if datetime.now() < datetime.strptime(document_data["expiry_date"], "%Y-%m-%d") else 0.0
            }
        }
        
        return {
            "status": status,
            "document_data": document_data,
            "checks": checks,
            "score": round(score, 2),
            "processing_time": random.randint(800, 2500)
        }

    def _detect_document_type_from_image(self, image):
        """Simule la détection du type de document depuis l'image"""
        # Simuler la détection basée sur le nom du fichier ou autres attributs
        filename = getattr(image, 'name', '').lower()
        
        if 'passeport' in filename or 'passport' in filename:
            return DocumentType.PASSPORT
        elif 'permis' in filename or 'license' in filename:
            return DocumentType.DRIVER_LICENSE
        elif 'carte_sejour' in filename or 'residence' in filename:
            return DocumentType.RESIDENCE_PERMIT
        else:
            # Par défaut, carte d'identité
            return DocumentType.ID_CARD

    def _simulate_processing_delay(self):
        """Simule un délai de traitement réaliste"""
        import random
        return random.uniform(0.5, 2.0)

    def validate_image_before_upload(self, image):
        """
        Validation simple sans magic : taille + présence
        Même implémentation que l'original pour la compatibilité
        """
        if not image:
            return False, "Image absente"

        if hasattr(image, 'size'):
            if image.size == 0:
                return False, "Le fichier est vide (0 octet)"
            if image.size > 5 * 1024 * 1024:
                return False, "Taille > 5MB"

        # Optionnel : vérifier content_type indiqué par le client
        if hasattr(image, 'content_type'):
            allowed_content_types = {
                'image/jpeg', 'image/jpg', 'image/png',
                'image/webp', 'image/tiff', 'application/pdf'
            }
            if image.content_type not in allowed_content_types:
                return False, f"Type indiqué non supporté : {image.content_type}"

        return True, "OK"

    def _prepare_file(self, f):
        """
        Prépare le fichier et remet le curseur à 0
        Même implémentation que l'original
        """
        if hasattr(f, 'seek'):
            f.seek(0)
        return f.file if hasattr(f, 'file') else f

    def get_simulation_statistics(self):
        """Retourne les statistiques de la simulation"""
        return {
            **self._simulation_stats,
            "approval_rate": (self._simulation_stats["approved"] / self._simulation_stats["total_requests"] * 100 
                             if self._simulation_stats["total_requests"] > 0 else 0),
            "simulation_mode": True
        }

    def _update_simulation_stats(self, status):
        """Met à jour les statistiques de simulation"""
        # Note: Les stats sont déjà mises à jour dans _simulate_verification_decision
        pass

    def reset_simulation(self):
        """Réinitialise les statistiques de simulation"""
        self._simulation_stats = {
            "total_requests": 0,
            "approved": 0,
            "rejected": 0,
            "pending": 0
        }

# Instance globale comme dans le code original
kyc_service = DiditKYCService()

# Fonction utilitaire pour tester la simulation
def test_simulation():
    """Fonction de test pour la simulation"""
    from io import BytesIO
    
    # Créer des images simulées
    class MockImage:
        def __init__(self, name, content_type='image/jpeg', size=1024):
            self.name = name
            self.content_type = content_type
            self.size = size
            self.file = BytesIO(b"fake image data")
        
        def seek(self, pos):
            self.file.seek(pos)
    
    # Tester différentes combinaisons
    test_cases = [
        ("carte_identite.jpg", None),
        ("passeport.jpg", None),
        ("permis_conduire.jpg", "verso_permis.jpg"),
        ("carte_identite.jpg", "verso_cni.jpg"),
    ]
    
    results = []
    for front_name, back_name in test_cases:
        front = MockImage(front_name)
        back = MockImage(back_name) if back_name else None
        
        result = kyc_service.verify_id_document(
            front_image=front,
            back_image=back,
            perform_document_liveness=True,
            minimum_age=18,
            vendor_data=f"test_{front_name}"
        )
        
        results.append({
            "document": front_name,
            "success": result["success"],
            "status": result.get("status"),
            "request_id": result.get("request_id")
        })
    
    # Afficher les statistiques
    stats = kyc_service.get_simulation_statistics()
    print(f"Statistiques de simulation: {stats}")
    
    return results


if __name__ == "__main__":
    # Exemple d'utilisation
    print("Test de la simulation Didit KYC...")
    test_results = test_simulation()
    for r in test_results:
        print(f"Document: {r['document']} - Succès: {r['success']} - Statut: {r['status']}")