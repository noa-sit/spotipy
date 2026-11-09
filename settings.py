import json
import os

SETTINGS_PATH = 'settings.json'

DEFAULTS = {
    "mp3_folder": "mp3",            # dossier de destination des MP3
    "write_playlists": True,        # créer un .m3u8 par playlist synchronisée
    "selected_playlists": [],       # playlists cochées, retenues entre deux lancements
}


def load_settings():
    """Charge les réglages ; les clés absentes prennent leur valeur par défaut."""
    settings = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                settings.update(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            print(f"Réglages illisibles, valeurs par défaut utilisées : {e}")
    return settings


def save_settings(settings):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"Impossible d'enregistrer les réglages : {e}")
