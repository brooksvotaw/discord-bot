import requests
import os
import random
from dotenv import load_dotenv

class LastFMClient:
    def __init__(self, api_key=None):
        self.lastfm_api_key = api_key or os.getenv('LASTFM_API_KEY')
        self.lastfm_api_base = "http://ws.audioscrobbler.com/2.0/"
    
    def get_recommendations(self, mbid: str, artist: str, title: str, limit: int = 10) -> list[dict]:
        """Get track recommendations with automatic fallback"""
        
        # Try 1: MBID lookup
        if mbid:
            print(f"Trying MBID: {mbid}")
            recs = self._get_similar_tracks(mbid=mbid, limit=limit)
            if recs:
                print(f"✓ Found {len(recs)} recommendations via MBID")
                return recs
            print("✗ MBID failed")
        
        # Try 2: Artist + Track name
        print(f"Trying: {artist} - {title}")
        recs = self._get_similar_tracks(artist=artist, track=title, limit=limit)
        if recs:
            print(f"✓ Found {len(recs)} recommendations via track")
            return recs
        print("✗ Track lookup failed")
        
        # Try 3: Similar artists
        print(f"Trying artist: {artist}")
        recs = self._get_similar_artists(artist, limit=limit)
        if recs:
            print(f"✓ Found {len(recs)} recommendations from similar artists")
            return recs
        
        print("✗ No recommendations found")
        return []
    
    def _get_similar_tracks(self, mbid=None, artist=None, track=None, limit=10):
        """Get similar tracks from Last.fm"""
        params = {
            "method": "track.getsimilar",
            "api_key": self.lastfm_api_key,
            "format": "json",
            "limit": limit,
            "autocorrect": 1
        }
        
        if mbid:
            params["mbid"] = mbid
        else:
            params["artist"] = artist
            params["track"] = track
        
        try:
            response = requests.get(self.lastfm_api_base, params=params)
            response.raise_for_status()
            data = response.json()
            
            tracks = data.get("similartracks", {}).get("track", [])
            return [{
                "title": t.get("name"),
                "artist": t.get("artist", {}).get("name")
            } for t in tracks if t.get("name") and t.get("artist", {}).get("name")]
        
        except Exception:
            return []
    
    def _get_similar_artists(self, artist, limit=10):
        """Get similar artists and randomly select from their top tracks"""
        # Get 4 similar artists
        params = {
            "method": "artist.getsimilar",
            "artist": artist,
            "api_key": self.lastfm_api_key,
            "format": "json",
            "limit": 4,
            "autocorrect": 1
        }
        
        try:
            response = requests.get(self.lastfm_api_base, params=params)
            response.raise_for_status()
            data = response.json()
            
            similar_artists = data.get("similarartists", {}).get("artist", [])
            
            # Add the original artist to the list
            all_artists = [artist] + [a.get("name") for a in similar_artists if a.get("name")]
            
            print(f"  Fetching top tracks from {len(all_artists)} artists...")
            
            # Collect top tracks from all artists
            all_tracks = []
            for artist_name in all_artists:
                tracks = self._get_artist_top_tracks(artist_name, limit=20)
                all_tracks.extend(tracks)
                print(f"    {artist_name}: {len(tracks)} tracks")
            
            print(f"  Total track pool: {len(all_tracks)} tracks")
            
            # Randomly select tracks up to the limit
            if len(all_tracks) <= limit:
                return all_tracks
            
            selected = random.sample(all_tracks, limit)
            return selected
        
        except Exception as e:
            print(f"  Error in _get_similar_artists: {e}")
            return []
    
    def _get_artist_top_tracks(self, artist, limit=20):
        """Get the top tracks for an artist"""
        params = {
            "method": "artist.gettoptracks",
            "artist": artist,
            "api_key": self.lastfm_api_key,
            "format": "json",
            "limit": limit,
            "autocorrect": 1
        }
        
        try:
            response = requests.get(self.lastfm_api_base, params=params)
            response.raise_for_status()
            data = response.json()
            
            tracks = data.get("toptracks", {}).get("track", [])
            return [{
                "title": t.get("name"),
                "artist": t.get("artist", {}).get("name")
            } for t in tracks if t.get("name") and t.get("artist", {}).get("name")]
        
        except Exception:
            return []


# DEBUG
if __name__ == "__main__":
    load_dotenv()
    client = LastFMClient(os.getenv('LASTFM_API_KEY'))
    
    print("=" * 60)
    print("TEST 1: Try with MBID (should work)")
    print("=" * 60)
    recs = client.get_recommendations(
        artist="Radiohead",
        title="Creep",
        mbid="6b9c2fb0-0f4a-4d6f-b5b3-e5f4f5e5c5a5",  # fake MBID, will fail
        limit=10
    )
    print(f"\nResults: {len(recs)} tracks")
    for i, rec in enumerate(recs[:5], 1):
        print(f"  {i}. {rec['artist']} - {rec['title']}")
    
    print("\n" + "=" * 60)
    print("TEST 2: Try with artist + track (should work)")
    print("=" * 60)
    recs = client.get_recommendations(
        artist="Kendrick Lamar",
        title="HUMBLE.",
        mbid=None,
        limit=10
    )
    print(f"\nResults: {len(recs)} tracks")
    for i, rec in enumerate(recs[:5], 1):
        print(f"  {i}. {rec['artist']} - {rec['title']}")
    
    print("\n" + "=" * 60)
    print("TEST 3: Fallback to similar artists (obscure track)")
    print("=" * 60)
    recs = client.get_recommendations(
        artist="Big K.R.I.T.",
        title="Definitely Not A Real Song Name 12345",
        mbid=None,
        limit=25
    )
    print(f"\nResults: {len(recs)} tracks")
    for i, rec in enumerate(recs[:10], 1):
        print(f"  {i}. {rec['artist']} - {rec['title']}")
    
    print("\n" + "=" * 60)
    print("TEST 4: Another artist fallback test")
    print("=" * 60)
    recs = client.get_recommendations(
        artist="Anderson .Paak",
        title="Not A Real Song",
        mbid=None,
        limit=15
    )
    print(f"\nResults: {len(recs)} tracks")
    for i, rec in enumerate(recs, 1):
        print(f"  {i}. {rec['artist']} - {rec['title']}")