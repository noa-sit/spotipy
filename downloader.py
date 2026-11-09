import glob
import os
import re
import shutil
import time
import requests
import subprocess  # Pour lancer l'exe externe
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YTDLP_EXE = os.path.join(BASE_DIR, 'yt-dlp.exe')
MP3_FOLDER = "mp3"

# Écart toléré (en secondes) entre la durée Spotify et la vidéo YouTube
DURATION_TOLERANCE = 15
# Durée max d'un téléchargement avant abandon (secondes)
DOWNLOAD_TIMEOUT = 300
# Évite qu'une fenêtre de console s'ouvre à chaque téléchargement (Windows)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _js_runtime_args():
    """YouTube exige maintenant un moteur JavaScript, sinon erreur 403 sur chaque vidéo.
    yt-dlp n'utilise que deno par défaut : on lui indique node/bun s'ils sont installés."""
    if shutil.which('deno'):
        return []
    for runtime in ('node', 'bun'):
        path = shutil.which(runtime)
        if path:
            return ['--js-runtimes', f'{runtime}:{path}']
    print("Aucun moteur JavaScript (deno, node ou bun) trouvé : "
          "YouTube risque de refuser les téléchargements.")
    return []


JS_RUNTIME_ARGS = _js_runtime_args()


def sanitize_filename(name):
    illegal_chars = r'[<>:"/\\|?*]'
    return re.sub(illegal_chars, '_', name).strip()


def add_metadata(file_path, title, artist, album, cover_url):
    """Incruste l'image et les infos dans le MP3."""
    try:
        audio = MP3(file_path, ID3=ID3)
        try:
            audio.add_tags()
        except error:
            pass

        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=artist))
        audio.tags.add(TALB(encoding=3, text=album))
        if cover_url:
            # Une pochette indisponible ne doit pas faire perdre le titre et l'artiste
            try:
                response = requests.get(cover_url, timeout=10)
                response.raise_for_status()
                audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover',
                                    data=response.content))
            except requests.RequestException as e:
                print(f"Pochette non récupérée pour {title} : {e}")
        audio.save()
        return True
    except Exception as e:
        print(f"Erreur Métadonnées : {e}")
        return False


def _remove_partial_files(file_path):
    """Efface les fichiers laissés par un téléchargement interrompu (.part, .webm, .mp3...)."""
    for f in glob.glob(glob.escape(file_path) + '.*'):
        if f.endswith('.old'):       # sauvegarde de l'ancien MP3 pendant un retéléchargement
            continue
        try:
            os.remove(f)
        except OSError:
            pass


# Versions alternatives à ne pas télécharger à la place de l'original (sauf si le titre
# Spotify les mentionne lui-même, ex. « Absurdism - Piano Part Looped »).
UNWANTED_VERSIONS = ["instrumental", "karaoke", "slowed", "sped up", "speed up", "nightcore",
                     "reverb", "8d", "loop", "looped", "1 hour", "1h", "extended", "cover",
                     "remix", "live"]
SEARCH_RESULTS = 8


def _version_filter(track_name):
    """Filtre yt-dlp qui écarte les vidéos dont le titre contient un de ces mots
    (mots entiers : « live » n'exclut pas « alive »)."""
    words = [w for w in UNWANTED_VERSIONS
             if not re.search(rf"\b{re.escape(w)}\b", track_name, re.IGNORECASE)]
    if not words:
        return None
    return r"title!~='(?i)\b(" + "|".join(words) + r")\b'"


def _run_ytdlp(command, file_path, stop_event):
    """Lance yt-dlp. Renvoie (terminé normalement, lignes d'erreur)."""
    try:
        # --quiet : seules les erreurs sortent sur stderr, le tampon ne peut pas se remplir
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                creationflags=NO_WINDOW, text=True, errors="replace")
    except Exception as e:
        return False, [f"ERROR: impossible de lancer yt-dlp : {e}"]

    # On attend la fin par petites tranches pour pouvoir réagir au bouton Stop.
    elapsed = 0.0
    while proc.poll() is None:
        if (stop_event is not None and stop_event.is_set()) or elapsed > DOWNLOAD_TIMEOUT:
            proc.kill()
            proc.wait()
            _remove_partial_files(file_path)   # un MP3 à moitié converti ne doit pas compter
            return False, []
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            elapsed += 0.5
    return True, [l for l in proc.stderr.read().splitlines() if l.startswith("ERROR")]


def download_track(track_name, artist_name, track_id, duration=0, folder=MP3_FOLDER,
                   url=None, skip=0, stop_event=None):
    """Télécharge la musique en utilisant l'exécutable yt-dlp.exe externe.

    - duration   : durée Spotify (s). Les vidéos trop différentes sont ignorées
                   (lives, compilations...), ainsi que les versions instrumentales,
                   ralenties, accélérées... qui auraient la même durée.
    - url        : lien précis (YouTube...) à télécharger au lieu de chercher.
    - skip       : nombre de résultats de recherche à sauter (pour « essayer un autre résultat »).
    - stop_event : threading.Event ; s'il est levé, le téléchargement est interrompu.
    """
    os.makedirs(folder, exist_ok=True)

    base_filename = f"{sanitize_filename(track_name)} - {sanitize_filename(artist_name)}"
    file_path = os.path.join(folder, base_filename) # yt-dlp ajoutera .mp3 tout seul
    output = [
        '-x', '--audio-format', 'mp3',
        '--audio-quality', '192K',
        '--ffmpeg-location', BASE_DIR,
        # « % » est un caractère spécial des modèles yt-dlp (titre du type « 100%(live) »)
        '-o', file_path.replace('%', '%%') + '.%(ext)s',
        '--quiet', '--no-warnings',
    ]

    if url:
        attempts = [['--no-playlist', url]]
    else:
        filters = []
        if duration > 0:
            # max(0, ...) : yt-dlp rejette les nombres négatifs (titres de moins de 15 s)
            filters.append(f'duration > {max(0, duration - DURATION_TOLERANCE)} '
                           f'& duration < {duration + DURATION_TOLERANCE}')
        version = _version_filter(track_name)
        if version:
            filters.append(version)
        search = ['--playlist-start', str(skip + 1), '--max-downloads', '1']
        if filters:
            search += ['--match-filter', ' & '.join(filters)]
        n = SEARCH_RESULTS + skip
        # 1) « titre artiste » : le plus fiable, surtout pour les petits artistes
        #    (avec « official audio », YouTube ne renvoie parfois qu'un résultat sans rapport).
        # 2) « official audio » en secours.
        attempts = [[f'ytsearch{n}:{track_name} {artist_name}', *search],
                    [f'ytsearch{n}:{track_name} {artist_name} official audio', *search]]

    errors = []
    for args in attempts:
        # Une erreur 403 de YouTube est souvent passagère : on retente une fois
        for retry in range(2):
            finished, errors = _run_ytdlp([YTDLP_EXE, *JS_RUNTIME_ARGS, *args, *output],
                                          file_path, stop_event)
            if not finished:
                return False                     # Stop ou délai dépassé
            # Pas de vérification du code retour : yt-dlp renvoie 101 quand --max-downloads
            # est atteint. Le seul vrai critère de réussite est la présence du MP3.
            if os.path.exists(f'{file_path}.mp3'):
                return True
            if not any("403" in e for e in errors):
                break
            time.sleep(2)

    if errors:
        print(f"Échec yt-dlp pour {track_name} - {artist_name} : {errors[-1]}")
    else:
        print(f"Aucun résultat YouTube correspondant pour : {track_name} - {artist_name}")
    return False
