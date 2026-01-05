import yt_dlp
import os
import re
import requests
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, error

MP3_FOLDER = "mp3"

def sanitize_filename(name):
    illegal_chars = r'[<>:"/\\|?*]'
    return re.sub(illegal_chars, '_', name).strip()

def add_metadata(file_path, title, artist, album, cover_url):
    """Incruste l'image et les infos dans le MP3."""
    try:
        img_data = requests.get(cover_url).content
        audio = MP3(file_path, ID3=ID3)
        try:
            audio.add_tags()
        except error:
            pass

        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=artist))
        audio.tags.add(TALB(encoding=3, text=album))
        audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=img_data))
        audio.save()
        return True
    except Exception as e:
        print(f"Erreur Métadonnées : {e}")
        return False

def download_track(track_name, artist_name, track_id):
    """Télécharge la musique depuis YouTube."""
    if not os.path.exists(MP3_FOLDER):
        os.makedirs(MP3_FOLDER)

    query = f"{track_name} {artist_name} official audio"
    base_filename = f"{sanitize_filename(track_name)} - {sanitize_filename(artist_name)}"
    file_path = os.path.join(MP3_FOLDER, base_filename)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': file_path,
        'quiet': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"ytsearch1:{query}"])
        return True
    except Exception as e:
        print(f"Erreur YouTube : {e}")
        return False
