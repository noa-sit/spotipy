import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from threading import Thread
import zipfile
import os 
import http.server
import socketserver 
import socket 

# Importations des modules locaux
# Assurez-vous que tous ces fichiers sont présents et à jour (spotify_auth.py, spotify_liked_tracks.py, etc.)
from spotify_auth import sp 
from spotify_liked_tracks import get_all_liked_tracks
from mp3_manager import init_db, is_track_in_db, delete_removed_tracks, save_downloaded_track, get_downloaded_tracks
# NOTE: Le fichier downloader.py doit être mis à jour pour accepter status_callback
from downloader import download_track

# Définition des couleurs style Spotify pour le thème sombre
COLOR_DARK_BG = '#121212'   
COLOR_MEDIUM_BG = '#282828' 
COLOR_SPOTIFY_GREEN = '#1DB954'
COLOR_TEXT_WHITE = '#FFFFFF'
COLOR_TEXT_LIGHT = '#B3B3B3' 
COLOR_ERROR_RED = '#FF4500'

# Configuration des dossiers
MP3_FOLDER = "mp3" 
ZIP_FOLDER = "zip_export" # Dossier temporaire pour le ZIP
ZIP_FILENAME = "spotify_mp3_export.zip"
SERVER_PORT = 8000
SERVER_HOST = '0.0.0.0' # Écoute sur toutes les interfaces
SERVER_URL = None 

# --- Serveur HTTP pour Partage Local ---

class FileHandler(http.server.SimpleHTTPRequestHandler):
    """
    Gère les requêtes HTTP en servant les fichiers depuis le répertoire courant (racine de l'application).
    Ceci permet de servir à la fois le dossier 'mp3' et le dossier 'zip_export'.
    """
    def __init__(self, *args, **kwargs):
        # Permet de servir les fichiers depuis le CWD (Current Working Directory)
        super().__init__(*args, directory=os.getcwd(), **kwargs)
        
    def log_message(self, format, *args):
        # Supprime le log par défaut des requêtes HTTP pour garder la console propre
        pass

# --- Application GUI ---

class SpotifySyncApp(tk.Tk):
    """Application GUI pour la synchronisation des morceaux likés de Spotify."""

    def __init__(self):
        super().__init__()
        self.title("Spotify MP3 Sync Tool")
        self.geometry("1000x650") 
        self.tracks_status = {}
        self.server_thread = None
        self.httpd = None
        self.is_sync_running = False
        self.is_zip_ready = False
        
        # Configuration du style et initialisation de la DB
        self._setup_style()
        init_db()
        self.create_widgets()
        self.load_initial_tracks()
        self._setup_folders()

        # Gestion de la fermeture de l'application
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_style(self):
        """Configure le thème sombre Tkinter."""
        style = ttk.Style(self)
        style.theme_use('clam')
        self.configure(bg=COLOR_DARK_BG) 
        
        style.configure('Dark.TFrame', background=COLOR_DARK_BG)
        style.configure('Dark.TLabel', background=COLOR_DARK_BG, foreground=COLOR_TEXT_WHITE, font=('Arial', 10))
        style.configure('Status.TLabel', background=COLOR_DARK_BG, foreground=COLOR_TEXT_LIGHT, font=('Arial', 10, 'italic'))
        
        # Bouton principal (Sync)
        style.configure('Spotify.TButton', font=('Arial', 11, 'bold'), background=COLOR_SPOTIFY_GREEN, foreground=COLOR_DARK_BG, padding=[15, 8], borderwidth=0)
        style.map('Spotify.TButton', background=[('active', COLOR_SPOTIFY_GREEN)]) 
        
        # Boutons secondaires (Export/Share)
        style.configure('Export.TButton', font=('Arial', 10, 'bold'), background=COLOR_MEDIUM_BG, foreground=COLOR_TEXT_WHITE, padding=[10, 8], borderwidth=0)
        style.map('Export.TButton', background=[('active', COLOR_DARK_BG)])
        
        # Treeview (Liste des titres)
        style.configure('Dark.Treeview', background=COLOR_MEDIUM_BG, fieldbackground=COLOR_MEDIUM_BG, foreground=COLOR_TEXT_WHITE, rowheight=30, borderwidth=0, font=('Arial', 10))
        style.configure('Dark.Treeview.Heading', background=COLOR_DARK_BG, foreground=COLOR_TEXT_LIGHT, font=('Arial', 10, 'bold'))
        style.configure('Dark.Vertical.TScrollbar', background=COLOR_MEDIUM_BG, troughcolor=COLOR_DARK_BG)
        
    def _setup_folders(self):
        """Crée les dossiers mp3 et zip_export s'ils n'existent pas."""
        if not os.path.exists(MP3_FOLDER):
            os.makedirs(MP3_FOLDER)
        if not os.path.exists(ZIP_FOLDER):
            os.makedirs(ZIP_FOLDER)
        
    def create_widgets(self):
        """Crée tous les éléments de l'interface graphique."""
        
        # --- Frame des Boutons ---
        button_frame = ttk.Frame(self, padding="20 15 20 15", style='Dark.TFrame')
        button_frame.pack(side=tk.TOP, fill=tk.X)

        app_title = ttk.Label(button_frame, text="Spotify MP3 Sync Tool", font=('Arial', 18, 'bold'), foreground=COLOR_SPOTIFY_GREEN, background=COLOR_DARK_BG, style='Dark.TLabel')
        app_title.pack(side=tk.LEFT, padx=10)

        self.sync_button = ttk.Button(button_frame, text="▶ Démarrer la Synchronisation", command=self.start_sync_thread, style='Spotify.TButton')
        self.sync_button.pack(side=tk.RIGHT, padx=5)

        # Bouton Exporter/Créer ZIP pour le partage
        self.export_button = ttk.Button(button_frame, text="📦 Préparer ZIP Partage", command=self.create_zip_for_sharing, style='Export.TButton')
        self.export_button.pack(side=tk.RIGHT, padx=15)
        
        self.share_button = ttk.Button(button_frame, text="🌐 Activer Partage Local", command=self.toggle_server, style='Export.TButton')
        self.share_button.pack(side=tk.RIGHT, padx=15)

        self.status_label = ttk.Label(button_frame, text="Statut : Prêt", foreground=COLOR_TEXT_LIGHT, style='Status.TLabel')
        self.status_label.pack(side=tk.RIGHT, padx=20)
        
        # --- Treeview (Liste des titres) ---
        tree_frame = ttk.Frame(self, style='Dark.TFrame')
        tree_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        columns = ("ID", "Artiste", "Titre", "Statut")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", style='Dark.Treeview')

        self.tree.heading("Artiste", text="Artiste", anchor=tk.W)
        self.tree.heading("Titre", text="Titre", anchor=tk.W)
        self.tree.heading("Statut", text="Statut", anchor=tk.CENTER)
        self.tree.heading("ID", text="ID Spotify", anchor=tk.CENTER)
        self.tree.column("Artiste", width=250, anchor=tk.W, stretch=tk.YES)
        self.tree.column("Titre", width=350, anchor=tk.W, stretch=tk.YES)
        self.tree.column("Statut", width=180, anchor=tk.CENTER, stretch=tk.NO)
        self.tree.column("ID", width=0, stretch=tk.NO) # Colonne masquée pour l'ID
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview, style='Dark.Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def load_initial_tracks(self):
        """Charge et affiche les titres déjà présents en local."""
        downloaded_tracks = get_downloaded_tracks()
        for track_id, track_name, artist_name in downloaded_tracks:
            self.tracks_status[track_id] = {
                'name': track_name,
                'artist': artist_name,
                'status': "✅ Téléchargé"
            }
            # Insère l'élément et lui donne un tag pour la couleur
            self.tree.insert("", "end", iid=track_id, 
                             values=(track_id, artist_name, track_name, "✅ Téléchargé"), tags=('completed_initial',))

        # Configuration des tags visuels
        self.tree.tag_configure('completed_initial', background=COLOR_MEDIUM_BG, foreground=COLOR_TEXT_LIGHT)
        self.tree.tag_configure('completed', foreground=COLOR_SPOTIFY_GREEN)
        self.tree.tag_configure('downloading', foreground='#1E90FF') 
        self.tree.tag_configure('processing', foreground='#FFD700') 
        self.tree.tag_configure('failed', foreground=COLOR_ERROR_RED) 
        self.tree.tag_configure('pending', foreground=COLOR_TEXT_LIGHT) 

        self.status_label.config(text=f"Statut : {len(downloaded_tracks)} titres locaux chargés. Prêt.")

    def update_track_status(self, message, track_id, status_type):
        """Callback pour mettre à jour l'état d'un titre depuis le thread de téléchargement."""
        if track_id in self.tracks_status:
            self.tracks_status[track_id]['status'] = message
            # Utilise self.after(0, ...) pour s'assurer que l'action est exécutée dans le thread GUI
            self.after(0, self._update_treeview_item, track_id, message, status_type)

    def _update_treeview_item(self, track_id, status_message, status_type):
        """Mise à jour de l'élément Treeview dans le thread GUI."""
        tag = status_type.lower()
        
        if self.tree.exists(track_id):
            # Mise à jour de l'élément existant
            current_values = list(self.tree.item(track_id, 'values'))
            current_values[3] = status_message
            self.tree.item(track_id, values=tuple(current_values), tags=(tag,))
        else:
            # Insertion d'un nouvel élément
            if track_id in self.tracks_status:
                track = self.tracks_status[track_id]
                self.tree.insert("", "end", iid=track_id, 
                                 values=(track_id, track['artist'], track['name'], status_message),
                                 tags=(tag,))
                self.tree.see(track_id) # Défilement vers le nouvel élément
                
    def sync_logic(self):
        """Logique de synchronisation principale."""
        self.is_sync_running = True
        self.after(0, self.status_label.config, {'text': "Statut : Récupération des titres Spotify...", 'foreground': '#FFD700'})
        self.after(0, self.sync_button.config, {'state': tk.DISABLED, 'text': "Synchronisation en cours..."})
        self.after(0, self.export_button.config, {'state': tk.DISABLED})
        self.after(0, self.share_button.config, {'state': tk.DISABLED})

        try:
            # Récupérer la liste complète des titres likés
            tracks = get_all_liked_tracks()
            current_liked_track_ids = {track['id'] for track in tracks}
            self.after(0, self.status_label.config, {'text': f"Statut : {len(tracks)} titres likés trouvés.", 'foreground': COLOR_TEXT_WHITE})
            
            # Supprimer les titres locaux qui ne sont plus likés sur Spotify
            # NOTE: delete_removed_tracks doit ABSOLUMENT retourner un INTEGER. 
            # C'est la correction effectuée dans mp3_manager.py
            deleted_count = delete_removed_tracks(current_liked_track_ids, mp3_folder=MP3_FOLDER)
            if deleted_count > 0:
                 self.after(0, self.status_label.config, {'text': f"Statut : {deleted_count} titres supprimés. Recherche de nouveaux...", 'foreground': COLOR_ERROR_RED})

            # Filtrer les nouveaux titres à télécharger
            new_tracks_to_download = [track for track in tracks if not is_track_in_db(track['id'])]
            self.after(0, self.status_label.config, {'text': f"Statut : {len(new_tracks_to_download)} nouveaux titres à télécharger."})

            for track in new_tracks_to_download:
                track_id = track['id']
                # Pré-insérer le titre dans la vue
                self.tracks_status[track_id] = {'name': track['name'], 'artist': track['artist'], 'status': "⏳ En attente"}
                self._update_treeview_item(track_id, "⏳ En attente", 'PENDING')
                
                # Téléchargement (appel à la fonction qui gère le yt-dlp)
                success = download_track(
                    track_name=track['name'], 
                    artist_name=track['artist'], 
                    track_id=track_id, # Passer l'ID pour le hook de progression
                    output_dir=MP3_FOLDER,
                    status_callback=self.update_track_status
                )
                
                if success:
                    save_downloaded_track(track_id, track['name'], track['artist'])
                    final_msg = "✅ Téléchargé"
                    final_status_type = 'COMPLETED'
                else:
                    final_msg = "❌ Échec du téléchargement"
                    final_status_type = 'FAILED'

                self.update_track_status(final_msg, track_id, final_status_type)

        except Exception as e:
            error_message = f"Une erreur critique est survenue : {e}"
            print(error_message)
            self.after(0, self.status_label.config, {'text': f"Statut : ERREUR ({e.__class__.__name__})", 'foreground': COLOR_ERROR_RED})

        finally:
            self.after(0, self.sync_button.config, {'state': tk.NORMAL, 'text': "▶ Démarrer la Synchronisation"})
            self.after(0, self.export_button.config, {'state': tk.NORMAL})
            self.after(0, self.share_button.config, {'state': tk.NORMAL})
            self.after(0, self.status_label.config, {'text': "Statut : Synchronisation terminée.", 'foreground': COLOR_SPOTIFY_GREEN})
            self.is_sync_running = False

    def start_sync_thread(self):
        """Démarre la logique de synchronisation dans un thread séparé."""
        if not self.is_sync_running:
            # S'assurer que le client Spotify est disponible
            if not sp:
                 messagebox.showerror("Erreur Spotify", "Le client Spotify n'est pas initialisé. Vérifiez vos clés dans le fichier .env.")
                 return
                 
            self.sync_thread = Thread(target=self.sync_logic)
            self.sync_thread.daemon = True
            self.sync_thread.start()

    def create_zip_for_sharing(self):
        """Démarre le processus de création ZIP dans le dossier temporaire ZIP_FOLDER."""
        zip_filepath = os.path.join(ZIP_FOLDER, ZIP_FILENAME)

        Thread(target=self._zip_worker, args=(zip_filepath,)).start()
        
    def _zip_worker(self, zip_filepath):
        """Tâche de compression exécutée dans un thread séparé."""
        
        self.after(0, self.export_button.config, {'state': tk.DISABLED, 'text': "📦 Création ZIP en cours..."})
        self.after(0, self.status_label.config, {'text': "Statut : Préparation de l'export ZIP...", 'foreground': '#FFD700'})
        self.is_zip_ready = False
        
        # Supprimer l'ancien ZIP s'il existe
        if os.path.exists(zip_filepath):
             os.remove(zip_filepath)

        try:
            # Récupère uniquement les fichiers .mp3 du dossier
            mp3_files = [os.path.join(MP3_FOLDER, f) for f in os.listdir(MP3_FOLDER) if f.endswith('.mp3')]
            
            if not mp3_files:
                self.after(0, lambda: messagebox.showwarning("Export ZIP", "Aucun fichier MP3 trouvé."))
                return

            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in mp3_files:
                    # Stocker le fichier avec son nom de base (sans le chemin complet)
                    zipf.write(file_path, os.path.basename(file_path))
            
            self.is_zip_ready = True
            
            # Message de confirmation
            confirm_msg = f"ZIP ({os.path.basename(zip_filepath)}) prêt au partage ({len(mp3_files)} fichiers)"
            self.after(0, self.status_label.config, {'text': f"Statut : {confirm_msg}", 'foreground': COLOR_SPOTIFY_GREEN})
            self.after(0, lambda: messagebox.showinfo("Export ZIP Terminé", 
                                                      f"Le fichier ZIP a été créé avec succès et est prêt à être partagé localement. \n\nCliquez sur 'Activer Partage Local' pour le rendre accessible."))


        except Exception as e:
            self.after(0, self.status_label.config, {'text': "Statut : Échec de l'export ZIP.", 'foreground': COLOR_ERROR_RED})
            self.after(0, lambda: messagebox.showerror("Erreur ZIP", f"Erreur : {e}"))

        finally:
            self.after(0, self.export_button.config, {'state': tk.NORMAL, 'text': "📦 Préparer ZIP Partage"})
            
    # --- LOGIQUE DU SERVEUR HTTP ---

    def get_local_ip(self):
        """Tente d'obtenir l'adresse IP locale."""
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Tenter de se connecter à une adresse externe pour trouver l'interface active
            s.connect(("8.8.8.8", 80)) 
            ip_address = s.getsockname()[0]
            return ip_address
        except Exception:
            return "127.0.0.1" # Fallback si aucune connexion externe n'est possible
        finally:
            if s: s.close()

    def start_server(self):
        """Démarre le serveur HTTP dans un thread séparé."""
        if self.httpd: return 

        if not os.path.exists(MP3_FOLDER) or not os.listdir(MP3_FOLDER):
            self.after(0, lambda: messagebox.showwarning("Partage Local", "Le dossier MP3 est vide ou n'existe pas. Veuillez d'abord télécharger des morceaux."))
            return

        # Le serveur est démarré depuis la racine de l'application (os.getcwd())
        # pour permettre l'accès aux dossiers /mp3 et /zip_export.
        
        try:
            Handler = FileHandler
            # TCPServer peut lever des exceptions si le port est déjà utilisé
            self.httpd = socketserver.TCPServer((SERVER_HOST, SERVER_PORT), Handler, bind_and_activate=False)
            self.httpd.allow_reuse_address = True
            self.httpd.server_bind()
            self.httpd.server_activate()

            local_ip = self.get_local_ip()
            global SERVER_URL
            SERVER_URL = f"http://{local_ip}:{SERVER_PORT}"
            ZIP_URL = f"{SERVER_URL}/{ZIP_FOLDER}/{ZIP_FILENAME}" # Lien direct vers le ZIP
            
            self.server_thread = Thread(target=self.httpd.serve_forever, daemon=True)
            self.server_thread.start()
            
            # Affichage du statut avec le lien du ZIP
            self.after(0, self.status_label.config, {'text': f"Partage Actif : {SERVER_URL}", 'foreground': COLOR_SPOTIFY_GREEN})
            self.after(0, self.share_button.config, {'text': "❌ Arrêter Partage Local", 'style': 'Spotify.TButton'})
            
            message = (
                "Partage en cours ! Ouvrez cette adresse dans le navigateur de votre téléphone (sur le même réseau Wi-Fi) :\n\n"
                f"Lien de la page d'index (dossiers MP3 & ZIP) : {SERVER_URL}\n\n"
            )
            
            if self.is_zip_ready:
                 message += f"Lien de TÉLÉCHARGEMENT DIRECT du ZIP: \n{ZIP_URL}"
            else:
                 message += "Le fichier ZIP n'a pas été préparé. Cliquez sur 'Préparer ZIP Partage' d'abord."

            self.after(0, lambda: messagebox.showinfo("Partage Local Actif", message))

        except Exception as e:
            if self.httpd:
                self.httpd.server_close()
                self.httpd = None
            
            error_message = f"Erreur de serveur : Le port {SERVER_PORT} est peut-être déjà utilisé ou bloqué. Assurez-vous d'avoir les permissions nécessaires."
            self.after(0, self.status_label.config, {'text': "Statut : Erreur de Partage.", 'foreground': COLOR_ERROR_RED})
            self.after(0, lambda: messagebox.showerror("Erreur Serveur", error_message + f" ({e.__class__.__name__})"))


    def stop_server(self):
        """Arrête le serveur HTTP."""
        if self.httpd:
            # Arrêter le thread du serveur
            self.httpd.shutdown() 
            self.httpd.server_close()
            self.httpd = None
            
            self.status_label.config(text="Statut : Partage Arrêté. Prêt.", foreground=COLOR_TEXT_LIGHT)
            self.share_button.config(text="🌐 Activer Partage Local", style='Export.TButton')
            print("Serveur HTTP arrêté.")

    def toggle_server(self):
        """Bascule entre le démarrage et l'arrêt du serveur."""
        if self.httpd:
            self.stop_server()
        else:
            self.start_server()

    def on_closing(self):
        """Gestionnaire d'événements lors de la tentative de fermeture de l'application."""
        if self.is_sync_running:
            messagebox.showwarning("Fermeture", "La synchronisation est en cours. Veuillez attendre.")
            return

        if self.httpd:
            self.stop_server()
        
        # Nettoyage du dossier ZIP temporaire lors de la fermeture (Optionnel mais propre)
        try:
            zip_file_path = os.path.join(ZIP_FOLDER, ZIP_FILENAME)
            if os.path.exists(zip_file_path):
                os.remove(zip_file_path)
        except Exception:
            pass 
            
        self.destroy()

if __name__ == "__main__":
    app = SpotifySyncApp()
    app.mainloop()