import musicbrainzngs
from musicbrainzngs import NetworkError, WebServiceError
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fuzzywuzzy import fuzz
import time
import os
import re


class MBClient:
    def __init__(self, app=None, version=None, contact=None):
        # Use env vars if not provided
        app = app or os.getenv('MUSICBRAINZ_APP_NAME', 'DiscordMusicBot')
        version = version or os.getenv('MUSICBRAINZ_VERSION', '1.0')
        contact = contact or os.getenv('MUSICBRAINZ_CONTACT', 'noreply@example.com')
        musicbrainzngs.set_useragent(app, version, contact)
        musicbrainzngs.set_rate_limit(2.0)
        self.executor = ThreadPoolExecutor(max_workers=3)


    async def song_search_async(self, query_string, score_threshold=75, limit=3, max_retries=3):
        # ASYNC WRAPPER FOR SEARCH TO RUN BLOCKING CODE IN A THREAD
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self.song_search,
            query_string,
            score_threshold,
            limit,
            max_retries
        )

    
    def song_search(self, query_string, score_threshold=75, limit=3, max_retries=3):
        print(f'Searching MusicBrainz for "{query_string}"...')
        artist = None
        matched_result = None
        for attempt in range(max_retries):
            try:
                # SEARCH FOR ARTIST
                if not artist:
                    artist = musicbrainzngs.search_artists(query_string, 1)['artist-list'][0]['name']
                    print(f'Artist found! "{artist}"')

                # SEARCH FOR TOP RECORDINGS FOR FOUND ARTIST
                recording_list = musicbrainzngs.search_recordings(f'{query_string} AND artist:"{artist}"', limit)['recording-list']

                # PARSE RECORDINGS DATA
                top_tracks = []
                for recording in recording_list:
                    title = recording.get('title', 'Unknown')
                    mbid = recording.get('id')
                    top_tracks.append({'title': title, 'mbid': mbid})
                
                # SCORE RESULTS - RETURN HIGHEST ABOVE THRESHOLD
                score = score_threshold
                for track_info in top_tracks:
                    track = track_info['title']
                    mb_match_string = f'{artist} - {track}'
                    track_score = fuzz.token_sort_ratio(self._clean_text(query_string), self._clean_text(mb_match_string))
                    if track_score > score:
                        score = track_score
                        matched_result = {
                            'artist': artist,
                            'track': track,
                            'mbid': track_info['mbid']
                        }

                if matched_result:
                    print(f"Match found! {matched_result['artist']} - {matched_result['track']} (MBID: {matched_result['mbid']})")
                else:
                    print('No matches found via MusicBrainz')

                return matched_result
            
            # NETWORK ERROR HANDLING - MUSICBRAINZ IS TEMPERAMENTAL
            except NetworkError as e:
                print(f"Network error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    print("Max retries reached")
                    return None
                    
            except WebServiceError as e:
                print(f"MusicBrainz API error: {e}")
                return None
                
            except Exception as e:
                print(f"Unexpected error: {e}")
                return None
        
        return None
    
    def _clean_text(self, text):
        text = text.lower()
        text = re.sub(r'[.,!?\'"()[\]{}]', '', text) # Remove common punctuation
        text = text.replace('&', 'and') # Swap ampersands
        text = re.sub(r'\s+', ' ', text) # Remove multiple spaces
        text = text.strip()
        return text


# DEBUG
# mb_client = MBClient('GupgradeMusicBot', '1.0', 'guptohkl@proton.me')
# results = mb_client.song_search("artist track")
# print(results)