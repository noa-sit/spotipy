import yt_dlp
import os
import re

# Définition des dossiers
MP3_FOLDER = "mp3" 

def sanitize_filename(name):
    """
    Assainit une chaîne de caractères pour qu'elle soit un nom de fichier valide.
    Remplace les caractères illégaux par des tirets bas.
    """
    # Caractères illégaux dans les noms de fichiers Windows/Unix
    illegal_chars = r'[<>:"/\\|?*]'
    return re.sub(illegal_chars, '_', name).strip()

def progress_hook(d, track_id, status_callback):
    """
    Fonction de hook appelée par yt-dlp pour fournir la progression.
    Met à jour la GUI via le status_callback.
    """
    if not status_callback:
        return

    # Mapping des statuts pour la GUI
    status_map = {
        'pre_process': ("⏳ Préparation...", 'PROCESSING'),
        'downloading': (f"🔽 Téléchargement: {d.get('percent_str', '0%')}", 'DOWNLOADING'),
        'finished': ("✨ Conversion en MP3...", 'PROCESSING'),
        'error': ("❌ Échec du téléchargement", 'FAILED')
    }
    
    # Déterminer le statut et le type d'état à afficher
    status_type = None
    
    if d['status'] == 'downloading':
        status, status_type = status_map['downloading']
    elif d['status'] == 'error':
        status, status_type = status_map['error']
    elif d['status'] == 'finished':
        # 'finished' est déclenché après le téléchargement brut, avant le post-traitement (conversion MP3)
        status, status_type = status_map['finished']
    else:
        # Autres statuts intermédiaires (comme 'extracting', 'pre_process')
        status, status_type = status_map.get(d['status'], ("⏳ En cours...", 'PROCESSING'))
    
    # Appel de la fonction de rappel de la GUI
    if status_type:
        status_callback(status, track_id, status_type)

def download_track(track_name, artist_name, track_id, output_dir=MP3_FOLDER, status_callback=None):
    """
    Télécharge un titre depuis YouTube au format MP3.

    :param track_name: Nom du morceau.
    :param artist_name: Nom de l'artiste.
    :param track_id: ID Spotify du morceau pour le suivi dans la GUI.
    :param output_dir: Dossier de sortie.
    :param status_callback: Fonction de rappel pour la mise à jour de la progression.
    :return: True en cas de succès, False en cas d'échec.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Assainir le nom de fichier pour éviter les problèmes de chemin
    safe_track_name = sanitize_filename(track_name)
    safe_artist_name = sanitize_filename(artist_name)
    
    # Format de sortie final souhaité (yt-dlp ajoutera le .mp3 final après conversion)
    base_filename = f"{safe_track_name} - {safe_artist_name}"
    
    # outtmpl est maintenant simplifié et pointe vers le chemin final. 
    # Le postprocessor d'extraction audio gère l'extension.
    outtmpl = os.path.join(output_dir, f"{base_filename}.%(ext)s")

    # Options pour yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192', # Qualité MP3 (ex: 192kbps)
        },
        # La ligne 'MoveFiles' problématique est retirée.
        {
            'key': 'FFmpegMetadata', # Pour écrire les métadonnées (optionnel mais propre)
            # Ajout du renommage des métadonnées (nom de fichier sans caractères spéciaux)
            'add_metadata': True,
        }],
        'outtmpl': outtmpl,
        'quiet': True,              # Supprimer la sortie console yt-dlp
        'noprogress': True,         # Désactiver la barre de progression par défaut
        'noplaylist': True,
        'default_search': 'ytsearch', # Chercher sur YouTube
        # Hook pour la progression en temps réel vers la GUI
        'progress_hooks': [lambda d: progress_hook(d, track_id, status_callback)],
        
        'extractor-args': 'youtube:player_client=android', 

        # NOTE: Si ffmpeg n'est pas dans votre PATH système, vous devez spécifier son emplacement.
        # 'ffmpeg_location': '/chemin/vers/votre/ffmpeg/executable', 
    }

    # Mise à jour initiale: Recherche en cours
    if status_callback:
        status_callback("🔍 Recherche du morceau...", track_id, 'PROCESSING')

    # Recherche et téléchargement
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            query = f"{track_name} {artist_name} official audio"
            # Chercher le meilleur résultat
            ydl.download([f"ytsearch:{query}"])
            
            # Vérification du fichier créé après le téléchargement et la conversion
            # yt-dlp utilise .mp3 si le codec préféré est mp3
            final_filepath = os.path.join(output_dir, f"{base_filename}.mp3")
            
            if os.path.exists(final_filepath):
                 return True
            else:
                 print(f"Avertissement: Fichier final {final_filepath} non trouvé après le téléchargement.")
                 if status_callback:
                    status_callback("❌ Fichier final manquant après la conversion", track_id, 'FAILED')
                 return False

        except yt_dlp.utils.DownloadError as e:
            print(f"Erreur de téléchargement pour {track_name} : {e}")
            if status_callback:
                status_callback("❌ Échec de la recherche/téléchargement", track_id, 'FAILED')
            return False
        except Exception as e:
            print(f"Erreur inattendue pour {track_name} : {e}")
            if status_callback:
                status_callback("❌ Erreur critique", track_id, 'FAILED')
            return False

if __name__ == "__main__":
    # Petit test de la fonction (sans callback)
    print("Test de téléchargement (vérifiez le dossier 'mp3')...")
    # Tenter de télécharger un titre simple
    success = download_track("Bohemian Rhapsody", "Queen", "test_id_queen", status_callback=None)
    print(f"Statut du test : {'Succès' if success else 'Échec'}")