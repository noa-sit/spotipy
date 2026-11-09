import spotify_auth

def get_all_liked_tracks():
    """Récupère les titres likés avec les URLs des pochettes.
    Retourne None si la récupération a échoué (liste incomplète)."""
    client = spotify_auth.sp
    if client is None: return None

    all_tracks = []
    limit = 50
    offset = 0

    while True:
        try:
            results = client.current_user_saved_tracks(limit=limit, offset=offset)
            tracks = results['items']
            if not tracks: break

            for item in tracks:
                track = item.get('track')
                if not track or not track.get('id'):
                    continue
                images = track['album'].get('images') or []
                all_tracks.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artist': track['artists'][0]['name'],
                    'album': track['album']['name'],
                    'cover_url': images[0]['url'] if images else '',
                    'duration': (track.get('duration_ms') or 0) // 1000,
                })
            offset += limit
            if len(tracks) < limit: break
        except Exception as e:
            print(f"Erreur API Spotify : {e}")
            return None
    return all_tracks