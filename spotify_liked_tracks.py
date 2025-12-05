from spotify_auth import sp  # Importe le client Spotify initialisé
# Importé pour des raisons de test ou d'intégration (non nécessaire pour get_all_liked_tracks elle-même)
# from mp3_manager import is_track_in_db 

def get_all_liked_tracks():
    """
    Récupère TOUS les titres likés de l'utilisateur en gérant la pagination de l'API Spotify.

    :return: Une liste de dictionnaires, chacun contenant les informations clés du titre.
             Ex: [{'id': '...', 'name': '...', 'artist': '...', 'album': '...'}]
    """
    if sp is None:
        print("Erreur: Le client Spotify n'est pas initialisé (problème d'authentification ou de clés).")
        return []

    all_tracks = []
    limit = 50  # Nombre de titres par requête (maximum autorisé par l'API Spotify)
    offset = 0  # Décalage pour la pagination

    while True:
        try:
            # Récupérer une page de résultats (chansons sauvegardées par l'utilisateur)
            results = sp.current_user_saved_tracks(limit=limit, offset=offset)
            tracks = results['items']

            # Si aucun résultat, ou si l'on a atteint la fin, on arrête la boucle
            if not tracks:
                break

            # Traiter et ajouter les titres à la liste globale
            for item in tracks:
                track = item['track']
                # On s'assure d'avoir l'ID, le nom, et le nom du premier artiste
                if track and track.get('id') and track.get('artists'):
                    all_tracks.append({
                        'id': track['id'],
                        'name': track['name'],
                        'artist': track['artists'][0]['name'],
                        'album': track['album']['name']
                    })

            # Passer à la page suivante
            offset += limit
            
            # Si le nombre total d'éléments dans la page est inférieur à la limite, c'est la dernière page
            if len(tracks) < limit:
                break
                
        except Exception as e:
            print(f"Erreur lors de la récupération des titres likés : {e}")
            break # Arrêter en cas d'erreur API

    return all_tracks

# Fonction de test, si nécessaire
def print_all_liked_tracks():
    """Affiche TOUS les titres likés."""
    tracks = get_all_liked_tracks()
    print(f"\n--- {len(tracks)} Titres Likés Récupérés ---")
    for i, track in enumerate(tracks):
        # Vous pouvez décommenter la ligne suivante si vous importez is_track_in_db
        # already_downloaded = is_track_in_db(track['id'])
        # status = "✅ Téléchargé" if already_downloaded else "❌ Non téléchargé"
        status = "❓ Statut Inconnu (Test)"
        
        print(f"[{i+1}] {track['name']} par {track['artist']} | ID: {track['id']} | {status}")
        
    if not tracks:
        print("Aucun titre trouvé ou la connexion a échoué.")


if __name__ == "__main__":
    # Ceci tentera de récupérer et d'afficher les titres après authentification
    print_all_liked_tracks()