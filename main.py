import customtkinter as ctk
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
import webbrowser
import shutil
import threading
from threading import Thread, Event, Lock
import os
import queue
import subprocess
import math
import io
import requests
from PIL import Image, ImageTk, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor

# Tous les chemins (.env, .cache, tracks.db, mp3/, yt-dlp.exe) sont relatifs au
# dossier du projet, quel que soit l'endroit d'où l'appli est lancée.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import spotify_auth
from spotify_liked_tracks import get_all_liked_tracks
from mp3_manager import (init_db, is_track_in_db, save_downloaded_track, is_db_writable,
                         get_tracks_to_delete, delete_tracks, track_filepath,
                         get_downloaded_tracks, write_m3u)
from downloader import download_track, add_metadata
from settings import load_settings, save_settings

LIKED_PLAYLIST_NAME = "Titres likés"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# ─── Palette (inspirée de l'appli Spotify) ───────────────────────────────────
BG_BASE    = "#000000"   # fond de la fenêtre, entre les panneaux
BG_PANEL   = "#121212"   # panneaux (bibliothèque, contenu)
BG_ELEV    = "#1F1F1F"   # survol dans la bibliothèque
BG_HOVER   = "#2A2A2A"   # survol d'une ligne du tableau
BG_ACTIVE  = "#333333"   # élément actif / sélectionné
GREEN      = "#1DB954"
GREEN_HI   = "#1ED760"
WHITE      = "#FFFFFF"
TEXT_SUB   = "#B3B3B3"
TEXT_DIM   = "#727272"
RED        = "#F15E6C"
GOLD       = "#F59B23"
BLUE       = "#509BF5"
FONT       = "Segoe UI"

# Noms utilisés par les fenêtres Réglages / Configuration
ACCENT, ACCENT_DIM = GREEN, "#1AA34A"
BG_DEEP, BG_CARD, BG_SURFACE = BG_BASE, "#181818", BG_HOVER
BORDER = "#3E3E3E"
TEXT_HI, TEXT_MID, TEXT_LO = WHITE, TEXT_SUB, TEXT_DIM
FONT_BTN   = (FONT, 13, "bold")
FONT_LABEL = (FONT, 12)
FONT_TITLE = (FONT, 22, "bold")

# Tailles en pixels « logiques » (multipliées par le zoom d'affichage de Windows)
ROW_H      = 56    # hauteur d'une ligne du tableau
COVER_ROW  = 40    # pochette dans le tableau
COVER_HDR  = 200   # grande pochette de la bannière
BANNER_H   = 270   # zone pochette + titre
HEADER_H   = 340   # bannière + rangée d'actions (bouton ↓, recherche)
COVER_LOAD = 64    # taille de téléchargement des pochettes de titres

SYMBOL_FONT = "seguisym.ttf"


# ─── Thread-safe UI calls ────────────────────────────────────────────────────
# Tkinter n'accepte d'être modifié que depuis le thread principal. Les threads
# de travail déposent leurs mises à jour dans cette file, vidée par la boucle Tk.
_ui_queue = queue.Queue()


def _in_main_thread():
    return threading.current_thread() is threading.main_thread()


def run_in_ui(fn, *args):
    """Exécute fn(*args) dans le thread Tk (immédiatement si on y est déjà)."""
    if _in_main_thread():
        fn(*args)
    else:
        _ui_queue.put(lambda: fn(*args))


def run_in_ui_wait(fn, *args):
    """Comme run_in_ui, mais attend la fin et renvoie le résultat de fn."""
    if _in_main_thread():
        return fn(*args)
    done, box = Event(), {}

    def task():
        try:
            box["result"] = fn(*args)
        finally:
            done.set()
    _ui_queue.put(task)
    done.wait()
    return box.get("result")


# ─── Images & couleurs ───────────────────────────────────────────────────────
def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)


def mix(a, b, t):
    """Mélange deux couleurs hex : t=0 → a, t=1 → b."""
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex([x + (y - x) * t for x, y in zip(ra, rb)])


def load_pil_image(url, size):
    """Télécharge et redimensionne une image (sans toucher à Tk : OK dans un thread)."""
    data = requests.get(url, timeout=5).content
    return Image.open(io.BytesIO(data)).convert("RGB").resize((size, size), Image.LANCZOS)


def rounded(img, radius):
    """Arrondit les coins d'une image (coins transparents)."""
    img = img.convert("RGBA")
    if radius > 0:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, img.size[0] - 1, img.size[1] - 1), radius=radius, fill=255)
        img.putalpha(mask)
    return img


def dominant_color(img):
    """Couleur moyenne de la pochette, assez sombre pour garder le texte blanc lisible."""
    r, g, b = img.convert("RGB").resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    scale = min(1.8, 160 / max(r, g, b, 1))
    return rgb_to_hex((r * scale, g * scale, b * scale))


def _symbol(img, char, ratio, color="white"):
    try:
        font = ImageFont.truetype(SYMBOL_FONT, int(img.size[0] * ratio))
    except OSError:
        return img
    ImageDraw.Draw(img).text((img.size[0] / 2, img.size[1] / 2), char,
                             font=font, fill=color, anchor="mm")
    return img


def gradient_square(size, top_left, bottom_right):
    """Carré en dégradé diagonal."""
    mid = mix(top_left, bottom_right, 0.5)
    small = Image.new("RGB", (2, 2))
    small.putdata([hex_to_rgb(top_left), hex_to_rgb(mid), hex_to_rgb(mid), hex_to_rgb(bottom_right)])
    return small.resize((size, size), Image.BILINEAR)


def liked_cover(size):
    """Pochette « Titres likés » façon Spotify : dégradé violet → vert d'eau + cœur."""
    return _symbol(gradient_square(size, "#450AF5", "#C4EFD9"), "♥", 0.42)


def sync_cover(size):
    return _symbol(gradient_square(size, "#1ED760", "#0B3D1D"), "⭳", 0.46)


def placeholder_cover(size):
    return _symbol(Image.new("RGB", (size, size), "#282828"), "♫", 0.4, TEXT_DIM)


def fmt_duration(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


def fmt_total(seconds):
    h, m = seconds // 3600, seconds % 3600 // 60
    if h:
        return f"environ {h} h {m} min"
    return f"{m} min {seconds % 60} s"


def truncate(text, n):
    return text if len(text) <= n else text[:n - 1] + "…"


# ─── yt-dlp update ───────────────────────────────────────────────────────────
def update_yt_dlp():
    """Lance la mise à jour automatique de l'exécutable yt-dlp."""
    if os.path.exists("yt-dlp.exe"):
        try:
            subprocess.run(["yt-dlp.exe", "-U"], check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            print("Vérification des mises à jour de yt-dlp terminée.")
        except Exception as e:
            print(f"Erreur lors de la mise à jour automatique : {e}")
    else:
        print("yt-dlp.exe introuvable, impossible de mettre à jour.")


# ─── Petits widgets ──────────────────────────────────────────────────────────
class Tooltip:
    """Bulle d'aide qui apparaît au survol d'un bouton-icône."""

    def __init__(self, widget, text):
        self.w, self.text, self.tip, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self.job = self.w.after(450, self._show)

    def _cancel(self):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None

    def _show(self):
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        self.tip.attributes("-topmost", True)
        tk.Label(self.tip, text=self.text, bg="#282828", fg=WHITE,
                 font=(FONT, 9), padx=8, pady=4).pack()
        self.tip.update_idletasks()
        x = self.w.winfo_rootx() + self.w.winfo_width() // 2 - self.tip.winfo_width() // 2
        y = self.w.winfo_rooty() - self.tip.winfo_height() - 6
        self.tip.geometry(f"+{x}+{y}")

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class SyncToggle(tk.Canvas):
    """Bouton rond ↓ (comme « Télécharger » dans Spotify) : vert = inclus dans la synchro.
    Dessiné avec PIL en sur-échantillonnage pour avoir un cercle lisse (le Canvas Tk
    ne lisse pas les cercles)."""

    _cache = {}

    def __init__(self, parent, size, on_change=None, bg=BG_PANEL):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.size, self._on_change = size, on_change
        self._on = self._locked = self._hover = False
        self._item = self.create_image(0, 0, anchor="nw")
        self.bind("<Button-1>", self._clicked)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self._draw()

    def set(self, on, locked=False):
        self._on, self._locked = on, locked
        self.configure(cursor="arrow" if locked else "hand2")
        self._draw()

    def set_bg(self, color):
        self.configure(bg=color)

    def _set_hover(self, hover):
        self._hover = hover and not self._locked
        self._draw()

    @classmethod
    def _image(cls, size, on, hover, disabled=False):
        key = (size, on, hover, disabled)
        if key not in cls._cache:
            k = 4                                    # sur-échantillonnage
            S = size * k
            img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            if on:
                d.ellipse((0, 0, S - 1, S - 1), fill=GREEN_HI if hover else GREEN)
                color = BG_BASE
            else:
                w = max(k * 2, S // 14)
                outline = "#3A3A3A" if disabled else (WHITE if hover else TEXT_DIM)
                d.ellipse((w // 2, w // 2, S - 1 - w // 2, S - 1 - w // 2),
                          outline=outline, width=w)
                color = "#4A4A4A" if disabled else (WHITE if hover else TEXT_SUB)
            lw = max(k * 2, int(S * 0.085))
            cx = S / 2
            d.line((cx, S * 0.27, cx, S * 0.70), fill=color, width=lw)
            d.line((cx - S * 0.19, S * 0.50, cx, S * 0.71, cx + S * 0.19, S * 0.50),
                   fill=color, width=lw, joint="curve")
            cls._cache[key] = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
        return cls._cache[key]

    def _draw(self):
        self.itemconfigure(self._item, image=self._image(
            self.size, self._on, self._hover, disabled=self._locked and not self._on))

    def _clicked(self, _e=None):
        if self._locked:
            return
        self._on = not self._on
        self._draw()
        if self._on_change:
            self._on_change(self._on)


class PlayButton(tk.Canvas):
    """Gros bouton rond blanc de la barre du bas : ▶ (synchroniser) ou ■ (arrêter)."""

    _cache = {}

    def __init__(self, parent, size, command):
        super().__init__(parent, width=size, height=size, bg=BG_BASE,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.size, self.command = size, command
        self._icon, self._enabled, self._hover = "play", True, False
        self._item = self.create_image(0, 0, anchor="nw")
        self.bind("<Button-1>", lambda _e: self._enabled and self.command())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self._draw()

    def set(self, icon=None, enabled=None):
        if icon is not None:
            self._icon = icon
        if enabled is not None:
            self._enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def _set_hover(self, hover):
        self._hover = hover
        self._draw()

    @classmethod
    def _image(cls, size, icon, enabled, hover):
        key = (size, icon, enabled, hover)
        if key not in cls._cache:
            k = 4
            S = size * k
            img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            # Au survol, Spotify grossit légèrement le bouton
            m = 0 if hover and enabled else int(S * 0.04)
            d.ellipse((m, m, S - 1 - m, S - 1 - m), fill=WHITE if enabled else "#7A7A7A")
            if icon == "play":
                d.polygon([(S * 0.40, S * 0.31), (S * 0.40, S * 0.69), (S * 0.71, S * 0.50)],
                          fill=BG_BASE)
            else:
                d.rounded_rectangle((S * 0.36, S * 0.36, S * 0.64, S * 0.64),
                                    radius=S * 0.03, fill=BG_BASE)
            cls._cache[key] = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
        return cls._cache[key]

    def _draw(self):
        self.itemconfigure(self._item, image=self._image(
            self.size, self._icon, self._enabled, self._hover))


class Equalizer(tk.Canvas):
    """Petites barres vertes animées pendant un téléchargement (comme « en lecture »)."""

    def __init__(self, parent, size):
        super().__init__(parent, width=size, height=size, bg=BG_BASE,
                         highlightthickness=0, bd=0)
        self.s, self._on, self._t = size, False, 0
        self._bars([0.2] * 4, BG_BASE)

    def start(self):
        if not self._on:
            self._on = True
            self._tick()

    def stop(self):
        self._on = False
        self._bars([0.2] * 4, BG_BASE)

    def _bars(self, heights, color):
        self.delete("all")
        bw = self.s / 7
        for i, h in enumerate(heights):
            x0 = i * 2 * bw
            self.create_rectangle(x0, self.s * (1 - h), x0 + bw, self.s, fill=color, width=0)

    def _tick(self):
        if not self._on:
            return
        self._t += 1
        self._bars([0.25 + 0.75 * abs(math.sin(self._t * 0.22 + i * 1.3)) for i in range(4)], GREEN)
        self.after(90, self._tick)


class BottomProgress(ctk.CTkFrame):
    """Barre de progression de la barre du bas : « 12 ━━━━━━━━── 50 »."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._done = ctk.CTkLabel(self, text="0", width=44, anchor="e",
                                  font=(FONT, 11), text_color=TEXT_SUB)
        self._done.pack(side="left")
        self.bar = ctk.CTkProgressBar(self, width=460, height=4, corner_radius=2,
                                      fg_color="#4D4D4D", progress_color=WHITE)
        self.bar.set(0)
        self.bar.pack(side="left", padx=10)
        self._total = ctk.CTkLabel(self, text="0", width=44, anchor="w",
                                   font=(FONT, 11), text_color=TEXT_SUB)
        self._total.pack(side="left")

    def set(self, done, total):
        self.bar.set(done / total if total > 0 else 0)
        self._done.configure(text=str(done))
        self._total.configure(text=str(total))

    def set_active(self, active):
        self.bar.configure(progress_color=GREEN if active else WHITE)


# ─── Ligne de la bibliothèque (barre de gauche) ──────────────────────────────
class LibraryRow(ctk.CTkFrame):
    """Pochette + nom + « Playlist • N titres » + bouton ↓ (inclure dans la synchro).
    Un clic sur la ligne affiche la playlist."""

    def __init__(self, parent, title, subtitle, image, on_click, toggle_size,
                 on_toggle=None, selected=False, locked=False, unavailable=None):
        super().__init__(parent, fg_color="transparent", corner_radius=6)
        self._active = False
        self._bg = BG_PANEL
        self.grid_columnconfigure(1, weight=1)

        self._img = ctk.CTkLabel(self, text="", image=image, width=48, height=48)
        self._img.grid(row=0, column=0, rowspan=2, padx=(8, 12), pady=8)
        self._title = ctk.CTkLabel(self, text=truncate(title, 24), font=(FONT, 14),
                                   text_color=WHITE, anchor="w", height=20)
        self._title.grid(row=0, column=1, sticky="sw")
        self._sub = ctk.CTkLabel(self, text=subtitle, font=(FONT, 12),
                                 text_color=TEXT_SUB, anchor="w", height=18)
        self._sub.grid(row=1, column=1, sticky="nw")
        self.toggle = SyncToggle(self, size=toggle_size, on_change=on_toggle, bg=BG_PANEL)
        if unavailable:                   # playlist illisible : bouton ↓ grisé et bloqué
            self.toggle.set(False, locked=True)
            self._sub.configure(text_color=TEXT_DIM)
            Tooltip(self.toggle, unavailable)
        else:
            self.toggle.set(selected or locked, locked)
            Tooltip(self.toggle, "Toujours synchronisé" if locked else "Inclure dans la synchro")
        self.toggle.grid(row=0, column=2, rowspan=2, padx=(6, 12))

        for w in (self, self._img, self._title, self._sub):
            w.bind("<Button-1>", lambda _e: on_click())
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _paint(self, color):
        self.configure(fg_color=color if color != BG_PANEL else "transparent")
        self.toggle.set_bg(color)   # le Canvas du bouton ↓ n'hérite pas de la couleur

    def _enter(self, _e=None):
        if not self._active:
            self._paint(BG_ELEV)

    def _leave(self, _e=None):
        # <Leave> arrive aussi quand la souris passe sur un enfant : on vérifie
        x, y = self.winfo_pointerxy()
        under = self.winfo_containing(x, y)
        if under is not None and str(under).startswith(str(self)):
            return
        if not self._active:
            self._paint(BG_PANEL)

    def set_active(self, active):
        self._active = active
        self._paint(BG_HOVER if active else BG_PANEL)
        self._title.configure(text_color=GREEN if active else WHITE)


# ─── Main App ─────────────────────────────────────────────────────────────────
class SpotifySyncApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        Thread(target=update_yt_dlp, daemon=True).start()

        self.title("Spotify Sync")
        self.geometry("1400x900")
        self.minsize(1100, 720)
        self.configure(fg_color=BG_BASE)
        try:
            self.S = ctk.ScalingTracker.get_widget_scaling(self)
        except Exception:
            self.S = 1.0

        self.settings        = load_settings()
        self.is_sync_running = False
        self._stop_event     = Event()  # levé par le bouton Stop
        self._total          = 0
        self._done           = 0
        self._selected_pls   = set(self.settings["selected_playlists"])
        self._playlists      = {}       # pl_id -> {name, total, cover}
        self._playlist_names = {}       # pl_id -> nom (pour les fichiers .m3u8)
        self._playlist_rows  = {}
        self._liked_row      = None
        self._liked_total    = None
        self._user_name      = "Toi"
        self._user_id        = None
        self._tracks_by_id   = {}       # titres de la vue affichée
        self._view_tracks    = []       # [(numéro, titre)] dans l'ordre Spotify
        self._state          = {}       # track_id -> (texte de l'état, tag)
        self._skip_counts    = {}       # track_id -> résultats YouTube déjà essayés
        self._cover_cache    = {}       # track_id -> PhotoImage du tableau
        self._cover_pil      = {}       # track_id -> image PIL (barre du bas)
        self._cover_loading  = set()
        self._banner_cache   = {}       # url -> (image PIL, couleur)
        self._sort           = None     # (colonne, décroissant) ou None = ordre Spotify
        self._hover_iid      = None
        self._view_token     = 0
        self._hdr_after      = None
        self._hdr_bg_key     = None
        self._hdr_cover_key  = None
        self._search_after   = None
        self._fonts          = {}
        self._active_preview = None     # pl_id affiché, None = titres likés
        self._done_lock      = Lock()
        self._cover_pool     = ThreadPoolExecutor(max_workers=8)
        self._last_sources   = None     # {playlist: titres} de la dernière synchro
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        families = set(tkfont.families(self))
        self._title_font_family = "Segoe UI Black" if "Segoe UI Black" in families else FONT
        self._placeholder_pil = placeholder_cover(128)
        self._liked_pil       = liked_cover(256)
        self._sync_pil        = sync_cover(256)

        init_db()
        self._build_ui()
        self._poll_ui_queue()
        self._set_view("liked")

        if spotify_auth.sp is None:
            self._set_status("Non connecté à Spotify", GOLD)
            self.after(600, self.show_setup_dialog)
        else:
            self._set_status("Connexion à Spotify...", TEXT_SUB)
            self._fetch_user_info()
        if not is_db_writable():
            self.after(800, lambda: messagebox.showwarning(
                "Base en lecture seule",
                "Le fichier tracks.db est en lecture seule : les titres téléchargés ne "
                "pourront pas être enregistrés et seraient retéléchargés à chaque synchro.\n\n"
                "Clic droit sur tracks.db → Propriétés → décoche « Lecture seule ».",
                parent=self))

    def px(self, v):
        """Pixels logiques → pixels réels (zoom d'affichage de Windows)."""
        return int(round(v * self.S))

    def _on_close(self):
        """Coupe les téléchargements : sinon le programme reste actif en arrière-plan
        jusqu'à la fin de la file d'attente, fenêtre fermée."""
        self._stop_event.set()
        self._cover_pool.shutdown(wait=False, cancel_futures=True)
        self.destroy()

    @property
    def mp3_folder(self):
        return self.settings["mp3_folder"]

    def _is_present(self, track):
        """Un titre est présent s'il est en base ET que son MP3 existe encore sur le disque."""
        return (is_track_in_db(track['id'])
                and os.path.exists(track_filepath(track['name'], track['artist'], self.mp3_folder)))

    def _save_selected_playlists(self):
        self.settings["selected_playlists"] = sorted(self._selected_pls)
        save_settings(self.settings)

    def _poll_ui_queue(self):
        """Exécute les mises à jour d'interface envoyées par les threads."""
        try:
            while True:
                task = _ui_queue.get_nowait()
                try:
                    task()
                except Exception as e:   # une erreur ne doit pas bloquer toute l'interface
                    print(f"Erreur d'interface : {e}")
        except queue.Empty:
            pass
        self.after(30, self._poll_ui_queue)

    def _ctk_image(self, pil, size):
        return ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))

    # ─── Spotify data ────────────────────────────────────────────────────────
    def _fetch_user_info(self):
        """Récupère le profil, puis charge la bibliothèque et les titres likés.
        Les appels sont enchaînés : au premier lancement, un seul onglet de
        connexion s'ouvre dans le navigateur."""
        def _do():
            try:
                user     = spotify_auth.sp.current_user()
                self._user_id = user.get("id")
                name     = user.get("display_name") or user.get("id", "Utilisateur")
                initials = "".join(p[0].upper() for p in name.split()[:2]) or "SP"
                run_in_ui(self._set_user, name, initials)
            except Exception as e:
                print(f"Erreur de connexion Spotify : {e}")
                self._set_status("❌ Connexion à Spotify impossible", RED)
                return
            run_in_ui(self._load_playlists)
            run_in_ui(self._on_liked_click)
            self._set_status("Prêt", GREEN)
        Thread(target=_do, daemon=True).start()

    def _set_user(self, name, initials):
        self._user_name = name
        self._avatar_lbl.configure(text=initials[:2])
        self._username_lbl.configure(text=truncate(name, 22))
        self._schedule_header_draw()

    def _load_playlists(self):
        def _do():
            try:
                liked_total = spotify_auth.sp.current_user_saved_tracks(limit=1).get("total")
                playlists, limit, offset = [], 50, 0
                while True:
                    res   = spotify_auth.sp.current_user_playlists(limit=limit, offset=offset)
                    items = res.get("items", [])
                    if not items:
                        break
                    for pl in items:
                        if not pl:
                            continue
                        images = pl.get("images") or []
                        cover  = images[0].get("url", "") if images else ""
                        # Spotify a renommé « tracks » en « items » : on accepte les deux
                        ti     = pl.get("items") or pl.get("tracks") or {}
                        owner  = pl.get("owner") or {}
                        playlists.append({
                            "id":    pl["id"],
                            "name":  pl["name"],
                            "total": ti.get("total", 0) if isinstance(ti, dict) else 0,
                            "cover": cover,
                            "owner": owner.get("display_name") or owner.get("id", "?"),
                            # Spotify ne donne le contenu d'une playlist qu'à son
                            # propriétaire ou à ses collaborateurs (sinon erreur 403)
                            "readable": owner.get("id") == self._user_id
                                        or bool(pl.get("collaborative")),
                        })
                    offset += limit
                    if len(items) < limit:
                        break
                run_in_ui(self._populate_sidebar, playlists, liked_total)
            except Exception as e:
                print(f"Erreur chargement playlists : {e}")
                self._set_status("❌ Erreur de chargement des playlists", RED)
        Thread(target=_do, daemon=True).start()

    def _populate_sidebar(self, playlists, liked_total=None):
        for w in self._pl_scroll.winfo_children():
            w.destroy()
        self._playlist_rows.clear()
        self._playlists      = {pl["id"]: pl for pl in playlists}
        self._playlist_names = {pl["id"]: pl["name"] for pl in playlists}
        if liked_total is not None:
            self._liked_total = liked_total

        # Oublie les playlists cochées qui n'existent plus ou ne sont pas lisibles
        self._selected_pls &= {pl["id"] for pl in playlists if pl.get("readable", True)}
        self._save_selected_playlists()
        self._update_selection_label()

        liked_sub = (f"Playlist • {self._liked_total} titres"
                     if self._liked_total is not None else "Playlist")
        self._liked_row = LibraryRow(self._pl_scroll, "Titres likés", liked_sub,
                                     self._ctk_image(self._liked_pil, 48),
                                     on_click=self._on_liked_click,
                                     toggle_size=self.px(28), locked=True)
        self._liked_row.pack(fill="x", pady=1)

        for pl in playlists:
            readable = pl.get("readable", True)
            sub = (f"Playlist • {pl['total']} titres" if readable
                   else f"Playlist • de {truncate(pl['owner'], 18)}")
            row = LibraryRow(
                self._pl_scroll, pl["name"], sub,
                self._ctk_image(self._placeholder_pil, 48),
                on_click=lambda pid=pl["id"]: self._preview_playlist(pid),
                toggle_size=self.px(28),
                on_toggle=lambda on, pid=pl["id"]: self._on_playlist_toggle(pid, on),
                selected=pl["id"] in self._selected_pls,
                unavailable=None if readable else
                f"Appartient au compte « {pl['owner']} » : Spotify ne donne pas son contenu")
            row.pack(fill="x", pady=1)
            self._playlist_rows[pl["id"]] = row
            if pl["cover"]:
                self._cover_pool.submit(self._load_sidebar_cover, row, pl["cover"])

        if not playlists:
            ctk.CTkLabel(self._pl_scroll, text="Aucune playlist",
                         font=(FONT, 12), text_color=TEXT_DIM).pack(pady=20)
        self._highlight_active_row()

    def _load_sidebar_cover(self, row, url):
        try:
            img = rounded(load_pil_image(url, 96), 8)
        except Exception:
            return

        def apply():
            if row.winfo_exists():
                row._img.configure(image=self._ctk_image(img, 48))
        run_in_ui(apply)

    def _highlight_active_row(self):
        if self._liked_row is not None and self._liked_row.winfo_exists():
            self._liked_row.set_active(self._view_kind == "liked")
        for pid, row in self._playlist_rows.items():
            row.set_active(self._view_kind == "playlist" and pid == self._active_preview)

    def _on_playlist_toggle(self, pl_id, selected):
        if selected:
            self._selected_pls.add(pl_id)
        else:
            self._selected_pls.discard(pl_id)
        self._save_selected_playlists()
        self._update_selection_label()
        # Garde le bouton de la bibliothèque et celui de la bannière d'accord
        row = self._playlist_rows.get(pl_id)
        if row:
            row.toggle.set(selected)
        if self._view_kind == "playlist" and self._active_preview == pl_id:
            self._hdr_toggle.set(selected)
            self._schedule_header_draw()

    def _update_selection_label(self):
        n = len(self._selected_pls)
        self._pl_count_lbl.configure(
            text=f"Titres likés + {n} playlist{'s' if n > 1 else ''} synchronisée{'s' if n > 1 else ''}"
            if n else "Seuls les titres likés sont synchronisés")

    def _get_playlist_tracks(self, pl_id):
        """Renvoie la liste des titres, ou None si la playlist est inaccessible (403).
        Toute autre erreur est remontée : on ne renvoie jamais une liste incomplète."""
        tracks, limit, offset = [], 100, 0
        while True:
            try:
                res = spotify_auth.sp.playlist_tracks(pl_id, limit=limit, offset=offset)
            except Exception as e:
                err = str(e)
                if "403" in err or "Forbidden" in err:
                    print(f"Playlist {pl_id} inaccessible (playlist éditoriale Spotify).")
                    return None  # signal = accès refusé
                raise
            items = res.get("items", [])
            if not items:
                break
            for item in items:
                t = item.get("track") or item.get("item")   # nouveau nom côté Spotify
                if not t or not t.get("id"):
                    continue
                images = t["album"].get("images") or []
                cover  = images[0]["url"] if images else ""
                tracks.append({
                    "id":        t["id"],
                    "name":      t["name"],
                    "artist":    t["artists"][0]["name"],
                    "album":     t["album"]["name"],
                    "cover_url": cover,
                    "duration":  (t.get("duration_ms") or 0) // 1000,
                })
            offset += limit
            if len(items) < limit:
                break
        return tracks

    # ─── Vues : titres likés / playlist / synchro ────────────────────────────
    def _set_view(self, kind, pl_id=None):
        """Prépare la bannière et vide le tableau en attendant les titres."""
        self._view_token += 1
        self._view_kind = kind
        self._active_preview = pl_id if kind == "playlist" else None
        if kind == "liked":
            self._view = {"label": "Playlist", "title": "Titres likés",
                          "cover": self._liked_pil, "color": "#5038A0"}
        elif kind == "sync":
            n = len(self._selected_pls)
            self._view = {"label": "Synchronisation", "title": "Ma synchro",
                          "cover": self._sync_pil, "color": "#1E7A3E",
                          "detail": f"Titres likés + {n} playlist{'s' if n > 1 else ''}"}
        else:
            pl = self._playlists.get(pl_id, {})
            url = pl.get("cover", "")
            cover, color = self._banner_cache.get(url, (self._placeholder_pil, "#535353"))
            self._view = {"label": "Playlist", "title": pl.get("name", "Playlist"),
                          "cover": cover, "color": color}
            if url and url not in self._banner_cache:
                self._cover_pool.submit(self._load_banner_cover, self._view_token, url)
        self._view["subtitle"] = "Chargement..."

        # Bouton ↓ de la bannière
        if kind == "liked":
            self._hdr_toggle.set(True, locked=True)
        elif kind == "playlist":
            if self._playlists.get(pl_id, {}).get("readable", True):
                self._hdr_toggle.set(pl_id in self._selected_pls)
            else:
                self._hdr_toggle.set(False, locked=True)

        if self._search.get():   # (vider un champ vide ferait disparaître le texte d'aide)
            self._search.delete(0, "end")
        self._sort = None
        self._update_heading_arrows()
        self._fill_table([], preview=True, loading=True)
        self._highlight_active_row()
        self._schedule_header_draw()

    def _load_banner_cover(self, token, url):
        try:
            img = load_pil_image(url, 300)
        except Exception:
            return
        color = dominant_color(img)

        def apply():
            self._banner_cache[url] = (img, color)
            if token == self._view_token:
                self._view["cover"], self._view["color"] = img, color
                self._schedule_header_draw()
        run_in_ui(apply)

    def _on_liked_click(self):
        if self.is_sync_running:
            return
        self._set_view("liked")
        token = self._view_token

        def _do():
            self._set_status("Chargement des titres likés...", TEXT_SUB)
            tracks = get_all_liked_tracks()
            if tracks is None:
                self._set_status("❌ Erreur de chargement des titres likés", RED)
                run_in_ui(self._show_empty, token, "Impossible de charger les titres likés")
                return
            run_in_ui(self._show_view_tracks, token, tracks)
        Thread(target=_do, daemon=True).start()

    def _preview_playlist(self, pl_id):
        if self.is_sync_running:
            return
        self._set_view("playlist", pl_id)
        token = self._view_token
        pl = self._playlists.get(pl_id, {})
        if not pl.get("readable", True):
            # Inutile d'interroger Spotify : il répondrait 403
            self._set_status("⛔ Playlist d'un autre compte", GOLD)
            self._show_empty(token, f"Cette playlist appartient au compte « {pl.get('owner')} ».\n"
                                    f"Spotify ne donne son contenu qu'à son propriétaire :\n"
                                    f"connecte-toi avec ce compte (⚙ → Changer de compte).")
            return

        def _do():
            self._set_status("Chargement de la playlist...", TEXT_SUB)
            try:
                tracks = self._get_playlist_tracks(pl_id)
            except Exception as e:
                print(f"Erreur playlist {pl_id} : {e}")
                self._set_status("❌ Erreur de chargement de la playlist", RED)
                run_in_ui(self._show_empty, token, "Impossible de charger cette playlist")
                return
            if tracks is None:
                self._set_status("⛔ Spotify refuse l'accès à cette playlist", RED)
                run_in_ui(self._show_empty, token, "⛔  Spotify ne permet pas de lire cette playlist")
                return
            run_in_ui(self._show_view_tracks, token, tracks)
        Thread(target=_do, daemon=True).start()

    def _show_view_tracks(self, token, tracks):
        if token != self._view_token:     # l'utilisateur a déjà cliqué ailleurs
            return
        self._fill_table(tracks, preview=True)
        self._set_status("Prêt", GREEN)

    def _show_empty(self, token, text):
        if token == self._view_token:
            self._view["subtitle"] = ""
            self._schedule_header_draw()
            self._empty_lbl.configure(text=text)
            self._empty_lbl.place(relx=0.5, rely=0.25, anchor="center")

    # ─── Tableau ──────────────────────────────────────────────────────────────
    def _fill_table(self, tracks, preview=False, loading=False):
        """Charge une liste de titres dans la vue (aperçu ou synchro)."""
        # Une playlist peut contenir deux fois le même titre, or chaque ligne a besoin d'un id unique
        tracks = list({t['id']: t for t in tracks}.values())
        self._tracks_by_id = {t['id']: t for t in tracks}
        self._view_tracks  = list(enumerate(tracks, 1))
        self._state = {}
        for t in tracks:
            if self._is_present(t):
                self._state[t['id']] = ("✓  Téléchargé", "ok")
            else:
                self._state[t['id']] = ("Non téléchargé", "dim") if preview else ("⏳  En attente", "dim")
            if (t['id'] not in self._cover_cache and t['id'] not in self._cover_loading
                    and t.get('cover_url')):
                self._cover_loading.add(t['id'])
                self._cover_pool.submit(self._load_cover_for_row, t['id'], t['cover_url'])

        if not loading:
            total_s = sum(t.get('duration', 0) for t in tracks)
            detail  = self._view.get("detail")
            parts   = [detail] if detail else [self._user_name]
            parts.append(f"{len(tracks)} titres, {fmt_total(total_s)}")
            self._view["subtitle"] = " • ".join(parts)
            self._schedule_header_draw()
        self._render_table(loading=loading)
        self._update_all_stats()

    def _render_table(self, loading=False):
        """Redessine les lignes en appliquant la recherche et le tri."""
        self.tree.delete(*self.tree.get_children())
        self._hover_iid = None
        query = self._search.get().strip().lower()
        rows = self._view_tracks
        if query:
            rows = [(n, t) for n, t in rows
                    if query in t['name'].lower() or query in t['artist'].lower()
                    or query in t['album'].lower()]
        if self._sort:
            col, desc = self._sort
            rows = sorted(rows, key=lambda r: self._sort_key(col, r[1]), reverse=desc)

        for num, t in rows:
            text, tag = self._state.get(t['id'], ("", "dim"))
            # Numéro aligné à droite : l'espace « chiffre » (U+2007) a la largeur d'un chiffre
            label = f"{num:>4}".replace(" ", " ") + " "
            self.tree.insert("", "end", iid=t['id'], text=label,
                             image=self._cover_cache.get(t['id'], self._row_placeholder),
                             values=(t['name'], t['artist'], t['album'],
                                     fmt_duration(t.get('duration', 0)), text),
                             tags=(tag,))

        if loading:
            self._empty_lbl.configure(text="Chargement...")
            self._empty_lbl.place(relx=0.5, rely=0.25, anchor="center")
        elif not rows:
            msg = (f"Aucun titre ne correspond à « {self._search.get().strip()} »" if query
                   else "Cette playlist est vide")
            self._empty_lbl.configure(text=msg)
            self._empty_lbl.place(relx=0.5, rely=0.25, anchor="center")
        else:
            self._empty_lbl.place_forget()

    STATE_ORDER = {"busy": 0, "fail": 1, "dim": 2, "ok": 3}

    def _sort_key(self, col, t):
        if col == "duree":
            return t.get('duration', 0)
        if col == "statut":
            return self.STATE_ORDER.get(self._state.get(t['id'], ("", "dim"))[1], 9)
        return {"titre": t['name'], "artiste": t['artist'], "album": t['album']}[col].lower()

    HEADINGS = {"titre": "Titre", "artiste": "Artiste", "album": "Album",
                "duree": "Durée", "statut": "État"}

    def _sort_by(self, col):
        """Clic sur un en-tête : croissant → décroissant → ordre Spotify."""
        if col is None:
            self._sort = None
        elif not self._sort or self._sort[0] != col:
            self._sort = (col, False)
        elif not self._sort[1]:
            self._sort = (col, True)
        else:
            self._sort = None
        self._update_heading_arrows()
        self._render_table()

    def _update_heading_arrows(self):
        for col, label in self.HEADINGS.items():
            if self._sort and self._sort[0] == col:
                label += "  ▼" if self._sort[1] else "  ▲"
            self.tree.heading(col, text=label)

    def _on_search(self, _e=None):
        if self._search_after:
            self.after_cancel(self._search_after)
        self._search_after = self.after(150, self._render_table)

    def _clear_search(self, _e=None):
        if self._search.get():
            self._search.delete(0, "end")
        self._render_table()
        self.tree.focus_set()   # rend le focus pour réafficher le texte d'aide

    def _fit_columns(self, event):
        """Le Treeview ne rétrécit pas ses colonnes tout seul : on répartit la place
        restante entre Titre / Artiste / Album, les autres gardent leur largeur."""
        fixed = sum(self.tree.column(c, "width") for c in ("#0", "duree", "statut"))
        free = max(self.px(300), event.width - fixed - self.px(4))
        for col, share in (("titre", 0.42), ("artiste", 0.28), ("album", 0.30)):
            self.tree.column(col, width=int(free * share))

    def _on_tree_motion(self, event):
        iid = self.tree.identify_row(event.y)
        if iid == self._hover_iid:
            return
        old, self._hover_iid = self._hover_iid, iid or None
        for i in (old, self._hover_iid):
            if i and self.tree.exists(i):
                self.tree.item(i, tags=self._tags_for(i))

    def _on_tree_leave(self, _e=None):
        old, self._hover_iid = self._hover_iid, None
        if old and self.tree.exists(old):
            self.tree.item(old, tags=self._tags_for(old))

    def _tags_for(self, iid):
        tags = [self._state.get(iid, ("", "dim"))[1]]
        if iid == self._hover_iid:
            tags.append("hover")
        return tags

    # ─── Cover loading ────────────────────────────────────────────────────────
    def _load_cover_for_row(self, track_id, url):
        """Thread de travail : télécharge l'image, la conversion Tk se fait dans l'UI."""
        try:
            img = load_pil_image(url, max(COVER_LOAD, self.px(COVER_ROW)))
        except Exception:
            img = None
        run_in_ui(self._store_cover, track_id, img)

    def _store_cover(self, track_id, img):
        self._cover_loading.discard(track_id)
        if img is None:
            return
        self._cover_pil[track_id] = img
        size = self.px(COVER_ROW)
        photo = ImageTk.PhotoImage(rounded(img.resize((size, size), Image.LANCZOS), self.px(4)))
        self._cover_cache[track_id] = photo
        if self.tree.exists(track_id):
            self.tree.item(track_id, image=photo)

    # ─── UI Construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main_panel()
        self._build_bottom_bar()
        self.bind("<Control-f>", lambda _e: self._search.focus_set())

    # ── BIBLIOTHÈQUE (gauche) ────────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8, width=330)
        sb.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=(8, 0))
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(2, weight=1)

        hdr = ctk.CTkFrame(sb, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=(16, 10), pady=(14, 0))
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr, text="▥  Ta bibliothèque", font=(FONT, 16, "bold"),
                     text_color=TEXT_SUB, anchor="w").grid(row=0, column=0, sticky="w")
        refresh = ctk.CTkButton(hdr, text="↻", width=32, height=32, corner_radius=16,
                                fg_color="transparent", hover_color=BG_ELEV,
                                text_color=TEXT_SUB, font=(FONT, 16),
                                command=self._load_playlists)
        refresh.grid(row=0, column=1)
        Tooltip(refresh, "Rafraîchir les playlists")

        self._pl_count_lbl = ctk.CTkLabel(sb, text="", font=(FONT, 12),
                                          text_color=TEXT_DIM, anchor="w")
        self._pl_count_lbl.grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 8))
        self._update_selection_label()

        self._pl_scroll = ctk.CTkScrollableFrame(
            sb, fg_color="transparent",
            scrollbar_button_color="#3A3A3A", scrollbar_button_hover_color="#5A5A5A")
        self._pl_scroll.grid(row=2, column=0, sticky="nsew", padx=(6, 2))
        ctk.CTkLabel(self._pl_scroll, text="Chargement...",
                     font=(FONT, 12), text_color=TEXT_DIM).pack(pady=20)

        # Compte connecté
        user = ctk.CTkFrame(sb, fg_color="transparent")
        user.grid(row=3, column=0, sticky="ew", padx=16, pady=12)
        self._avatar_lbl = ctk.CTkLabel(user, text="?", width=32, height=32, corner_radius=16,
                                        fg_color="#AF2896", text_color=WHITE,
                                        font=(FONT, 12, "bold"))
        self._avatar_lbl.pack(side="left")
        col = ctk.CTkFrame(user, fg_color="transparent")
        col.pack(side="left", padx=(10, 0))
        self._username_lbl = ctk.CTkLabel(col, text="Connexion...", font=(FONT, 13, "bold"),
                                          text_color=WHITE, anchor="w", height=18)
        self._username_lbl.pack(anchor="w")
        ctk.CTkLabel(col, text="Compte Spotify", font=(FONT, 11),
                     text_color=TEXT_DIM, anchor="w", height=16).pack(anchor="w")

    # ── CONTENU (droite) ──────────────────────────────────────────────────────
    def _build_main_panel(self):
        main = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8)
        main.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=(8, 0))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        self._build_header(main)
        self._build_table(main)

    def _build_header(self, parent):
        """Bannière dessinée sur un Canvas : dégradé de la couleur de la pochette,
        grande pochette, titre géant, puis la rangée bouton ↓ + recherche."""
        c = tk.Canvas(parent, height=self.px(HEADER_H), bg=BG_PANEL,
                      highlightthickness=0, bd=0)
        c.grid(row=0, column=0, sticky="ew")
        self._hdr = c
        self._hdr_bg_item    = c.create_image(0, 0, anchor="nw")
        self._hdr_cover_item = c.create_image(0, 0, anchor="nw")
        self._hdr_kind_item  = c.create_text(0, 0, anchor="sw", fill=WHITE, font=(FONT, 10, "bold"))
        self._hdr_title_item = c.create_text(0, 0, anchor="sw", fill=WHITE)
        self._hdr_sub_item   = c.create_text(0, 0, anchor="sw", fill=WHITE, font=(FONT, 11))

        self._hdr_toggle = SyncToggle(c, size=self.px(48), on_change=self._on_header_toggle)
        Tooltip(self._hdr_toggle, "Inclure dans la synchro")
        self._hdr_toggle_item = c.create_window(0, 0, anchor="w", window=self._hdr_toggle)
        self._hdr_toggle_lbl  = c.create_text(0, 0, anchor="w", fill=TEXT_SUB, font=(FONT, 11))

        self._search = ctk.CTkEntry(c, width=280, height=36, corner_radius=18,
                                    placeholder_text="🔍  Rechercher dans la liste",
                                    fg_color="#2A2A2A", border_width=0, text_color=WHITE,
                                    placeholder_text_color=TEXT_DIM, font=(FONT, 12),
                                    bg_color=BG_PANEL)
        self._search_item = c.create_window(0, 0, anchor="e", window=self._search)
        self._search.bind("<KeyRelease>", self._on_search)
        self._search.bind("<Escape>", self._clear_search)

        c.bind("<Configure>", lambda _e: self._schedule_header_draw())

    def _on_header_toggle(self, on):
        if self._view_kind == "playlist" and self._active_preview:
            self._on_playlist_toggle(self._active_preview, on)

    def _schedule_header_draw(self):
        if self._hdr_after is None:
            self._hdr_after = self.after(20, self._draw_header)

    def _header_color_at(self, color, y, height):
        t = min(1.0, max(0.0, y / max(1, height - 1)))
        return mix(color, BG_PANEL, t ** 1.25)

    def _font(self, family, size, weight="normal"):
        key = (family, size, weight)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(self, family=family, size=size, weight=weight)
        return self._fonts[key]

    def _draw_header(self):
        self._hdr_after = None
        c, v = self._hdr, self._view
        w = max(c.winfo_width(), 300)
        H, B = self.px(HEADER_H), self.px(BANNER_H)
        pad = self.px(24)

        # Fond en dégradé (recalculé seulement si la taille ou la couleur change)
        key = (w, H, v["color"])
        if key != self._hdr_bg_key:
            self._hdr_bg_key = key
            column = Image.new("RGB", (1, H))
            column.putdata([hex_to_rgb(self._header_color_at(v["color"], y, H)) for y in range(H)])
            grad = column.resize((w, H), Image.NEAREST)
            # Coins du haut arrondis comme le panneau
            bg = Image.new("RGB", (w, H), BG_BASE)
            mask = Image.new("L", (w, H), 0)
            r = self.px(8)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, H + r), radius=r, fill=255)
            bg.paste(grad, (0, 0), mask)
            self._hdr_bg_photo = ImageTk.PhotoImage(bg)
            c.itemconfigure(self._hdr_bg_item, image=self._hdr_bg_photo)
            row_color = self._header_color_at(v["color"], B + (H - B) // 2, H)
            self._hdr_toggle.set_bg(row_color)
            self._search.configure(bg_color=row_color)

        # Grande pochette
        cs = self.px(COVER_HDR)
        top = B - cs - self.px(26)
        ckey = (id(v["cover"]), cs)
        if ckey != self._hdr_cover_key:
            self._hdr_cover_key = ckey
            self._hdr_cover_photo = ImageTk.PhotoImage(
                rounded(v["cover"].resize((cs, cs), Image.LANCZOS), self.px(6)))
            c.itemconfigure(self._hdr_cover_item, image=self._hdr_cover_photo)
        c.coords(self._hdr_cover_item, pad, top)

        # Textes : « Playlist », titre géant (taille adaptée à la largeur), sous-titre
        tx = pad + cs + self.px(24)
        avail = max(100, w - tx - pad)
        family = self._title_font_family
        weight = "normal" if family != FONT else "bold"
        title = v["title"]
        for size in (64, 54, 46, 38, 32, 26):
            font = self._font(family, size, weight)
            if font.measure(title) <= avail:
                break
        else:
            while len(title) > 4 and font.measure(title + "…") > avail:
                title = title[:-1]
            title += "…"
        sub_y = top + cs
        title_y = sub_y - self.px(30)
        c.itemconfigure(self._hdr_title_item, text=title, font=font)
        c.coords(self._hdr_title_item, tx - self.px(3), title_y)
        c.itemconfigure(self._hdr_kind_item, text=v["label"])
        c.coords(self._hdr_kind_item, tx, title_y - font.metrics("linespace") + self.px(8))
        c.itemconfigure(self._hdr_sub_item, text=v.get("subtitle", ""))
        c.coords(self._hdr_sub_item, tx, sub_y)

        # Rangée d'actions
        cy = B + (H - B) // 2
        if self._view_kind == "sync":
            c.itemconfigure(self._hdr_toggle_item, state="hidden")
            c.coords(self._hdr_toggle_lbl, pad, cy)
            label = "Tout ce qui est synchronisé : tes titres likés et les playlists avec ↓ en vert"
        else:
            c.itemconfigure(self._hdr_toggle_item, state="normal")
            c.coords(self._hdr_toggle_item, pad, cy)
            c.coords(self._hdr_toggle_lbl, pad + self.px(64), cy)
            pl = self._playlists.get(self._active_preview, {})
            if self._view_kind == "liked":
                label = "Toujours synchronisés"
            elif not pl.get("readable", True):
                label = (f"Playlist du compte « {pl.get('owner')} » : Spotify ne donne son "
                         f"contenu qu'à son propriétaire")
            elif self._active_preview in self._selected_pls:
                label = "Incluse dans la synchro"
            else:
                label = "Non synchronisée — clique sur ↓ pour l'ajouter"
        c.itemconfigure(self._hdr_toggle_lbl, text=label)
        c.coords(self._search_item, w - pad, cy)

    def _build_table(self, parent):
        area = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=0)
        area.grid(row=1, column=0, sticky="nsew", padx=(16, 6), pady=(0, 8))
        area.grid_rowconfigure(0, weight=1)
        area.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Sp.Treeview",
                        background=BG_PANEL, fieldbackground=BG_PANEL, foreground=WHITE,
                        borderwidth=0, relief="flat", rowheight=self.px(ROW_H),
                        font=(FONT, 11))
        style.configure("Sp.Treeview.Heading",
                        background=BG_PANEL, foreground=TEXT_SUB, font=(FONT, 10),
                        relief="flat", borderwidth=0, padding=(6, 8))
        style.map("Sp.Treeview.Heading",
                  background=[("active", BG_PANEL), ("pressed", BG_PANEL)],
                  foreground=[("active", WHITE)])
        style.map("Sp.Treeview",
                  background=[("selected", BG_ACTIVE)],
                  foreground=[("selected", WHITE)])
        style.layout("Sp.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        # Colonne #0 : numéro puis pochette, sans flèche d'arborescence
        style.layout("Sp.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.text", {"side": "left", "sticky": ""}),
            ("Treeitem.image", {"side": "left", "sticky": ""})]})])
        style.configure("Sp.Treeview.Item", padding=(self.px(4), 0, 0, 0))

        size = self.px(COVER_ROW)
        self._row_placeholder = ImageTk.PhotoImage(
            rounded(placeholder_cover(size), self.px(4)))

        self.tree = ttk.Treeview(
            area, columns=("titre", "artiste", "album", "duree", "statut"),
            show=("tree", "headings"), style="Sp.Treeview", selectmode="browse")
        self.tree.heading("#0", text="  #", anchor="w", command=lambda: self._sort_by(None))
        for col, label in self.HEADINGS.items():
            self.tree.heading(col, text=label, anchor="e" if col == "duree" else "w",
                              command=lambda c=col: self._sort_by(c))
        self.tree.column("#0",      width=self.px(110), minwidth=self.px(110), stretch=False)
        self.tree.column("titre",   width=self.px(300), minwidth=self.px(120), stretch=False)
        self.tree.column("artiste", width=self.px(200), minwidth=self.px(90),  stretch=False)
        self.tree.column("album",   width=self.px(200), minwidth=self.px(90),  stretch=False)
        self.tree.column("duree",   width=self.px(70),  anchor="e", stretch=False)
        self.tree.column("statut",  width=self.px(170), anchor="w", stretch=False)
        self.tree.bind("<Configure>", self._fit_columns)

        vsb = ctk.CTkScrollbar(area, command=self.tree.yview, fg_color=BG_PANEL,
                               button_color="#4D4D4D", button_hover_color="#6A6A6A")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.tree.tag_configure("ok",    foreground=WHITE)
        self.tree.tag_configure("dim",   foreground=TEXT_SUB)
        self.tree.tag_configure("busy",  foreground=GREEN)
        self.tree.tag_configure("fail",  foreground=RED)
        self.tree.tag_configure("hover", background=BG_HOVER)

        self._empty_lbl = ctk.CTkLabel(area, text="", font=(FONT, 13),
                                       text_color=TEXT_SUB, fg_color=BG_PANEL)

        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)
        self.tree.bind("<Double-1>", lambda e: self._show_in_explorer()
                       if self.tree.identify_row(e.y) else None)

        # Menu clic droit sur un titre
        self._row_menu = tk.Menu(self, tearoff=0, bg="#282828", fg=WHITE,
                                 activebackground="#3E3E3E", activeforeground=WHITE,
                                 bd=0, font=(FONT, 10))
        self._row_menu.add_command(label="🔁  Essayer un autre résultat YouTube",
                                   command=lambda: self._redownload_selected())
        self._row_menu.add_command(label="🔗  Télécharger depuis un lien…",
                                   command=lambda: self._redownload_from_link())
        self._row_menu.add_separator()
        self._row_menu.add_command(label="📂  Afficher dans l'explorateur",
                                   command=lambda: self._show_in_explorer())
        self.tree.bind("<Button-3>", self._on_row_right_click)

    # ── BARRE DU BAS ──────────────────────────────────────────────────────────
    def _build_bottom_bar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_BASE, corner_radius=0, height=92)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_rowconfigure(0, weight=1)
        bar.grid_columnconfigure(0, weight=1, uniform="side")
        bar.grid_columnconfigure(1, weight=2)
        bar.grid_columnconfigure(2, weight=1, uniform="side")

        # Gauche : titre en cours de téléchargement
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=16)
        self._now_img = ctk.CTkLabel(left, text="", width=56, height=56,
                                     image=self._ctk_image(self._placeholder_pil, 56))
        self._now_img.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        self._now_title = ctk.CTkLabel(left, text="", font=(FONT, 13),
                                       text_color=WHITE, anchor="w", height=20)
        self._now_title.grid(row=0, column=1, sticky="sw")
        self._now_artist = ctk.CTkLabel(left, text="", font=(FONT, 11),
                                        text_color=TEXT_SUB, anchor="w", height=18)
        self._now_artist.grid(row=1, column=1, sticky="nw")
        self._eq = Equalizer(left, self.px(14))
        self._eq.grid(row=0, column=2, sticky="s", padx=(12, 0), pady=(0, 4))
        self._set_now_idle()

        # Centre : ↻  ▶/■  📂  +  progression
        mid = ctk.CTkFrame(bar, fg_color="transparent")
        mid.grid(row=0, column=1)
        btns = ctk.CTkFrame(mid, fg_color="transparent")
        btns.pack()
        icon = dict(width=36, height=36, corner_radius=18, fg_color="transparent",
                    hover_color=BG_HOVER, text_color=TEXT_SUB,
                    text_color_disabled="#4D4D4D", font=(FONT, 17))
        self.retry_btn = ctk.CTkButton(btns, text="↻", command=self.start_retry_thread, **icon)
        self.retry_btn.pack(side="left", padx=14)
        Tooltip(self.retry_btn, "Réessayer les échecs")
        self.main_btn = PlayButton(btns, self.px(44), self._on_main_button)
        self.main_btn.pack(side="left", padx=14)
        self._main_tip = Tooltip(self.main_btn, "Synchroniser")
        folder_btn = ctk.CTkButton(btns, text="📂", command=self._open_mp3_folder, **icon)
        folder_btn.pack(side="left", padx=14)
        Tooltip(folder_btn, "Ouvrir le dossier des MP3")
        self.progress = BottomProgress(mid)
        self.progress.pack(pady=(6, 0))

        # Droite : état + compteurs + réglages
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=16)
        info = ctk.CTkFrame(right, fg_color="transparent")
        info.pack(side="left", padx=(0, 12))
        status_row = ctk.CTkFrame(info, fg_color="transparent")
        status_row.pack(anchor="e")
        self._dot_lbl = ctk.CTkLabel(status_row, text="●", font=(FONT, 10),
                                     text_color=TEXT_DIM, height=18)
        self._dot_lbl.pack(side="left", padx=(0, 6))
        self._status_text = ctk.CTkLabel(status_row, text="", font=(FONT, 12),
                                         text_color=TEXT_SUB, height=18)
        self._status_text.pack(side="left")
        self._stats_lbl = ctk.CTkLabel(info, text="", font=(FONT, 11),
                                       text_color=TEXT_DIM, height=18)
        self._stats_lbl.pack(anchor="e")
        gear = ctk.CTkButton(right, text="⚙", command=self.show_settings_dialog, **icon)
        gear.pack(side="left")
        Tooltip(gear, "Réglages")

    def _set_now_idle(self):
        self._now_img.configure(image=self._ctk_image(self._placeholder_pil, 56))
        self._now_title.configure(text="Aucun téléchargement en cours")
        self._now_artist.configure(text="Clique sur ▶ pour synchroniser")

    def _set_now_playing(self, t):
        pil = self._cover_pil.get(t['id'], self._placeholder_pil)
        self._now_img.configure(image=self._ctk_image(rounded(pil, 4), 56))
        self._now_title.configure(text=truncate(t['name'], 34))
        self._now_artist.configure(text=truncate(t['artist'], 40))

    def _open_mp3_folder(self):
        os.makedirs(self.mp3_folder, exist_ok=True)
        os.startfile(os.path.abspath(self.mp3_folder))

    # ─── Helpers ──────────────────────────────────────────────────────────────
    def _set_status(self, text, color=TEXT_SUB):
        """Utilisable depuis n'importe quel thread."""
        def apply():
            self._dot_lbl.configure(text_color=color)
            self._status_text.configure(text=truncate(text, 52))
        run_in_ui(apply)

    def _update_all_stats(self):
        tags = [self._state.get(t['id'], ("", "dim"))[1] for _, t in self._view_tracks]
        ok, fail = tags.count("ok"), tags.count("fail")
        todo = len(tags) - ok - fail
        parts = [f"{ok} téléchargé{'s' if ok > 1 else ''}"]
        if todo:
            parts.append(f"{todo} à télécharger")
        if fail:
            parts.append(f"{fail} échec{'s' if fail > 1 else ''}")
        self._stats_lbl.configure(text="  ·  ".join(parts) if tags else "")

    # ─── Collect tracks for sync ──────────────────────────────────────────────
    def _collect_all_tracks(self):
        """Renvoie (titres à synchroniser sans doublon, {nom de source: titres}, complet).
        (None, None, False) si une récupération a échoué. complet est faux si une
        playlist a été ignorée : sa liste manquante ferait supprimer des MP3 à tort."""
        self._set_status("Récupération des titres likés...", GOLD)
        liked = get_all_liked_tracks()
        if liked is None:
            return None, None, False
        all_tracks = list(liked)
        sources    = {LIKED_PLAYLIST_NAME: liked}
        seen = {t["id"] for t in all_tracks}
        complete = True
        for pl_id in list(self._selected_pls):
            self._set_status("Récupération des playlists...", GOLD)
            try:
                pl_tracks = self._get_playlist_tracks(pl_id)
            except Exception as e:
                print(f"Erreur playlist {pl_id} : {e}")
                return None, None, False
            if pl_tracks is None:
                print(f"Playlist {pl_id} ignorée (inaccessible).")
                complete = False
                continue
            sources[self._playlist_names.get(pl_id, pl_id)] = pl_tracks
            for t in pl_tracks:
                if t["id"] not in seen:
                    all_tracks.append(t)
                    seen.add(t["id"])
        return all_tracks, sources, complete

    def _write_playlists(self, sources):
        if not self.settings["write_playlists"]:
            return
        for name, tracks in sources.items():
            write_m3u(name, tracks, self.mp3_folder)

    # ─── Sync logic ───────────────────────────────────────────────────────────
    def _on_main_button(self):
        """Gros bouton ▶ : lance la synchro ; pendant la synchro il devient ■ (Stop)."""
        if self.is_sync_running:
            self.stop_sync()
        else:
            self.start_sync_thread()

    def start_sync_thread(self):
        if self.is_sync_running: return
        if not spotify_auth.sp:
            self.show_setup_dialog(); return
        self.is_sync_running = True   # posé ici pour bloquer un double-clic
        Thread(target=self.run_sync, daemon=True).start()

    def start_retry_thread(self):
        if self.is_sync_running: return
        self.is_sync_running = True
        Thread(target=self.run_retry, daemon=True).start()

    def stop_sync(self):
        """Bouton Stop : les téléchargements en cours sont coupés, les suivants ignorés."""
        self._stop_event.set()
        self.main_btn.set(enabled=False)
        self._set_status("Arrêt en cours...", GOLD)

    def _begin_job(self):
        """Début d'une synchro/réessai/retéléchargement (appelé depuis le thread)."""
        self._stop_event.clear()
        run_in_ui(self._set_running_ui, True)

    def _end_job(self):
        run_in_ui(self._set_running_ui, False)
        self.is_sync_running = False

    def _set_running_ui(self, running):
        self.main_btn.set(icon="stop" if running else "play", enabled=True)
        self._main_tip.text = "Arrêter" if running else "Synchroniser"
        self.retry_btn.configure(state="disabled" if running else "normal")
        self.progress.set_active(running)
        if running:
            self._eq.start()
        else:
            self._eq.stop()
            self._set_now_idle()

    def _set_track_state(self, track_id, text, tag):
        self._state[track_id] = (text, tag)
        if self.tree.exists(track_id):
            self.tree.set(track_id, "statut", text)
            self.tree.item(track_id, tags=self._tags_for(track_id))
        self._update_all_stats()

    def _track_finished(self):
        self.progress.set(self._done, self._total)
        self._update_all_stats()

    def process_one_track(self, t, url=None, skip=0):
        """Appelé depuis un thread de travail : l'UI passe par run_in_ui."""
        try:
            if self._stop_event.is_set():   # Stop cliqué : on laisse « En attente »
                return
            run_in_ui(self._set_track_state, t['id'], "↓  Téléchargement…", "busy")
            run_in_ui(self._set_now_playing, t)
            ok = download_track(t['name'], t['artist'], t['id'], t.get('duration', 0),
                                folder=self.mp3_folder, url=url, skip=skip,
                                stop_event=self._stop_event)
            if ok:
                add_metadata(track_filepath(t['name'], t['artist'], self.mp3_folder),
                             t['name'], t['artist'], t['album'], t['cover_url'])
                if save_downloaded_track(t['id'], t['name'], t['artist']):
                    run_in_ui(self._set_track_state, t['id'], "✓  Téléchargé", "ok")
                else:
                    # Le MP3 est là, mais sans la base il serait retéléchargé à chaque synchro
                    run_in_ui(self._set_track_state, t['id'], "⚠  Non enregistré", "fail")
                    self._set_status("❌ tracks.db n'est pas modifiable (lecture seule ?)", RED)
            elif self._stop_event.is_set():
                run_in_ui(self._set_track_state, t['id'], "⏹  Arrêté", "dim")
            else:
                run_in_ui(self._set_track_state, t['id'], "✕  Échec", "fail")
        except Exception as e:
            print(f"Erreur sur {t['name']} : {e}")
            run_in_ui(self._set_track_state, t['id'], "✕  Erreur", "fail")
        finally:
            with self._done_lock:
                self._done += 1
            run_in_ui(self._track_finished)

    def _confirm_delete(self, tracks):
        names = "\n".join(f"• {name} — {artist}" for _, name, artist in tracks[:10])
        if len(tracks) > 10:
            names += f"\n… et {len(tracks) - 10} autre(s)"
        return messagebox.askyesno(
            "Supprimer des MP3 ?",
            f"{len(tracks)} titre(s) ne sont plus dans tes likes ni dans les "
            f"playlists synchronisées :\n\n{names}\n\nSupprimer ces fichiers MP3 ?",
            icon="warning", parent=self)

    def _show_pending(self, tracks, to_download_ids):
        self._set_view("sync")
        self._fill_table(tracks, preview=False)
        self.progress.set(0, len(to_download_ids))

    def run_sync(self):
        self._begin_job()
        try:
            tracks, sources, complete = self._collect_all_tracks()
            if tracks is None:
                self._set_status("❌ Erreur Spotify : synchro annulée, rien n'a été supprimé", RED)
                return
            if self._stop_event.is_set():
                self._set_status("⏹ Synchro arrêtée", GOLD)
                return
            self._last_sources = sources

            to_delete = get_tracks_to_delete(t['id'] for t in tracks) if complete else []
            if to_delete and run_in_ui_wait(self._confirm_delete, to_delete):
                n = delete_tracks(to_delete, self.mp3_folder)
                print(f"{n} titre(s) supprimé(s).")

            # _is_present vérifie aussi le disque : un MP3 effacé à la main est retéléchargé
            to_download = [t for t in tracks if not self._is_present(t)]
            self._total = len(to_download)
            self._done  = 0
            run_in_ui_wait(self._show_pending, tracks, [t['id'] for t in to_download])
            self._set_status(f"Téléchargement de {self._total} titre(s)...", GREEN)
            with ThreadPoolExecutor(max_workers=3) as ex:
                list(ex.map(self.process_one_track, to_download))
            self._write_playlists(sources)   # même après un Stop : ne liste que les MP3 présents
            if self._stop_event.is_set():
                self._set_status("⏹ Synchro arrêtée", GOLD)
            else:
                self._set_status("Synchronisation terminée ✓", GREEN)
        except Exception as e:
            print(f"Erreur pendant la synchro : {e}")
            self._set_status("❌ Erreur pendant la synchro", RED)
        finally:
            self._end_job()

    def _failed_ids(self):
        return {tid for tid, (_, tag) in self._state.items() if tag == "fail"}

    def run_retry(self):
        self._begin_job()
        try:
            self._set_status("Réessai des échecs...", GOLD)
            failed_ids = run_in_ui_wait(self._failed_ids)
            if not failed_ids:
                self._set_status("Aucun échec à réessayer", GREEN)
                return
            # Les titres affichés dans le tableau suffisent : pas besoin de réinterroger Spotify
            to_retry    = [t for tid, t in self._tracks_by_id.items() if tid in failed_ids]
            self._total = len(to_retry)
            self._done  = 0
            run_in_ui(self.progress.set, 0, self._total)
            with ThreadPoolExecutor(max_workers=2) as ex:
                list(ex.map(self.process_one_track, to_retry))
            if self._last_sources:           # ajoute aux .m3u8 les titres récupérés
                self._write_playlists(self._last_sources)
            if self._stop_event.is_set():
                self._set_status("⏹ Réessai arrêté", GOLD)
            else:
                self._set_status("Réessai terminé ✓", GREEN)
        except Exception as e:
            print(f"Erreur pendant le réessai : {e}")
            self._set_status("❌ Erreur pendant le réessai", RED)
        finally:
            self._end_job()

    # ─── Clic droit sur un titre ──────────────────────────────────────────────
    def _on_row_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        busy = "disabled" if self.is_sync_running else "normal"
        self._row_menu.entryconfigure(0, state=busy)
        self._row_menu.entryconfigure(1, state=busy)
        try:
            self._row_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._row_menu.grab_release()

    def _selected_track(self):
        sel = self.tree.selection()
        return self._tracks_by_id.get(sel[0]) if sel else None

    def _redownload_selected(self):
        """Essaie le résultat YouTube suivant (utile quand le 1er n'est pas le bon morceau)."""
        t = self._selected_track()
        if not t or self.is_sync_running:
            return
        skip = self._skip_counts.get(t['id'], 0) + 1
        self._skip_counts[t['id']] = skip
        self._start_redownload(t, skip=skip)

    def _redownload_from_link(self):
        t = self._selected_track()
        if not t or self.is_sync_running:
            return
        dialog = ctk.CTkInputDialog(
            title="Télécharger depuis un lien",
            text=f"Colle le lien YouTube pour :\n{t['name']} — {t['artist']}")
        url = (dialog.get_input() or "").strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            messagebox.showerror("Lien invalide", "Le lien doit commencer par https://", parent=self)
            return
        self._start_redownload(t, url=url)

    def _start_redownload(self, t, url=None, skip=0):
        self.is_sync_running = True
        Thread(target=self._run_redownload, args=(t, url, skip), daemon=True).start()

    def _run_redownload(self, t, url, skip):
        self._begin_job()
        path   = track_filepath(t['name'], t['artist'], self.mp3_folder)
        backup = path + ".old"
        try:
            self._set_status(f"Retéléchargement : {t['name']}", BLUE)
            # On met l'ancien fichier de côté : il est restauré si le nouveau échoue
            if os.path.exists(path):
                os.replace(path, backup)
            self._total, self._done = 1, 0
            run_in_ui(self.progress.set, 0, 1)
            self.process_one_track(t, url=url, skip=skip)
            if os.path.exists(path):
                if os.path.exists(backup):
                    os.remove(backup)
                self._set_status("Retéléchargement terminé ✓", GREEN)
            else:
                if os.path.exists(backup):
                    os.replace(backup, path)
                    run_in_ui(self._set_track_state, t['id'], "✓  Téléchargé (ancien)", "ok")
                self._set_status("❌ Retéléchargement échoué, ancien fichier conservé", RED)
        except Exception as e:
            print(f"Erreur pendant le retéléchargement : {e}")
            self._set_status("❌ Erreur pendant le retéléchargement", RED)
        finally:
            self._end_job()

    def _show_in_explorer(self):
        t = self._selected_track()
        if not t:
            return
        path = os.path.abspath(track_filepath(t['name'], t['artist'], self.mp3_folder))
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", path])
        else:
            self._open_mp3_folder()

    # ─── Réglages ─────────────────────────────────────────────────────────────
    def show_settings_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Réglages")
        win.geometry("540x430")
        win.configure(fg_color=BG_CARD)
        win.attributes("-topmost", True)
        win.resizable(False, False)

        ctk.CTkLabel(win, text="Réglages",
                     font=FONT_TITLE, text_color=TEXT_HI).pack(pady=(28, 16))

        # Dossier des MP3
        ctk.CTkLabel(win, text="Dossier des MP3", font=FONT_LABEL,
                     text_color=TEXT_MID).pack(anchor="w", padx=40, pady=(0, 4))
        folder_row = ctk.CTkFrame(win, fg_color="transparent")
        folder_row.pack(padx=40, fill="x")
        folder_var = ctk.StringVar(value=os.path.abspath(self.mp3_folder))
        ctk.CTkEntry(folder_row, textvariable=folder_var, height=40, corner_radius=8,
                     fg_color=BG_SURFACE, border_color=BORDER, text_color=TEXT_HI,
                     font=FONT_LABEL, state="readonly").pack(side="left", fill="x", expand=True)

        def browse():
            chosen = filedialog.askdirectory(parent=win, initialdir=folder_var.get(),
                                             title="Choisir le dossier des MP3")
            if chosen:
                folder_var.set(os.path.abspath(chosen))
        ctk.CTkButton(folder_row, text="Parcourir…", width=100, height=40, corner_radius=20,
                      fg_color="transparent", hover_color=BG_SURFACE,
                      border_width=1, border_color=TEXT_DIM, text_color=TEXT_HI,
                      font=FONT_LABEL, command=browse).pack(side="left", padx=(8, 0))

        # Fichiers playlist
        m3u_var = ctk.BooleanVar(value=self.settings["write_playlists"])
        ctk.CTkCheckBox(win, text="Créer un fichier playlist (.m3u8) par playlist synchronisée",
                        variable=m3u_var, font=FONT_LABEL, text_color=TEXT_MID,
                        fg_color=ACCENT, hover_color=ACCENT_DIM,
                        border_color=TEXT_LO).pack(anchor="w", padx=40, pady=(18, 0))

        account_row = ctk.CTkFrame(win, fg_color="transparent")
        account_row.pack(anchor="w", padx=40, pady=(18, 0))
        small = dict(font=FONT_LABEL, height=36, corner_radius=18,
                     fg_color="transparent", hover_color=BG_SURFACE,
                     border_width=1, border_color=TEXT_DIM, text_color=TEXT_MID)
        ctk.CTkButton(account_row, text="👤  Changer de compte",
                      command=lambda: (win.destroy(), self._switch_account()),
                      **small).pack(side="left")
        ctk.CTkButton(account_row, text="🔑  Identifiants de l'appli…",
                      command=lambda: (win.destroy(), self.show_setup_dialog()),
                      **small).pack(side="left", padx=(8, 0))

        def save():
            new_folder = folder_var.get()
            old_folder = os.path.abspath(self.mp3_folder)
            if os.path.normcase(new_folder) != os.path.normcase(old_folder):
                if self.is_sync_running:
                    messagebox.showwarning("Synchro en cours",
                                           "Attends la fin de la synchro pour changer de dossier.",
                                           parent=win)
                    return
                self._change_mp3_folder(old_folder, new_folder, win)
            self.settings["write_playlists"] = m3u_var.get()
            save_settings(self.settings)
            win.destroy()
            self._set_status("Réglages enregistrés ✓", GREEN)

        ctk.CTkButton(win, text="Enregistrer",
                      font=FONT_BTN, height=48, corner_radius=24,
                      fg_color=ACCENT, hover_color=GREEN_HI, text_color=BG_DEEP,
                      command=save).pack(padx=40, pady=(28, 0), fill="x")

    def _switch_account(self):
        """Déconnecte le compte actuel et rouvre la connexion Spotify dans le navigateur."""
        if self.is_sync_running:
            messagebox.showwarning("Synchro en cours",
                                   "Attends la fin de la synchro pour changer de compte.", parent=self)
            return
        if not messagebox.askyesno(
                "Changer de compte",
                f"Te déconnecter du compte « {self._user_name} » ?\n\n"
                "Ton navigateur va s'ouvrir sur Spotify. Si le mauvais compte est déjà "
                "connecté, clique sur « Ce n'est pas vous ? » pour choisir l'autre.",
                parent=self):
            return
        if spotify_auth.switch_account() is None:
            self.show_setup_dialog()
            return
        self._user_id = None
        self._selected_pls.clear()     # les playlists cochées étaient celles de l'autre compte
        self._save_selected_playlists()
        self._set_status("Connexion à Spotify...", TEXT_SUB)
        self._fetch_user_info()        # recharge profil, playlists et titres likés

    def _change_mp3_folder(self, old_folder, new_folder, parent):
        """Change le dossier des MP3 et propose d'y déplacer les fichiers existants."""
        files = []
        for _, name, artist in get_downloaded_tracks():
            p = track_filepath(name, artist, old_folder)
            if os.path.exists(p):
                files.append(p)
        if os.path.isdir(old_folder):
            files += [os.path.join(old_folder, f) for f in os.listdir(old_folder)
                      if f.lower().endswith(".m3u8")]

        if files and messagebox.askyesno(
                "Déplacer les MP3 ?",
                f"Déplacer les {len(files)} fichier(s) existant(s) vers le nouveau dossier ?\n\n"
                f"Si tu refuses, ils resteront dans l'ancien dossier et seront "
                f"retéléchargés à la prochaine synchro.", parent=parent):
            os.makedirs(new_folder, exist_ok=True)
            errors = 0
            for p in files:
                try:
                    shutil.move(p, os.path.join(new_folder, os.path.basename(p)))
                except OSError as e:
                    print(f"Impossible de déplacer {p} : {e}")
                    errors += 1
            if errors:
                messagebox.showwarning("Déplacement incomplet",
                                       f"{errors} fichier(s) n'ont pas pu être déplacés "
                                       f"(ouverts dans un lecteur ?).", parent=parent)
        self.settings["mp3_folder"] = new_folder

    # ─── Config dialog ────────────────────────────────────────────────────────
    def show_setup_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Configuration API Spotify")
        win.geometry("480x520")
        win.configure(fg_color=BG_CARD)
        win.attributes("-topmost", True)
        win.resizable(False, False)

        ctk.CTkLabel(win, text="Connexion à Spotify",
                     font=FONT_TITLE, text_color=TEXT_HI).pack(pady=(32, 4))
        ctk.CTkLabel(win, text="Entre tes identifiants depuis le Dashboard Spotify",
                     font=FONT_LABEL, text_color=TEXT_MID).pack(pady=(0, 20))
        ctk.CTkButton(win, text="🌐  Ouvrir le Dashboard Spotify",
                      font=FONT_BTN, height=40, corner_radius=20,
                      fg_color="transparent", hover_color=BG_SURFACE,
                      border_width=1, border_color=TEXT_DIM, text_color=TEXT_HI,
                      command=lambda: webbrowser.open("https://developer.spotify.com/dashboard")
                      ).pack(padx=40, fill="x")

        ctk.CTkLabel(win, text="Client ID", font=FONT_LABEL,
                     text_color=TEXT_MID).pack(anchor="w", padx=40, pady=(20, 4))
        e_id = ctk.CTkEntry(win, placeholder_text="ex: 4b3c…", height=42,
                             corner_radius=8, fg_color=BG_SURFACE,
                             border_color=BORDER, text_color=TEXT_HI, font=FONT_LABEL)
        e_id.pack(padx=40, fill="x")

        ctk.CTkLabel(win, text="Client Secret", font=FONT_LABEL,
                     text_color=TEXT_MID).pack(anchor="w", padx=40, pady=(14, 4))
        e_sec = ctk.CTkEntry(win, placeholder_text="••••••••••••••••",
                              show="*", height=42, corner_radius=8,
                              fg_color=BG_SURFACE, border_color=BORDER,
                              text_color=TEXT_HI, font=FONT_LABEL)
        e_sec.pack(padx=40, fill="x")

        feedback = ctk.CTkLabel(win, text="", font=FONT_LABEL, text_color=RED)
        feedback.pack(pady=(10, 0))

        def save():
            feedback.configure(text="Connexion en cours...", text_color=GOLD)
            win.update()
            new_sp = spotify_auth.save_credentials(e_id.get().strip(), e_sec.get().strip())
            if new_sp:
                try:
                    new_sp.current_user()
                    win.destroy()
                    self._fetch_user_info()   # enchaîne playlists + titres likés
                except Exception:
                    feedback.configure(text="❌ Identifiants invalides", text_color=RED)
            else:
                feedback.configure(text="❌ Impossible de se connecter", text_color=RED)

        ctk.CTkButton(win, text="Valider et se connecter",
                      font=FONT_BTN, height=48, corner_radius=24,
                      fg_color=ACCENT, hover_color=GREEN_HI, text_color=BG_DEEP,
                      command=save).pack(padx=40, pady=25, fill="x")


if __name__ == "__main__":
    app = SpotifySyncApp()
    app.mainloop()
