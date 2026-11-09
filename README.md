# 🎵 Spotify MP3 Sync

> **Synchronisez automatiquement vos “Titres Likés” Spotify en fichiers MP3 locaux**

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Spotify API](https://img.shields.io/badge/Spotify-API-green)
![yt-dlp](https://img.shields.io/badge/yt--dlp-Downloader-orange)
![License](https://img.shields.io/badge/License-Non--spécifiée-lightgrey)

Un script Python qui synchronise un dossier local `mp3/` avec votre playlist **Titres Likés (Liked Songs)** de Spotify : il télécharge les nouveaux morceaux (via YouTube + `yt-dlp`) et supprime les MP3 des morceaux que vous avez retirés de vos Likes.

---

## ✨ Fonctionnalités

* Authentification OAuth2 avec l'API Spotify (Spotipy)
* Récupération complète des `Liked Songs`
* Téléchargement automatique des nouveaux titres (YouTube → `yt-dlp` → MP3)
* Nettoyage des MP3 locaux pour les morceaux délikés
* Base locale SQLite (`tracks.db`) pour suivre l'état des fichiers

---

## 📦 Prérequis

* Python 3.8+
* FFmpeg (présent dans le `PATH`)

### Dépendances Python

```bash
uv sync
```

---

## 🔧 Configuration Spotify

1. Ouvrez le **Spotify Developer Dashboard** et créez une application.
2. Dans *Edit Settings*, ajoutez l'URI de redirection :

```
http://127.0.0.1:8080/callback
```

3. Récupérez `Client ID` et `Client Secret`.

### Fichier `.env` (à la racine)

Créez un fichier `.env` contenant :

```env
SPOTIPY_CLIENT_ID="VOTRE_CLIENT_ID_SPOTIFY"
SPOTIPY_CLIENT_SECRET="VOTRE_CLIENT_SECRET_SPOTIFY"
SPOTIPY_REDIRECT_URI="http://127.0.0.1:8080/callback"
```
---

## ▶️ Utilisation

### Première exécution (authentification)

```bash
python main.py
```

La première fois, un navigateur s'ouvrira pour autoriser l'application. Le token est sauvegardé automatiquement.

### Synchronisation

Relancez `main.py` pour lancer la synchronisation complète (récupération, téléchargement et nettoyage) :

```bash
python main.py
```

---

## 🗂 Structure du projet

```
Spotify-MP3-Sync/
├── main.py
├── mp3_manager.py
├── downloader.py
├── spotify_auth.py
├── spotify_liked_tracks.py
├── .env
├── mp3/              
└── tracks.db          
```
