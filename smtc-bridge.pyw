# Versioning
APP_VERSION = "1.0.0"
DEVELOPER = "nutty"



###############
### IMPORTS ###
###############

import datetime
import traceback
import asyncio
import json
import base64
import threading
import os
import sys
import psutil
import tempfile
import atexit
import pystray
import webbrowser
import configparser
import time
import platform
import socket
import hashlib
from PIL import Image
from flask import Flask, jsonify
from flask_cors import CORS
from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SMTC
from winsdk.windows.storage.streams import DataReader
from plyer import notification
import winsdk._winrt as winrt
from collections import OrderedDict



# IMPORTANT SHIT STARTS HERE

def log_crash(e):
    # 1. Ensure the 'logs' folder exists
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 2. Create timestamped filename: yyyy-MM-dd hh-mm-ss
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    filename = os.path.join(log_dir, f"crash_{timestamp}.txt")
    
    # 3. Write the error log
    with open(filename, "w", encoding="utf-8") as f:
        f.write("--- CRASH DETECTED ---\n")
        f.write(f"Time: {timestamp}\n")
        f.write(str(e) + "\n\n")
        f.write(traceback.format_exc())

    # 4. Keep only the 10 most recent logs
    # Get all .txt files in the log directory
    files = [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith(".txt")]
    
    # Sort by modification time (oldest first)
    files.sort(key=os.path.getmtime)
    
    # If we have more than 10, delete the oldest
    while len(files) > 10:
        oldest_file = files.pop(0)
        try:
            os.remove(oldest_file)
        except OSError:
            pass # Ignore errors if file is locked or already gone

try:
    #############################
    ### SINGLE INSTANCE CHECK ###
    #############################

    def is_already_running():
        # Use the system temp directory
        lockfile = os.path.join(tempfile.gettempdir(), 'smtc_bridge.lock')
        
        # Check if the lockfile already exists
        if os.path.exists(lockfile):
            try:
                with open(lockfile, 'r') as f:
                    pid = int(f.read())
                # Check if that PID is actually still running
                if psutil.pid_exists(pid):
                    return True # A real instance is running
                else:
                    os.remove(lockfile) # Stale lock from a crash, clean it up
            except (ValueError, PermissionError):
                # If the file is garbled or we can't read it, treat it as a stale lock
                os.remove(lockfile)
                
        # No instance found, write our PID to the lockfile
        try:
            with open(lockfile, 'w') as f:
                f.write(str(os.getpid()))
        except IOError:
            pass # Could not write lockfile, but let's proceed anyway
            
        # Register a cleanup function to delete the file when the app closes
        atexit.register(lambda: os.remove(lockfile) if os.path.exists(lockfile) else None)
        
        return False

    if is_already_running():
        print("Another instance is already running. Exiting...")
        sys.exit()



    ######################
    ### INITIALIZATION ###
    ######################

    def get_resource_path(relative_path):
        """ Get absolute path to resource, works for dev and for PyInstaller """
        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def load_settings():
        config = configparser.ConfigParser()
        config['SERVER'] = {'Host': '127.0.0.1', 'Port': '5000'}
        
        # Ensure settings.ini is looked for in the executable's directory
        exe_dir = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__)
        ini_path = os.path.join(exe_dir, 'settings.ini')
        
        if os.path.exists(ini_path):
            config.read(ini_path)
        else:
            with open(ini_path, 'w') as f:
                config.write(f)
        return config

    settings = load_settings()
    HOST = settings.get('SERVER', 'Host')
    PORT = settings.getint('SERVER', 'Port')

    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    DISPLAY_HOST = get_local_ip() if HOST == "0.0.0.0" else HOST

    app = Flask(__name__)
    CORS(app)

    # Create a local temp directory for thumbnails
    THUMB_DIR = os.path.join(tempfile.gettempdir(), 'smtc_bridge_thumbs')
    if not os.path.exists(THUMB_DIR):
        os.makedirs(THUMB_DIR)



    ######################
    ### CORE FUNCTIONS ###
    ######################

    # Cache variables for the SMTC manager and rate limiting
    smtc_manager = None
    last_execution_time = 0.0
    last_payload = None
    
    # Thumbnail cache to avoid reprocessing the same artwork repeatedly
    MAX_CACHE_SIZE = 50               # Maximum number of unique thumbnails to cache
    thumb_cache = OrderedDict()

    async def get_all_media_info():            
        try:
            # We will cache the last execution time and payload to avoid redundant parsing if requests flood in faster than 0.5 seconds.
            current_time = time.time()
            global smtc_manager, last_execution_time, last_payload, thumb_cache

            # If requests flood in faster than 0.5 seconds, return the cached result 
            # to completely spare the CPU from redundant parsing.
            if (current_time - last_execution_time) < 0.5 and last_payload:
                # print("Using cached media info.")
                return last_payload
            # else:
            #     print("Fetching fresh media info.")
            
            last_execution_time = current_time

            # Instantiate the SMTC manager -> This allows use to "talk" to the Windows Media API
            # Reuse the manager if we already have it, otherwise request it once
            if not smtc_manager:
                print("Instantiating new SMTC manager...")
                smtc_manager = await SMTC.request_async()

            manager = smtc_manager
            
            # If it returns null, then no media is playing, or something fucked up and I have no
            # idea what to do, so just return an empty session list
            if not manager:
                return {"current_session_id": None, "sessions": []}

            # current_focused:  This is the session for the current media player -> Whatever Windows deems is "in focus"
            #                   will be the current session.
            # all_sessions:     We will also get all sessions, not just the current session.
            #                   This will provide the client with all the necessary info if they want to target just one application.
            # We will store the SourceAppUserModelId, which we all add to the final payload.
            # For all available properties/methods/events, see the official docs:
            # https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession?view=winrt-28000
            
            # Try to pull sessions using the cached manager
            try:
                current_focused = manager.get_current_session()
                all_sessions = manager.get_sessions()
            except Exception:
                # If the COM context dropped or invalidated, reset it and retry once
                print("Instantiating new SMTC manager...")
                smtc_manager = await SMTC.request_async()
                manager = smtc_manager
                if not manager:
                    return {"current_session_id": None, "sessions": []}
                current_focused = manager.get_current_session()
                all_sessions = manager.get_sessions()

            current_session_id = current_focused.source_app_user_model_id if current_focused else None

            # We will store all the session info in a list of dictionaries, which we will return as JSON
            sessions_list = []

            # We will not iterate over all the sessions, and grab all the available info
            for session in all_sessions:
                # Get all the available info for each session object:
                # For all available properties/methods/events, see the official docs:
                # https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession?view=winrt-28000
                app_id = session.source_app_user_model_id
                raw_playback = session.get_playback_info()
                raw_timeline = session.get_timeline_properties()
                raw_media = await session.try_get_media_properties_async()

                # Playback info
                # https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionplaybackinfo?view=winrt-28000
                playback_data = {
                    # AutoRepeatMode: Specifies the repeat mode of the session.
                    "AutoRepeatMode": raw_playback.auto_repeat_mode.value if (raw_playback and raw_playback.auto_repeat_mode) else 0,
                    
                    # IsShuffleActive: Specifies whether the session is currently playing content in a shuffled order.
                    "IsShuffleActive": raw_playback.is_shuffle_active if raw_playback else False,
                    
                    # PlaybackRate: The rate at which playback is happening (e.g., 1.0 is normal speed).
                    "PlaybackRate": raw_playback.playback_rate if raw_playback else 1.0,
                    
                    # PlaybackStatus: The current playback state of the session (e.g., Playing, Paused).
                    "PlaybackStatus": raw_playback.playback_status.value if (raw_playback and raw_playback.playback_status) else 0,
                    
                    # PlaybackType: Specifies what type of content the session has (e.g., Music, Video).
                    "PlaybackType": raw_playback.playback_type.value if (raw_playback and raw_playback.playback_type) else 0
                }

                # Timeline properties
                # https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessiontimelineproperties?view=winrt-28000
                timeline_data = {
                    # EndTime: The end timestamp of the current media item.
                    "EndTime": int(raw_timeline.end_time.total_seconds() * 1000) if raw_timeline.end_time else 0,
                    
                    # LastUpdatedTime: The UTC time at which the timeline properties were last updated.
                    "LastUpdatedTime": str(raw_timeline.last_updated_time) if raw_timeline.last_updated_time else None,
                    
                    # MaxSeekTime: The furthest timestamp at which the content can currently seek to.
                    "MaxSeekTime": int(raw_timeline.max_seek_time.total_seconds() * 1000) if raw_timeline.max_seek_time else 0,
                    
                    # MinSeekTime: The earliest timestamp at which the current media item can currently seek to.
                    "MinSeekTime": int(raw_timeline.min_seek_time.total_seconds() * 1000) if raw_timeline.min_seek_time else 0,
                    
                    # Position: The playback position, current as of LastUpdatedTime.
                    "Position": int(raw_timeline.position.total_seconds() * 1000) if raw_timeline.position else 0,
                    
                    # StartTime: The starting timestamp of the current media item.
                    "StartTime": int(raw_timeline.start_time.total_seconds() * 1000) if raw_timeline.start_time else 0,
                }

                # Media properties
                # https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmediaproperties?view=winrt-28000
                media_data = {
                    # Title: The title of the track.
                    "Title": raw_media.title if raw_media else "Unknown",
                    
                    # Artist: The name of the artist.
                    "Artist": raw_media.artist if raw_media else "Unknown",
                    
                    # AlbumTitle: The title of the album.
                    "AlbumTitle": raw_media.album_title if raw_media else "Unknown",
                    
                    # AlbumArtist: The artist associated with the album.
                    "AlbumArtist": raw_media.album_artist if raw_media else "Unknown",
                    
                    # TrackNumber: The track number within the album.
                    "TrackNumber": raw_media.track_number if raw_media else 0,
                    
                    # AlbumTrackCount: The total number of tracks on the album.
                    "AlbumTrackCount": raw_media.album_track_count if raw_media else 0,
                    
                    # Genres: The list of genres associated with the track.
                    "Genres": list(raw_media.genres) if raw_media else [],
                    
                    # Subtitle: Any subtitle information (common in podcasts/videos).
                    "Subtitle": raw_media.subtitle if raw_media else "",
                    
                    # Thumbnail: Our cached thumbnail representation.
                    "Thumbnail": None 
                }

                # Read thumbnail and convert straight to Base64
                thumb_url = None
                if raw_media and raw_media.thumbnail:
                    try:
                        stream_ref = raw_media.thumbnail
                        stream = await stream_ref.open_read_async()

                        if stream.size > 0:
                            reader = DataReader(stream.get_input_stream_at(0))
                            await reader.load_async(stream.size)
                            buffer = bytearray(stream.size)
                            reader.read_bytes(buffer)
                            
                            # Hash the raw bytes to see if the artwork is unique
                            img_hash = hashlib.md5(buffer).hexdigest()
                            
                            # If we've already processed this exact image bytes, grab it from cache instantly
                            if img_hash in thumb_cache:
                                thumb_cache.move_to_end(img_hash)
                                thumb_url = thumb_cache[img_hash]
                                # print(f"Using cached artwork for: {media_data['Artist']} - {media_data['Title']}")
                            else:
                                print(f"Processing new artwork for: {media_data['Artist']} - {media_data['Title']}")
                                
                                # Convert raw Windows bytes straight to Base64
                                encoded_img = base64.b64encode(bytes(buffer)).decode('utf-8')
                                thumb_url = f"data:image/jpeg;base64,{encoded_img}"
                                
                                # Store it in the cache so we never process it again for this track
                                thumb_cache[img_hash] = thumb_url
                                
                                # If the cache is full, remove the least recently used item
                                if len(thumb_cache) > MAX_CACHE_SIZE:
                                    thumb_cache.popitem(last=False)
                                    print(f"Removed least recently used artwork from cache. Current cache size: {len(thumb_cache)}")

                    except Exception as e:
                        thumb_url = None

                # Add the Base64 data string to the payload

                media_data["Thumbnail"] = thumb_url

                # Finally, assemble all the data into a session object, and add it to the session list
                sessions_list.append({
                    "source_app_id": app_id,
                    "playback_info": playback_data,
                    "timeline_properties": timeline_data,
                    "media_properties": media_data
                })
            
            # Build the final payload
            payload = {
                "app_version": APP_VERSION,
                "os": f"{platform.system()} {platform.release()}",
                "current_session_id": current_session_id, 
                "sessions": sessions_list
            }
            
            # Save to global payload cache
            last_payload = payload
            return payload

        except Exception as e:
            return {"current_session_id": None, "sessions": [], "error": str(e)}



    ########################
    ### STARTUP SHORTCUT ###
    ########################

    def get_startup_shortcut_path():
        # Gets the path to the current user's Startup folder
        startup_dir = os.path.join(os.environ['APPDATA'], r'Microsoft\Windows\Start Menu\Programs\Startup')
        return os.path.join(startup_dir, 'SMTCBridge.lnk')

    def is_start_with_windows():
        return os.path.exists(get_startup_shortcut_path())

    def set_start_with_windows(enable: bool):
        shortcut_path = get_startup_shortcut_path()
        
        if enable:
            # Determine the correct path (handles both raw script and PyInstaller .exe)
            if getattr(sys, 'frozen', False):
                target_path = sys.executable
                working_dir = os.path.dirname(sys.executable)
            else:
                target_path = sys.executable  # python.exe
                working_dir = os.path.dirname(os.path.abspath(__file__))
                # If running as script, you might want to point to the script instead, 
                # but usually this feature is intended for the built .exe
                
            # Use a quick PowerShell command to create a proper Windows .lnk shortcut
            # This avoids needing external libraries like winshell
            script_args = f"""
            $WshShell = New-Object -ComObject WScript.Shell
            $Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
            $Shortcut.TargetPath = '{target_path}'
            $Shortcut.WorkingDirectory = '{working_dir}'
            $Shortcut.Save()
            """
            import subprocess
            subprocess.run(["powershell", "-Command", script_args], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            if os.path.exists(shortcut_path):
                try:
                    os.remove(shortcut_path)
                except OSError:
                    pass
    
    def toggle_startup(icon, item):
        current_state = is_start_with_windows()
        set_start_with_windows(not current_state)


    #################
    ### ENDPOINTS ###
    #################

    @app.route('/artwork/<app_identifier>')
    def serve_artwork(app_identifier):
        from flask import send_from_directory
        # Serve the cached thumbnail directly from the temp directory
        return send_from_directory(THUMB_DIR, f"{app_identifier}.jpg")

    @app.route('/now-playing')
    def now_playing():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return jsonify(loop.run_until_complete(get_all_media_info()))
        finally:
            loop.close()

    @app.route('/sessions', methods=['GET'])
    def get_sessions():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def fetch():
            manager = await SMTC.request_async()
            if not manager: return []
            return list(set([s.source_app_user_model_id for s in manager.get_sessions()]))
        
        try:
            sessions = loop.run_until_complete(fetch())
            
            # Wrapped in a <body> tag with a dark background and some padding
            html_list = """
            <body style='background-color: #121212; color: white; font-family: sans-serif; padding: 20px;'>
                <h3 style='margin-top: 0;'>Active Audio Sources:</h3>
                <ul>
            """
            
            if not sessions:
                html_list += "<li style='color: #888;'>No active audio sources found.</li>"
            else:
                for s in sessions:
                    html_list += f"<li style='margin-bottom: 8px; font-size: 1.1em;'>{s}</li>"
            
            html_list += "</ul></body>"
            return html_list
            
        except Exception as e:
            return f"<body style='background-color: #121212; color: #ff5555;'>Error: {str(e)}</body>"
        finally:
            loop.close()



    ###########################
    ### SYSTEM TRAY CONTROL ###
    ###########################

    # "Quit" menu item
    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    # Setup the tray icon
    def setup_tray():
        # Set the icon
        image = Image.open(get_resource_path("smtc-bridge.ico"))
        
        # Add the menu items
        menu = pystray.Menu(
            pystray.MenuItem(f"SMTC Bridge v{APP_VERSION} by {DEVELOPER}", None, enabled=False),
            pystray.Menu.SEPARATOR,            
            pystray.MenuItem("View Data (JSON)", lambda: webbrowser.open(f"http://{DISPLAY_HOST}:{PORT}/now-playing")),
            pystray.MenuItem("View Active Sessions", lambda: webbrowser.open(f"http://{DISPLAY_HOST}:{PORT}/sessions")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("★ Customize Overlay", lambda: webbrowser.open(f"https://widgets.nutty.gg/now-playing/settings/")),
            pystray.MenuItem("★ Try my stream widgets!", lambda: webbrowser.open(f"https://nutty.gg/collections/member-exclusive-widgets")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows", 
                toggle_startup, 
                checked=lambda item: is_start_with_windows()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit)
        )
        
        # Put it all together
        icon = pystray.Icon("MediaBridge", image, "SMTC Bridge", menu=menu)
        icon.run()



    #################
    ### KICK OFF! ###
    #################

    def run_flask():
        # Disable flask startup messages
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        
        # Define a helper to trigger the notification
        def send_notification():
            notification.notify(
                title=f'SMTC Bridge v{APP_VERSION}',
                # Use the PORT variable here
                message=f'Server successfully started on port {PORT}',
                app_icon=get_resource_path('smtc-bridge.ico'),
                timeout=5,
            )
        
        # Run the notification
        send_notification()
        
        # Start the server
        try:                
            app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)
        except Exception as e:
            with open("error.txt", "w") as f:
                f.write(str(e))

    if __name__ == '__main__':
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Setup the Tray
        setup_tray()
        
except Exception as e:
    log_crash(e)
    sys.exit(1)