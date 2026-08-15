# Versioning
APP_VERSION = "0.0.5"
DEVELOPER = "nutty"



# IMPORTANT SHIT STARTS HERE

import sys
import traceback
import os
import datetime

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

    ###############
    ### IMPORTS ###
    ###############

    import asyncio
    import json
    import base64
    import io
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
    from PIL import Image
    from flask import Flask, jsonify
    from flask_cors import CORS
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SMTC
    from winsdk.windows.storage.streams import DataReader
    from plyer import notification
    import winsdk._winrt as winrt



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

    app = Flask(__name__)
    CORS(app)

    # Create a local temp directory for thumbnails
    THUMB_DIR = os.path.join(tempfile.gettempdir(), 'smtc_bridge_thumbs')
    if not os.path.exists(THUMB_DIR):
        os.makedirs(THUMB_DIR)



    ######################
    ### CORE FUNCTIONS ###
    ######################

    async def get_all_media_info():            
        try:
            # We will cache the last execution time and payload to avoid redundant parsing if requests flood in faster than 1 second.
            current_time = time.time()
            if not hasattr(get_all_media_info, "last_execution"):
                get_all_media_info.last_execution = 0
                get_all_media_info.last_payload = None

            # If requests flood in faster than 1 second, return the cached result 
            # to completely spare the CPU from redundant parsing.
            if (current_time - get_all_media_info.last_execution) < 1.0 and get_all_media_info.last_payload:
                # print("Using cached media info.")
                return get_all_media_info.last_payload
            # else:
            #     print("Fetching fresh media info.")
            
            get_all_media_info.last_execution = current_time

            # Instantiate the SMTC manager -> This allows use to "talk" to the Windows Media API
            manager = await SMTC.request_async()
            
            # If it returns null, then no media is playing, or something fucked up and I have no
            # idea what to do, so just return an empty session list
            if not manager:
                return {"current_session_id": None, "sessions": []}

            # This is the session for the current media player -> Whatever Windows deems is "in focus"
            # will be the current session.
            # We will store the SourceAppUserModelId, which we all add to the final payload.
            # For all available properties/methods/events, see the official docs:
            # https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession?view=winrt-28000
            current_focused = manager.get_current_session()
            current_session_id = current_focused.source_app_user_model_id if current_focused else None

            # We will also get all sessions, not just the current session.
            # This will provide the client with all the necessary info if they want to target just
            # one application.
            all_sessions = manager.get_sessions()
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

                # Read and save thumbnail to a local temp file with byte-hashing cache
                thumb_url = None
                if raw_media and raw_media.thumbnail:
                    try:
                        stream_ref = raw_media.thumbnail
                        stream = await stream_ref.open_read_async()

                        # Only proceed if there's actual data to read
                        if stream.size > 0:
                            reader = DataReader(stream.get_input_stream_at(0))
                            await reader.load_async(stream.size)
                            buffer = bytearray(stream.size)
                            reader.read_bytes(buffer)
                            
                            # Generate a safe filename based on the app_id
                            safe_app_id = "".join(c for c in app_id if c.isalnum() or c in ('_', '-'))
                            thumb_filename = f"{safe_app_id}.jpg"
                            thumb_path = os.path.join(THUMB_DIR, thumb_filename)
                            
                            # Hash the raw image bytes to check if the artwork actually changed
                            import hashlib
                            img_hash = hashlib.md5(buffer).hexdigest()
                            
                            # Track hashes in memory to avoid writing to disk if nothing changed
                            if not hasattr(get_all_media_info, "cache"):
                                get_all_media_info.cache = {}
                            
                            # Check if we already processed this exact artwork for this app
                            if get_all_media_info.cache.get(safe_app_id) == img_hash and os.path.exists(thumb_path):
                                # Artwork hasn't changed, reuse existing file and version timestamp
                                # print("Using cached artwork.")
                                pass
                            else:
                                print(f"Processing new artwork for: {media_data['Artist']} - {media_data['Title']}")
                                # Process and save with Pillow only when bytes actually change
                                img = Image.open(io.BytesIO(buffer))
                                if img.mode in ("RGBA", "P"):
                                    img = img.convert("RGB")

                                # Save at full resolution, but use faster compression settings
                                img.save(
                                    thumb_path, 
                                    "JPEG", 
                                    quality=40,          # Sweet spot for small size / high visual fidelity
                                    subsampling=2,       # Faster compression algorithm for low-end CPUs
                                    optimize=False       # Skips the extra CPU pass
                                )
                                
                                # Update cache hash
                                get_all_media_info.cache[safe_app_id] = img_hash
                            
                            # Use file modification time as the version token so browsers cache it aggressively
                            thumb_version = int(os.path.getmtime(thumb_path) * 1000)
                            
                            # Construct the URL with the version query parameter
                            thumb_url = f"http://{HOST}:{PORT}/artwork/{safe_app_id}?v={thumb_version}"
                    except Exception:
                        thumb_url = None

                # Add the local URL to the payload
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
                "current_session_id": current_session_id, 
                "sessions": sessions_list
            }
            
            # Save to global payload cache
            get_all_media_info.last_payload = payload
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
            pystray.MenuItem("View Data (JSON)", lambda: webbrowser.open(f"http://{HOST}:{PORT}/now-playing")),
            pystray.MenuItem("View Active Sessions", lambda: webbrowser.open(f"http://{HOST}:{PORT}/sessions")),
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