# SMTC Bridge

SMTC Bridge was designed to expose Windows *System Media Transport Controls (SMTC)* as a clean REST API.

This was designed for developers to easily create their own "Now Playing" widgets that work with anything supported by SMTC, bypassing the complicated API limitations imposed by streaming platforms (fuck you Spotify).

Simply open run the system tray application, and a local web server will run in the background, accessible at `http://127.0.0.1:5000/now-playing/`

### Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/now-playing` | Returns the current media state as JSON. |
| `GET` | `/sessions` | Returns a diagnostic list of all active media sessions. |

## Quick Start
1. Download the latest `.exe` from the [Releases page](#).
2. Run the application; a tray icon will appear.
3. Right-click the icon to view the API data or manage your settings.

## Credits
Built and maintained by **nutty**. 
[Check out my other stream widgets here!](https://nutty.gg/collections/member-exclusive-widgets)
