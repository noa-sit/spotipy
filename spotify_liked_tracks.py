import spotify_auth

def get_all_liked_tracks():
    """Récupère les titres likés avec les URLs des pochettes."""
    client = spotify_auth.sp 
    if client is None: return []

    all_tracks = []
    limit = 50
    offset = 0

    while True:
        try:
            results = client.current_user_saved_tracks(limit=limit, offset=offset)
            tracks = results['items']
            if not tracks: break

            for item in tracks:
                track = item['track']
                all_tracks.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artist': track['artists'][0]['name'],
                    'album': track['album']['name'],
                    'cover_url': track['album']['images'][0]['url']
                })
            offset += limit
            if len(tracks) < limit: break
        except Exception as e:
            print(f"Erreur API Spotify : {e}")
            break
    return all_tracks
