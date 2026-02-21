# Geo V8.5 - Simple GPS Location App

Simple desktop app for GPS location management.

## Features

- **Run Check** - Manual location verification
- **Auto-Check** - Automatic checking every X minutes (while app is open)
- **IP + GPS Verification** - Validates both IP location and GPS coordinates
- **Cloud Config** - Settings sync to Supabase

## Installation

### 1. Install Python 3.8+
Download from: https://www.python.org/downloads/

### 2. Install dependencies
```bash
cd geo-app-python
pip install -r requirements.txt
```

### 3. Run the app
```bash
python geo_app.py
```
Or double-click `run.bat`

## Usage

1. **First time**: Enter your license key
2. **Go to Settings**: Configure username, password, GPS coordinates
3. **Save Settings**
4. **Run Check**: Click to verify location
5. **Auto-Check**: Turn ON to check automatically every few minutes

## Settings

- **Device Portal**: Username and password for Windows Device Portal
- **GPS Coordinates**: Latitude and longitude to set
- **Allowed Countries**: Countries that are allowed (comma-separated)
- **Allowed States**: States that are allowed (comma-separated, empty = all)
- **Auto-Check Interval**: Minutes between automatic checks

## Files

- `geo_app.py` - Main application
- `config_local.json` - Local configuration (auto-created)
- `run.bat` - Quick launcher

## Troubleshooting

### "Device Portal unavailable"
- Enable Developer Mode in Windows Settings
- Enable Device Portal
- Check the port (default: 50080)

### Settings not saved
- Make sure to click "Save Settings"
- Check internet connection for cloud sync
