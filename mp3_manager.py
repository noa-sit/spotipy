import os
import sqlite3
from contextlib import closing

from downloader import sanitize_filename, MP3_FOLDER

DB_PATH = 'tracks.db'


def _connect():
    """Ouvre une connexion qui se ferme toute seule (avec `with`).
    Le timeout évite les erreurs « database is locked » quand plusieurs threads écrivent."""
    return closing(sqlite3.connect(DB_PATH, timeout=10))


def track_filepath(track_name, artist_name, mp3_folder=MP3_FOLDER):
    """Chemin du MP3, construit exactement comme dans downloader.py."""
    filename = f"{sanitize_filename(track_name)} - {sanitize_filename(artist_name)}.mp3"
    return os.path.join(mp3_folder, filename)


def init_db():
    """Initialise la base de données SQLite et crée la table pour les titres téléchargés."""
    try:
        with _connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS downloaded_tracks
                            (track_id TEXT PRIMARY KEY,
                             track_name TEXT,
                             artist_name TEXT)''')
            conn.commit()
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de l'initialisation de la DB : {e}")


def is_db_writable():
    """Faux si tracks.db est en lecture seule (attribut Windows) : rien ne pourrait être enregistré."""
    return not os.path.exists(DB_PATH) or os.access(DB_PATH, os.W_OK)


def save_downloaded_track(track_id, track_name, artist_name):
    """Enregistre un titre dans la base de données après un téléchargement réussi.
    Retourne False si l'enregistrement a échoué."""
    try:
        with _connect() as conn:
            # INSERT OR IGNORE permet d'éviter les doublons si le titre existe déjà
            conn.execute("INSERT OR IGNORE INTO downloaded_tracks VALUES (?, ?, ?)",
                         (track_id, track_name, artist_name))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de la sauvegarde : {e}")
        return False


def is_track_in_db(track_id):
    """Vérifie si un titre Spotify (par son ID) est déjà dans la base de données locale."""
    try:
        with _connect() as conn:
            row = conn.execute("SELECT 1 FROM downloaded_tracks WHERE track_id = ?",
                               (track_id,)).fetchone()
            return row is not None
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de la vérification : {e}")
        return False


def get_downloaded_tracks():
    """Récupère tous les titres téléchargés depuis la base de données."""
    try:
        with _connect() as conn:
            return conn.execute(
                "SELECT track_id, track_name, artist_name FROM downloaded_tracks").fetchall()
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de la récupération : {e}")
        return []


def get_tracks_to_delete(current_track_ids):
    """Liste les titres téléchargés qui ne sont plus dans `current_track_ids`.
    Ne supprime rien : sert à demander confirmation avant `delete_tracks`."""
    current = set(current_track_ids)
    return [t for t in get_downloaded_tracks() if t[0] not in current]


def delete_tracks(tracks, mp3_folder=MP3_FOLDER):
    """Supprime les titres donnés (tuples id, nom, artiste) du disque et de la DB.
    Retourne le nombre d'éléments supprimés."""
    deleted_count = 0
    try:
        with _connect() as conn:
            for track_id, track_name, artist_name in tracks:
                filepath = track_filepath(track_name, artist_name, mp3_folder)
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    else:
                        print(f"Avertissement : MP3 introuvable : {filepath}")
                except OSError as e:
                    # Fichier verrouillé (ouvert dans un lecteur...) : on le garde en DB
                    print(f"Erreur OS lors de la suppression de {filepath} : {e}")
                    continue
                conn.execute("DELETE FROM downloaded_tracks WHERE track_id = ?", (track_id,))
                deleted_count += 1
            conn.commit()
    except sqlite3.Error as e:
        print(f"Erreur SQLite lors de la suppression : {e}")
    return deleted_count


def write_m3u(playlist_name, tracks, mp3_folder=MP3_FOLDER):
    """Écrit `<playlist_name>.m3u8` dans le dossier des MP3, avec les titres présents
    sur le disque. Les chemins sont relatifs : le dossier peut être copié tel quel
    sur un téléphone ou une clé USB. Retourne le nombre de titres écrits."""
    lines = ["#EXTM3U"]
    for t in tracks:
        path = track_filepath(t['name'], t['artist'], mp3_folder)
        if os.path.exists(path):
            lines.append(f"#EXTINF:{t.get('duration', 0) or -1},{t['artist']} - {t['name']}")
            lines.append(os.path.basename(path))
    m3u_path = os.path.join(mp3_folder, f"{sanitize_filename(playlist_name)}.m3u8")
    try:
        with open(m3u_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"Impossible d'écrire {m3u_path} : {e}")
        return 0
    return (len(lines) - 1) // 2


def delete_removed_tracks(current_track_ids, mp3_folder=MP3_FOLDER):
    """Supprime sans confirmation les titres qui ne sont plus dans `current_track_ids`."""
    return delete_tracks(get_tracks_to_delete(current_track_ids), mp3_folder)


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
