# SMTC Bridge

SMTC Bridge was designed to expose Windows ***System Media Transport Controls (SMTC)*** as a clean REST API.

This lightweight system tray application allows evelopers can easily create their own "Now Playing" widgets that work with anything supported by SMTC, bypassing the complex API limitations imposed by streaming platforms (fuck you Spotify).

Simply open run the application, and a local web server will run in the background, accessible via `http://127.0.0.1:5000/now-playing/`

## Quick Start
1. Download the latest `.exe` from the [Releases page](releases).
2. Run the application — a tray icon will appear.
3. Right-click the icon to view the API.

### Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/now-playing` | Returns the current media state as JSON. |
| `GET` | `/sessions` | Returns a list of all active media sessions. |

### Data Schema
The `/now-playing` endpoint provides a real-time snapshot of your active media sessions. Developers can integrate this into their own web widgets using the following JSON structure:

```json
{
  "app_version": "0.0.1",
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

## Credits
Built and maintained by **nutty**. 
[Check out my other stream widgets here!](https://nutty.gg/)
