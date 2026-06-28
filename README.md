# SMTC Bridge

SMTC Bridge was designed to expose Windows ***System Media Transport Controls (SMTC)*** as a clean REST API.

This lightweight system tray application allows evelopers can easily create their own "Now Playing" widgets that work with anything supported by SMTC, bypassing the complex API limitations imposed by streaming platforms (fuck you Spotify).

Simply open run the application, and a local web server will run in the background, accessible via `http://127.0.0.1:5000/now-playing/`

### Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/now-playing` | Returns the current media state as JSON. |
| `GET` | `/sessions` | Returns a list of all active media sessions. |

## Quick Start
1. Download the latest `.exe` from the [Releases page](releases).
2. Run the application — a tray icon will appear.
3. Right-click the icon to view the API.

## Credits
Built and maintained by **nutty**. 
[Check out my other stream widgets here!](https://nutty.gg/)
