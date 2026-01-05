import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

ENV_PATH = '.env'
CACHE_PATH = '.cache'

def initialize_spotify():
    """Charge le .env et configure l'authentification."""
    load_dotenv(ENV_PATH, override=True)
    
    client_id = os.getenv('SPOTIPY_CLIENT_ID')
    client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
    redirect_uri = os.getenv('SPOTIPY_REDIRECT_URI', 'http://127.0.0.1:8080/callback')

    if not client_id or not client_secret or "VOTRE_CLIENT_ID" in client_id:
        return None

    try:
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="user-library-read",
            open_browser=True,
            cache_path=CACHE_PATH
        )
        return spotipy.Spotify(auth_manager=auth_manager)
    except Exception as e:
        print(f"Erreur d'initialisation Spotify : {e}")
        return None

# Instance globale pour l'app
sp = initialize_spotify()

def save_credentials(client_id, client_secret):
    """Enregistre les clés et réinitialise la connexion."""
    global sp
    if os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)
        
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(f'SPOTIPY_CLIENT_ID="{client_id}"\n')
        f.write(f'SPOTIPY_CLIENT_SECRET="{client_secret}"\n')
        f.write(f'SPOTIPY_REDIRECT_URI="http://127.0.0.1:8080/callback"\n')
    
    sp = initialize_spotify()
    return sp
