import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# --- Configuration et Initialisation ---

# Charger les variables d'environnement depuis un fichier .env
# Ce fichier doit contenir:
# SPOTIPY_CLIENT_ID="..."
# SPOTIPY_CLIENT_SECRET="..."
# SPOTIPY_REDIRECT_URI="http://localhost:8080" (ou toute autre URL de redirection)
load_dotenv()

# Récupérer les clés depuis l'environnement
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
SPOTIPY_REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI', 'http://localhost:8080')

# Vérification des clés
if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
    print("Erreur: Les variables d'environnement SPOTIPY_CLIENT_ID et/ou SPOTIPY_CLIENT_SECRET ne sont pas définies.")
    # On assigne None à sp pour que les autres modules puissent vérifier l'échec d'initialisation
    sp = None
else:
    # --- Initialisation du Client Spotify ---
    try:
        # Création du gestionnaire d'authentification OAuth 2.0
        # Scope "user-library-read" est nécessaire pour lire la liste des titres likés
        auth_manager = SpotifyOAuth(
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET,
            redirect_uri=SPOTIPY_REDIRECT_URI,
            scope="user-library-read",
            # Vous pouvez ajouter 'cache_path' pour stocker le token d'accès
            # 'cache_path': 'spotify_token_cache.json'
        )
        
        # Initialiser le client Spotify avec l'authentification
        sp = spotipy.Spotify(auth_manager=auth_manager)
        
    except Exception as e:
        print(f"Erreur lors de l'initialisation du client Spotify : {e}")
        sp = None # Échec de l'initialisation

# --- Fonction de Test ---

def test_connection():
    """Tente de récupérer les informations de l'utilisateur pour vérifier la connexion."""
    if sp is None:
        print("La connexion Spotify n'a pas pu être établie. Vérifiez les clés d'API.")
        return

    try:
        user = sp.current_user()
        print(f"✅ Connexion Spotify réussie. Connecté en tant que : {user['display_name']}")
    except Exception as e:
        print(f"❌ Erreur de connexion / d'authentification : {e}")
        print("Assurez-vous d'avoir complété le processus d'authentification (ouvrir l'URL de redirection dans votre navigateur si nécessaire).")

if __name__ == "__main__":
    # Ceci exécutera le processus d'authentification et affichera les messages
    test_connection()