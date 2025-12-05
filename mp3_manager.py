import os
import sqlite3
# import eyed3 # N'est pas strictement nécessaire pour la gestion DB/Fichiers, mais utile si on veut éditer les tags plus tard.

DB_PATH = 'tracks.db'

def init_db():
    """Initialise la base de données SQLite et crée la table pour les titres téléchargés."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS downloaded_tracks
                     (track_id TEXT PRIMARY KEY, 
                      track_name TEXT, 
                      artist_name TEXT)''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de l'initialisation de la DB : {e}")
    finally:
        if conn:
            conn.close()

def save_downloaded_track(track_id, track_name, artist_name):
    """Enregistre un titre dans la base de données après un téléchargement réussi."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # INSERT OR IGNORE permet d'éviter les doublons si le titre existe déjà
        c.execute("INSERT OR IGNORE INTO downloaded_tracks VALUES (?, ?, ?)", (track_id, track_name, artist_name))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de la sauvegarde : {e}")
    finally:
        if conn:
            conn.close()

def is_track_in_db(track_id):
    """Vérifie si un titre Spotify (par son ID) est déjà dans la base de données locale."""
    exists = False
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT 1 FROM downloaded_tracks WHERE track_id = ?", (track_id,))
        exists = c.fetchone() is not None
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de la vérification : {e}")
    finally:
        if conn:
            conn.close()
    return exists

def get_downloaded_tracks():
    """Récupère tous les titres téléchargés depuis la base de données."""
    downloaded_tracks = []
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Retourne les données importantes pour l'affichage et la comparaison
        c.execute("SELECT track_id, track_name, artist_name FROM downloaded_tracks")
        downloaded_tracks = c.fetchall()
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de la récupération : {e}")
    finally:
        if conn:
            conn.close()
    return downloaded_tracks

def delete_removed_tracks(current_liked_track_ids, mp3_folder="mp3"):
    """
    Supprime les titres de la DB et du dossier MP3 s'ils ne sont plus
    dans la liste 'current_liked_track_ids' de Spotify.
    Retourne le nombre d'éléments supprimés.
    """
    deleted_count = 0
    tracks_to_delete = []

    # 1. Identifier les titres à supprimer
    downloaded_tracks = get_downloaded_tracks()
    for track_id, track_name, artist_name in downloaded_tracks:
        if track_id not in current_liked_track_ids:
            tracks_to_delete.append((track_id, track_name, artist_name))
    
    if not tracks_to_delete:
        return 0

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        for track_id, track_name, artist_name in tracks_to_delete:
            
            # 2. Tenter de supprimer le fichier MP3
            # Construction du nom de fichier basée sur le format utilisé dans downloader.py
            # On cherche tous les fichiers qui pourraient correspondre (e.g., .mp3, .m4a)
            # Puisqu'on ne connaît pas l'extension exacte après le téléchargement, on va utiliser la convention
            # du nom complet pour la suppression, en supposant l'extension .mp3 par défaut.
            
            # NOTE: Le nom du fichier généré par yt-dlp dans 'downloader.py' est : 
            # f"{track_name} - {artist_name}.mp3"
            filename = f"{track_name} - {artist_name}.mp3"
            filepath = os.path.join(mp3_folder, filename)

            if os.path.exists(filepath):
                os.remove(filepath)
                # print(f"Fichier supprimé : {filepath}")
            else:
                 # Le fichier n'existe plus ou n'a pas été renommé correctement, on continue la suppression DB
                 print(f"Avertissement : Fichier MP3 non trouvé à l'emplacement attendu : {filepath}")

            # 3. Supprimer l'entrée de la base de données
            c.execute("DELETE FROM downloaded_tracks WHERE track_id = ?", (track_id,))
            deleted_count += 1
            
        conn.commit()
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de la suppression : {e}")
    except OSError as e:
        print(f"Erreur OS lors de la suppression du fichier : {e}")
    finally:
        if conn:
            conn.close()
            
    return deleted_count

if __name__ == "__main__":
    # Petit test de vérification des fonctions de base
    init_db()
    
    test_id = "test_id_123"
    test_name = "Test Song"
    test_artist = "Test Artist"
    
    print(f"Est-ce que '{test_name}' est dans la DB ? {is_track_in_db(test_id)}")
    save_downloaded_track(test_id, test_name, test_artist)
    print(f"Est-ce que '{test_name}' est dans la DB après sauvegarde ? {is_track_in_db(test_id)}")
    
    tracks = get_downloaded_tracks()
    print(f"Titres téléchargés (total) : {len(tracks)}")
    
    # Simuler la suppression (si l'ID est dans les titres téléchargés)
    # print(f"Titres supprimés (si existant) : {delete_removed_tracks(set(), mp3_folder='.')}")