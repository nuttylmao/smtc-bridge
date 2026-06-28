# SMTC Bridge

SMTC Bridge is a lightweight system tray application that exposes Windows ***System Media Transport Controls (SMTC)*** as a clean REST API.

This tool allows developers to easily create their own "Now Playing" widgets that work with anything supported by SMTC, bypassing the complex API limitations imposed by streaming platforms (fuck you Spotify).

Simply run the application, and a local web server will run in the background. By default, it can be accessed here after running the application:<br>
[http://127.0.0.1:5000/now-playing/](http://127.0.0.1:5000/now-playing/)

A ready-to-use "Now Playing" widget utilizing SMTC Bridge is available to try here:<br>
**[https://widgets.nutty.gg/now-playing/settings/](https://widgets.nutty.gg/now-playing/settings/)**

## Quick Start
1. Download the latest `.exe` from the [Releases page](releases).
2. Run the application — a tray icon will appear.
3. Right-click the icon to view the API.

### Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/now-playing` | Returns the current media state as JSON. |
| `GET` | `/sessions` | Returns a list of all active media sessions. |

### Schema
The `/now-playing` endpoint provides a real-time snapshot of your active media sessions. Developers can integrate this into their own web widgets using the following JSON structure:

```json
{
  "app_version": "string",
  "current_session_id": "string",
  "sessions": [
    {
      "source_app_id": "string",
      "media_properties": {
        "Title": "string",
        "Artist": "string",
        "AlbumTitle": "string",
        "AlbumArtist": "string",
        "Thumbnail": "string (base64)",
        "AlbumTrackCount": "integer",
        "TrackNumber": "integer",
        "Genres": "array of strings",
        "Subtitle": "string"
      },
      "playback_info": {
        "PlaybackStatus": "integer",
        "PlaybackType": "integer",
        "PlaybackRate": "number or null",
        "IsShuffleActive": "boolean",
        "AutoRepeatMode": "integer"
      },
      "timeline_properties": {
        "Position": "integer (ms)",
        "StartTime": "integer (ms)",
        "EndTime": "integer (ms)",
        "MinSeekTime": "integer (ms)",
        "MaxSeekTime": "integer (ms)",
        "LastUpdatedTime": "string (ISO 8601)"
      }
    }
  ]
}
```

### Enums

#### Playback Status
| Value | Status | Description |
| :--- | :--- | :--- |
| `0` | `CLOSED` | Engine uninitialized or empty |
| `1` | `OPENED` | Pipeline loaded but idling |
| `2` | `CHANGING` | Buffering, track skipping, or seeking |
| `3` | `STOPPED` | Track queued but fully stopped |
| `4` | `PLAYING` | Audio actively streaming |
| `5` | `PAUSED` | Audio frozen |

#### Playback Type
| Value | Type | Description |
| :--- | :--- | :--- |
| `0` | `UNKNOWN` | Generic audio wrapper |
| `1` | `MUSIC` | Pure audio pipeline (Spotify, iTunes, etc.) |
| `2` | `VIDEO` | Visual media feed (YouTube, Twitch, etc.) |
| `3` | `IMAGE` | Static slideshow presentation hook |

#### Auto Repeat Mode
| Value | Mode | Description |
| :--- | :--- | :--- |
| `0` | `NONE` | Plays queue through and terminates |
| `1` | `TRACK` | Single active song looping |
| `2` | `LIST` | Parent playlist/album looping |

## Credits
Built and maintained by **nutty**. 
[Check out my other stream widgets here!](https://nutty.gg/)
