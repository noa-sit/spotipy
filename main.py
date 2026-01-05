import customtkinter as ctk
from tkinter import ttk, messagebox
import webbrowser
from threading import Thread
import os
from concurrent.futures import ThreadPoolExecutor

import spotify_auth
from spotify_liked_tracks import get_all_liked_tracks
from mp3_manager import init_db, is_track_in_db, delete_removed_tracks, save_downloaded_track
from downloader import download_track, add_metadata, sanitize_filename

# Configuration du thème
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green") 

class SpotifySyncApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Spotify Sync Pro - Turbo Edition")
        self.geometry("1000x800")
        self.is_sync_running = False
        
        init_db()
        self.create_widgets()

        if spotify_auth.sp is None:
            self.after(500, self.show_setup_dialog)
        else:
            self.update_status("Prêt", "#1DB954")

    def create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- HEADER ---
        self.header_label = ctk.CTkLabel(self, text="Spotify Music Downloader", font=("Impact", 35))
        self.header_label.grid(row=0, column=0, pady=(30, 5))

        self.status_label = ctk.CTkLabel(self, text="Statut : Prêt", text_color="gray", font=("Arial", 15))
        self.status_label.grid(row=1, column=0, pady=(0, 20))

        # --- TABLEAU (TREEVIEW STYLE) ---
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", 
                        background="#1a1a1a", 
                        foreground="white", 
                        fieldbackground="#1a1a1a", 
                        borderwidth=0, 
                        rowheight=40,
                        font=("Arial", 11))
        style.configure("Treeview.Heading", background="#2b2b2b", foreground="white", relief="flat", font=("Arial", 12, "bold"))
        style.map("Treeview", background=[('selected', '#1DB954')])

        self.tree_frame = ctk.CTkFrame(self, fg_color="#1a1a1a", corner_radius=15)
        self.tree_frame.grid(row=2, column=0, padx=30, sticky="nsew")
        
        self.tree = ttk.Treeview(self.tree_frame, columns=("titre", "artiste", "statut"), show="headings")
        self.tree.heading("titre", text="TITRE")
        self.tree.heading("artiste", text="ARTISTE")
        self.tree.heading("statut", text="ÉTAT")
        
        self.tree.column("titre", width=400)
        self.tree.column("artiste", width=250)
        self.tree.column("statut", width=150, anchor="center")
        
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        # --- ZONE DES BOUTONS ---
        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.grid(row=3, column=0, pady=30, padx=30, sticky="ew")
        self.btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # Bouton Sync Total
        self.sync_btn = ctk.CTkButton(self.btn_frame, text="🚀 TOUT SYNCHRONISER", 
                                      font=("Arial", 16, "bold"), height=55, 
                                      corner_radius=28, command=self.start_sync_thread)
        self.sync_btn.grid(row=0, column=0, padx=10, sticky="ew")

        # Bouton Retry (Échecs)
        self.retry_btn = ctk.CTkButton(self.btn_frame, text="🔄 RÉESSAYER ÉCHECS", 
                                       fg_color="#E74C3C", hover_color="#C0392B",
                                       font=("Arial", 16, "bold"), height=55, 
                                       corner_radius=28, command=self.start_retry_thread)
        self.retry_btn.grid(row=0, column=1, padx=10, sticky="ew")

        # Bouton Config
        self.config_btn = ctk.CTkButton(self.btn_frame, text="⚙️ CONFIG", 
                                        fg_color="#333333", hover_color="#444444",
                                        height=55, corner_radius=28, command=self.show_setup_dialog)
        self.config_btn.grid(row=0, column=2, padx=10, sticky="ew")

    # --- LOGIQUE DE FONCTIONNEMENT ---

    def update_status(self, text, color="gray"):
        self.status_label.configure(text=f"Statut : {text}", text_color=color)

    def start_sync_thread(self):
        if self.is_sync_running: return
        if not spotify_auth.sp:
            self.show_setup_dialog()
            return
        Thread(target=self.run_sync, daemon=True).start()

    def start_retry_thread(self):
        if self.is_sync_running: return
        Thread(target=self.run_retry, daemon=True).start()

    def process_one_track(self, t):
        """Action unique pour un thread : Téléchargement + Tagging."""
        try:
            self.tree.set(t['id'], "statut", "🔽 En cours...")
            if download_track(t['name'], t['artist'], t['id']):
                filename = f"{sanitize_filename(t['name'])} - {sanitize_filename(t['artist'])}.mp3"
                file_path = os.path.join("mp3", filename)
                
                # Ajout des tags et image
                add_metadata(file_path, t['name'], t['artist'], t['album'], t['cover_url'])
                
                save_downloaded_track(t['id'], t['name'], t['artist'])
                self.tree.set(t['id'], "statut", "✅ Terminé")
            else:
                self.tree.set(t['id'], "statut", "❌ Échec")
        except Exception as e:
            self.tree.set(t['id'], "statut", "❌ Erreur")

    def run_sync(self):
        self.is_sync_running = True
        self.sync_btn.configure(state="disabled")
        self.update_status("Récupération Spotify...", "orange")
        
        tracks = get_all_liked_tracks()
        delete_removed_tracks(tracks)

        self.tree.delete(*self.tree.get_children())
        to_download = []
        for t in tracks:
            deja_la = is_track_in_db(t['id'])
            self.tree.insert("", "end", iid=t['id'], values=(t['name'], t['artist'], "✅ Présent" if deja_la else "⏳ En attente"))
            if not deja_la:
                to_download.append(t)

        self.update_status(f"Téléchargement turbo ({len(to_download)} titres)...", "#1DB954")
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            executor.map(self.process_one_track, to_download)
        
        self.update_status("Synchronisation terminée !", "#1DB954")
        self.sync_btn.configure(state="normal")
        self.is_sync_running = False

    def run_retry(self):
        self.is_sync_running = True
        self.retry_btn.configure(state="disabled")
        self.update_status("Retraitement des échecs...", "#E74C3C")

        # Identifier les lignes avec un échec
        failed_ids = [self.tree.item(item)["values"] for item in self.tree.get_children() 
                     if "❌" in self.tree.item(item)["values"][2] or "Échec" in self.tree.item(item)["values"][2]]
        
        # On doit re-récupérer les infos complètes de Spotify pour ces IDs
        all_tracks = get_all_liked_tracks()
        to_retry = [t for t in all_tracks if any(f[0] == t['name'] for f in failed_ids)]

        if not to_retry:
            self.update_status("Aucun échec trouvé.", "#1DB954")
        else:
            with ThreadPoolExecutor(max_workers=2) as executor:
                executor.map(self.process_one_track, to_retry)

        self.update_status("Réessai terminé !", "#1DB954")
        self.retry_btn.configure(state="normal")
        self.is_sync_running = False

    def show_setup_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Setup")
        win.geometry("450x550")
        win.attributes('-topmost', True)

        ctk.CTkLabel(win, text="Spotify API Setup", font=("Arial", 22, "bold")).pack(pady=25)
        ctk.CTkButton(win, text="🌐 Dashboard Spotify", command=lambda: webbrowser.open("https://developer.spotify.com/dashboard")).pack(pady=10)

        self.e_id = ctk.CTkEntry(win, placeholder_text="Client ID", width=350, height=40)
        self.e_id.pack(pady=10)
        self.e_sec = ctk.CTkEntry(win, placeholder_text="Client Secret", width=350, height=40, show="*")
        self.e_sec.pack(pady=10)

        def save():
            new_sp = spotify_auth.save_credentials(self.e_id.get().strip(), self.e_sec.get().strip())
            if new_sp:
                Thread(target=lambda: (new_sp.current_user(), win.destroy(), self.update_status("Connecté", "#1DB954")), daemon=True).start()

        ctk.CTkButton(win, text="VALIDER", height=45, command=save).pack(pady=30)

if __name__ == "__main__":
    app = SpotifySyncApp()
    app.mainloop()
