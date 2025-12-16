import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import random
import yt_dlp
import musicbrainz
import lastfm


### DEFINITIONS ###
# SONG DATA
class Song:
    def __init__(self, title, url, audio_url, duration, source="youtube"):
        self.title = title
        self.url = url
        self.audio_url = audio_url
        self.duration = duration
        self.requester = None # May want to change this later but will just manually set in the discord command to separate logic
        self.source = source
    
    @classmethod
    def from_youtube(cls, info):
        return cls(
            title=info['title'],
            url=info['webpage_url'],
            audio_url=info['url'],
            duration=info['duration'],
            # May want to change this later but will just manually set in the discord command to separate logic
            #requester=requester,
            source="youtube"
        )
    
    @classmethod
    # UNUSED
    def from_local_file(cls, filepath, metadata, requester):
        return cls(
            title=metadata['title'],
            url=filepath,
            audio_url=filepath,
            duration=metadata['duration'],
            requester=requester,
            source="local"
        )
    
    def __str__(self):
        return f"{self.title} ({self.source})"

# SERVER SPECIFIC DATA STRUCTURES
currently_playing = {}  # Current song
music_queues = {}  # Manually played queue
autoplay_queues = {}  # Autoplay queue - only loads 2 songs at a time
autoplay_enabled = {}  # Autoplay status
autoplay_recommendations = {}  # Autoplay recs - full list for autoplay queue to pull from


# YT_DLP
ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch3',
    'extract_flat': False,
    'no_warnings': True,
}

### BOT ###
# LOAD TOKEN FROM .ENV
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# CREATE BOT AND CLIENTS
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)
mb_client = musicbrainz.MBClient()
lastfm_client = lastfm.LastFMClient()

### METHODS ###
def get_queue(guild_id):
    if guild_id not in music_queues:
        music_queues[guild_id] = []
    return music_queues[guild_id]


def get_autoplay_queue(guild_id):
    if guild_id not in autoplay_queues:
        autoplay_queues[guild_id] = []
    return autoplay_queues[guild_id]


def get_autoplay_recommendations(guild_id):
    if guild_id not in autoplay_recommendations:
        autoplay_recommendations[guild_id] = []
    return autoplay_recommendations[guild_id]


def is_autoplay_enabled(guild_id):
    return autoplay_enabled.get(guild_id, False)


async def fetch_autoplay_recommendations(ctx, mbid, artist, track):
    if not mbid:
        return False
    
    # GET RECOMMENDATIONS FROM LAST FM
    recommendations = lastfm_client.get_recommendations(mbid, artist, track, 25)
    
    if not recommendations:
        return False
    
    random.shuffle(recommendations)
    
    # STORE RECOMMENDATIONS
    rec_list = get_autoplay_recommendations(ctx.guild.id)
    rec_list.clear()
    rec_list.extend(recommendations)
    
    print(f"Fetched {len(recommendations)} recommendations from Last.fm")
    return True


async def load_next_autoplay_song(ctx):
    rec_list = get_autoplay_recommendations(ctx.guild.id)
    autoplay_queue = get_autoplay_queue(ctx.guild.id)
    
    if not rec_list:
        print("No autoplay recommendations available")
        return None
    
    rec = rec_list.pop(0)
    rec_search = f"{rec['artist']} {rec['title']}"

    # QUERY YOUTUBE FOR REC AND ADD TO AUTOPLAY QUEUE
    yt_results = await query_youtube(rec_search)
    if yt_results:
        song = yt_results[0]
        song.requester = "Autoplay"
        autoplay_queue.append(song)

    # RETRY WITH NEXT SONG IF NOT FOUND
    else:
        load_next_autoplay_song(ctx)


async def query_youtube(search_query):
    try:
        # YOUTUBE SEARCH
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            yt_info = ydl.extract_info(search_query, download=False)

            # PLAYLIST
            if len(yt_info['entries']) > 3: # Not the best logic but I imagine any playlists linked will have more than 3 songs, ytsearch3 returns 3 entries always
                
                # RETRIVE ALL SONG DATA
                playlist = []
                for entry in yt_info['entries']:
                    if entry:
                        song = Song.from_youtube(entry)
                        playlist.append(song)
                
                return playlist

            # SINGLE VIDEO
            else:
                # FILTER OUT MUSIC VIDEOS
                filtered_entries = [
                    entry for entry in yt_info['entries']
                    if entry 
                    and '(clean)' not in entry.get('title', '').lower()
                    and 'clean version' not in entry.get('title', '').lower()
                    and 'album' not in entry.get('title', '').lower()
                    and (
                        # Allow if it contains "lyrics" or "lyric"
                        'lyric' in entry.get('title', '').lower()
                        or (
                            # Otherwise, exclude these patterns
                            'music video' not in entry.get('title', '').lower()
                            and 'official video' not in entry.get('title', '').lower()
                            and not ('official' in entry.get('title', '').lower() and 'video' in entry.get('title', '').lower())
                        )
                    )
                ]
                best_entry = filtered_entries[0] if filtered_entries else yt_info['entries'][0]
                song = Song.from_youtube(best_entry)
                return [song]
    except:
        return


async def play_song(ctx, song, from_autoplay=False):
    voice_client = ctx.voice_client
    audio_source = discord.FFmpegPCMAudio(
        song.audio_url,
        before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        options='-vn -af "loudnorm=I=-16:TP=-1.5:LRA=11"'
    )
    
    # CALLBACK - TRIGGERS AFTER PLAY_SONG FINISHES
    def after_playing(error):
        if error:
            create_embed("Error", error, discord.Color.red())
        
        queue = get_queue(ctx.guild.id)
        
        # PLAY NEXT SONG IN MANUAL QUEUE
        if queue:
            next_song = queue.pop(0)
            asyncio.run_coroutine_threadsafe(
                play_song(ctx, next_song), 
                bot.loop
            )

        # PLAY NEXT SONG IN AUTOPLAY QUEUE
        elif is_autoplay_enabled(ctx.guild.id):
            autoplay_queue = get_autoplay_queue(ctx.guild.id)
            if autoplay_queue:
                next_song = autoplay_queue.pop(0)
                
                # PLAY SONG
                asyncio.run_coroutine_threadsafe(
                    play_song(ctx, next_song), 
                    bot.loop
                )

                # SEND EMBED
                asyncio.run_coroutine_threadsafe(
                    ctx.send(embed=create_song_embed(ctx, next_song)),
                    bot.loop
                )

                # REPLENISH AUTOPLAY QUEUE
                if len(autoplay_queue) < 2:
                    asyncio.run_coroutine_threadsafe(
                        load_next_autoplay_song(ctx),
                        bot.loop
                    )
            else:
                currently_playing[ctx.guild.id] = None
        else:
            currently_playing[ctx.guild.id] = None
    
    voice_client.play(audio_source, after=after_playing)
    currently_playing[ctx.guild.id] = song


### MESSAGE EMBEDS
def create_embed(title, description=None, color=discord.Color.blue(), footer=None):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=footer)
    return embed


def create_song_embed(ctx, song, mb_results=None):
    
    queue = get_queue(ctx.guild.id)
    autoplay_enabled = is_autoplay_enabled(ctx.guild.id)
    from_autoplay = True if song.requester == "Autoplay" else False # Separating this out cause I may change how I determine

    embed = discord.Embed(
        title='Track Queued' if not from_autoplay else "Autoplaying Next Song",
        description=f'[{song.title}]({song.url})',
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    # MUSICBRAINZ MATCH
    if mb_results:
        embed.add_field(name="Identified As", value=f"`{mb_results['artist']} - {mb_results['track']}`", inline=False)
    
    # DURATION
    duration_str = f"{song.duration // 60}:{song.duration % 60:02d}"
    embed.add_field(name="Duration", value=duration_str, inline=True)
    
    # QUEUE POSITION AND TIME UNTIL
    if queue:
        embed.add_field(name="Position in Queue", value=f"#{len(queue)}", inline=True)

        # TIME UNTL PLAY
        time_until = sum(s.duration for s in queue[:-1])
        if ctx.guild.id in currently_playing and queue:
            time_until += currently_playing[ctx.guild.id].duration
            time_until_str = f"{time_until // 60}:{time_until % 60:02d}"
            embed.add_field(name="Estimated Start", value=time_until_str, inline=True)

    # AUTOPLAY STATUS - TODO ADD MORE INFO ON FAILURES
    if autoplay_enabled and not from_autoplay:
        response_text = "✅ Autoplaying from this track" if mb_results else "❌ Failed to identify artist/track"
        embed.add_field(name="Autoplay", value=response_text, inline=True)
    
    # REQUESTER
    embed.set_footer(text=f"Requested by {song.requester}" if not from_autoplay else "Provided by last.fm")
    
    return embed


def create_playlist_embed(playlist_title, song_count, first_song, duration):
    embed = discord.Embed(
        title="Playlist Queued",
        description=f"**{playlist_title}**",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    
    # TRACKS ADDED
    embed.add_field(name="Tracks Added", value=f"{song_count} songs", inline=True)

    # DURATION
    duration_str = f"{duration // 60}:{duration % 60:02d}"
    embed.add_field(name="Duration", value=duration_str, inline=True)
    
    # FIRST TRACK INFO
    embed.add_field(name="First Track", value=f"[{first_song.title}]({first_song.url})", inline=False)

    # REQUESTER
    embed.set_footer(text=f"Requested by {first_song.requester}")
    
    return embed


### EVENTS ###
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')


### COMMANDS ###
@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')


# TODO SEND EMBED INSTEAD OF MESSAGE?
@bot.command()
async def disconnect(ctx):
    if ctx.voice_client:
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        
        queue = get_queue(ctx.guild.id)
        queue.clear()
        autoplay_queue = get_autoplay_queue(ctx.guild.id)
        autoplay_queue.clear()
        
        if ctx.guild.id in currently_playing:
            currently_playing[ctx.guild.id] = None
        
        await ctx.voice_client.disconnect()
        await ctx.send("DISCONNECTING! LATER DOOOOOOOOG!")
    else:
        await ctx.send("I'm not in a voice channel!")


@bot.command()
async def play(ctx, *, search):
    # CONNECT TO VOICE
    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel!")
        return
    
    voice_channel = ctx.author.voice.channel
    if not ctx.voice_client:
        await voice_channel.connect(self_deaf=True)

    queue = get_queue(ctx.guild.id)

    # QUERY MUSICBRAINZ TO GET METADATA
    mb_results = None
    if not ('youtube.com' in search or 'youtu.be' in search):
        mb_results = await mb_client.song_search_async(search)
        # UPDATE SEARCH WITH ACCURATE ARTIST AND TITLE
        if mb_results:
            search = f'{mb_results['artist']} - {mb_results['track']}'

    # QUERY YOUTUBE
    yt_results = await query_youtube(search)
    if not yt_results:
        await ctx.send(embed=create_embed("Error", "No song found for that request!", discord.Color.red()))
        return
    
    # PLAYLIST
    if len(yt_results) > 1:
        first_song = None
        songs_added = 0
        total_duration = 0

        # ADD SONGS
        for song in yt_results:
            song.requester = ctx.author.name # Don't love setting this here but makes logic simpler and not require passing ctx around
            songs_added += 1
            total_duration += song.duration
            if not first_song:
                first_song = song
            queue.append(song)

        # SEND EMBED - TODO FIGURE OUT A WAY TO CLEANLY PASS THE TITLE
        await ctx.send(embed=create_playlist_embed("PLAYLIST TITLE PLACEHOLDER", songs_added, first_song, total_duration))

        # PLAY SONG IF NOTHING PLAYING
        if not ctx.voice_client.is_playing() and queue:
            song = queue.pop(0)
            await play_song(ctx, song)

    # SINGLE SONG
    else:
        song = yt_results[0]
        song.requester = ctx.author.name # Don't love setting this here but makes logic simpler and not require passing ctx around

        # PLAY SONG / ADD TO QUEUE
        if not ctx.voice_client.is_playing():
            await play_song(ctx, song)
        else:
            queue.append(song)

        # SEND EMBED
        await ctx.send(embed=create_song_embed(ctx, song, mb_results))
    
        # AUTOPLAY
        if mb_results and is_autoplay_enabled(ctx.guild.id):
            # GRAB RECS FROM LAST FM
            success = await fetch_autoplay_recommendations(ctx, mb_results['mbid'], mb_results['artist'], mb_results['track'])
            if success:

                # CLEAR CURRENT AUTOPLAY QUEUE
                autoplay_queue = get_autoplay_queue(ctx.guild.id)
                autoplay_queue.clear()
                
                # LOAD TWO AUTOPLAY SONGS TO START - KEEPS BUFFER
                for _ in range(2):
                    await load_next_autoplay_song(ctx)
                
                print(f"Queued initial autoplay songs")


@bot.command()
async def skip(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        await ctx.send("Nothing is playing!")
        return
    
    
    current = currently_playing.get(ctx.guild.id) # Cache current song to reference in embed
    queue = get_queue(ctx.guild.id)
    autoplay_queue = get_autoplay_queue(ctx.guild.id)  # AUTOPLAY: Get autoplay queue
    autoplay_recs = get_autoplay_recommendations(ctx.guild.id)  # AUTOPLAY: Get recommendations
    
    # BUILD EMBED
    embed = create_embed("Track Skipped", f"~~[{current.title}]({current.url})~~")
    
    # SHOW NEXT IN QUEUE
    if queue:
        next_song = queue[0]
        embed.add_field(
            name="Up Next", 
            value=f"[{next_song.title}]({next_song.url})",
            inline=False
        )
    # SHOW NEXT IN AUTOPLAY QUEUE - TODO THIS TECHNICALLY WILL SHOW THE NEXT SONG TWICE, HERE AND VIA CALLBACK
    elif is_autoplay_enabled(ctx.guild.id) and autoplay_queue:
        next_song = autoplay_queue[0]
        embed.add_field(
            name="Up Next (Autoplay)", 
            value=f"[{next_song.title}]({next_song.url})",
            inline=False
        )
    else:
        embed.add_field(name="Up Next", value="Queue is empty", inline=False)
    
    # SKIP SONG VIA CALLBACK
    ctx.voice_client.stop()

    # SEND EMBED
    await ctx.send(embed=embed)


@bot.command()
async def queue(ctx):
    queue = get_queue(ctx.guild.id)
    autoplay_queue = get_autoplay_queue(ctx.guild.id)
    autoplay_recs = get_autoplay_recommendations(ctx.guild.id)
    
    # ERROR HANDLING
    if not queue and not autoplay_queue:  # AUTOPLAY: Check both queues
        await ctx.send(embed=create_embed("Invalid Command", "The queue is empty", discord.Color.red()))
        return
    
    # BUILD QUEUE
    queue_text = ""
    total_duration = 0

    # DISPLAY CURRENTLY PLAYING SONG
    current = currently_playing.get(ctx.guild.id)
    if current:
        duration_str = f"{current.duration // 60}:{current.duration % 60:02d}"
        queue_text += f"**Now Playing**\n[{current.title}]({current.url}) `[{duration_str}]`\n"

    
    # QUEUE
    if queue:
        queue_text += "\n**__Queue__**\n"
    for i, song in enumerate(queue, 1):
        duration_str = f"{song.duration // 60}:{song.duration % 60:02d}"
        queue_text += f"**{i}.** [{song.title}]({song.url}) `[{duration_str}]`\n"
        total_duration += song.duration

    total_str = f"{total_duration // 60}:{total_duration % 60:02d}"
    
    # AUTOPLAY QUEUE
    if is_autoplay_enabled(ctx.guild.id) and (autoplay_queue or autoplay_recs):
        queue_text += "\n**__Autoplay Queue (Next 5)__**\n"
        
        # SONGS ALREADY RETRIEVED FROM YOUTUBE
        for i, song in enumerate(autoplay_queue[:5], 1):
            duration_str = f"{song.duration // 60}:{song.duration % 60:02d}"
            queue_text += f"**A{i}.** [{song.title}]({song.url}) `[{duration_str}]`\n"
        
        # UPCOMING RECOMMENDATIONS
        remaining_slots = 5 - len(autoplay_queue)
        if remaining_slots > 0 and autoplay_recs:
            for i, rec in enumerate(autoplay_recs[:remaining_slots], len(autoplay_queue) + 1):
                queue_text += f"**A{i}.** {rec['artist']} - {rec['title']} `[pending]`\n"
    
    # FOOTER
    footer_text = f"{len(queue)} songs • Total duration: {total_str}"
    if is_autoplay_enabled(ctx.guild.id):
        total_autoplay = len(autoplay_queue) + len(autoplay_recs)
        if total_autoplay > 0:
            footer_text += f" • {total_autoplay} autoplay songs available"
    
    # SEND EMBED
    await ctx.send(embed=create_embed('Current Queue', queue_text, discord.Color.purple(), footer_text))


@bot.command()
async def shuffle(ctx):
    queue = get_queue(ctx.guild.id)
    
    # ERROR HANDLING
    error_text = None
    if not queue:
        error_text = "The queue is empty - there is nothing to shuffle"

    if len(queue) < 2:
        error_text = f"The queue is too small to shuffle",
    

    if error_text:
        await ctx.send(embed=create_embed("Invalid Command", error_text, discord.Color.red()))
        return
    
    # SHUFFLE QUEUE
    random.shuffle(queue)
    
    # CREATE PREVIEW
    preview = "\n".join([f"**{i+1}.** {song.title}" for i, song in enumerate(queue[:5])])
    if len(queue) > 5:
        preview += f"\n*...and {len(queue) - 5} more*"
    
    # SEND EMBED
    await ctx.send(embed=create_embed("Queue Shuffled", preview, discord.Color.blue(), f"Shuffled {len(queue)} songs"))


@bot.command()
async def clear(ctx):
    queue = get_queue(ctx.guild.id)
    
    # ERROR HANDLING
    if not queue:
        await ctx.send(embed=create_embed("Invalid Command", "The queue is empty - there is nothing to clear", discord.Color.red()))
        return
    
    # CLEAR QUEUE
    song_count = len(queue)
    queue.clear()
    
    # SEND EMBED
    await ctx.send(embed=create_embed("Queue Cleared", f"Removed {song_count} song{'s' if song_count != 1 else ''} from the queue"))


@bot.command()
async def remove(ctx, position: int):
    queue = get_queue(ctx.guild.id)
    
    # ERROR HANDLING
    error_text = None
    if not queue:
        error_text = "The queue is empty - there is nothing to bump"

    if position < 1 or position > len(queue):
        error_text = f"Please choose a number between 1 and {len(queue)}",
    

    if error_text:
        await ctx.send(embed=create_embed("Invalid Command", error_text, discord.Color.red()))
        return
    
    # REMOVE SONG
    removed_song = queue.pop(position - 1)
    
    # SEND EMBED
    await ctx.send(embed=create_embed("Song Removed", f"~~[{removed_song.title}]({removed_song.url})~~", discord.Color.blue(), f"{len(queue)} song{'s' if len(queue) != 1 else ''} remaining in queue"))


@bot.command()
async def bump(ctx, position: int):
    queue = get_queue(ctx.guild.id)
    
    # ERROR HANDLING
    error_text = None
    if not queue:
        error_text = "The queue is empty - there is nothing to bump"

    if position < 2 or position > len(queue):
        error_text = f"Please choose a number between 2 and {len(queue)}",
    

    if error_text:
        await ctx.send(embed=create_embed("Invalid Command", error_text, discord.Color.red()))
        return

    # BUMP SONG
    bumped_song = queue.pop(position - 1)
    queue.insert(0, bumped_song)
    
    # SEND EMBED
    await ctx.send(embed=create_embed("Song Bumped to Top", f"[{bumped_song.title}]({bumped_song.url})"))


@bot.command()
async def autoplay(ctx):
    current_status = is_autoplay_enabled(ctx.guild.id)
    autoplay_enabled[ctx.guild.id] = not current_status
    
    new_status = "ENABLED" if not current_status else "DISABLED"
    status_emoji = "✅" if not current_status else "❌"
    
    await ctx.send(embed=create_embed("Autoplay Toggled", f"Autoplay is now **{new_status}** {status_emoji}", discord.Color.purple()))

@bot.command()
async def help(ctx):
    embed = create_embed("BIG CHINA Command List", "Available commands:", color=discord.Color.gold())
    
    embed.add_field(
        name="/autoplay",
        value="Toggle autoplay on/off. If enabled, /played tracks able to be identified will create an autoplay queue to continue playing when the main queue is empty",
        inline=False
    )

    embed.add_field(
        name="/bump <position>",
        value="Move a song to the top of the queue",
        inline=False
    )

    embed.add_field(
        name="/clear",
        value="Clear the entire queue",
        inline=False
    )

    embed.add_field(
        name="/disconnect",
        value="Disconnect bot from voice channel",
        inline=False
    )

    embed.add_field(
        name="/play <song/url>",
        value="Play a song or add it to queue",
        inline=False
    )

    embed.add_field(
        name="/queue",
        value="Show the current queue and autoplay queue (if enabled)",
        inline=False
    )

    embed.add_field(
        name="/remove <position>",
        value="Remove a song at the specified position",
        inline=False
    )

    embed.add_field(
        name="/shuffle",
        value="Shuffle the queue",
        inline=False
    )
    
    embed.add_field(
        name="/skip",
        value="Skip the current song",
        inline=False
    )
    
    embed.set_footer(text="Use / before each command")
    
    await ctx.send(embed=embed)

bot.run(TOKEN)