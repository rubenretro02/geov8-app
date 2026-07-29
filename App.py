###############################################
# Geo V9.3.1.1 - Dashboard Application
# New features in 9.3.1.1:
# - NEW: Auto-close on successful check - 3 second countdown with a Cancel
#        button (skipped while periodic auto-check is ON). Navigating to
#        Details or Settings also cancels the countdown.
#
# Previous (9.3.0.9):
# - FIX: Rebuilt with the correct toolchain (Python 3.14, no webdriver_manager).
#        The 9.3.0.8 exe was built with Python 3.12 + webdriver_manager bundled,
#        which broke Device Portal location activation on VMs
#        ("GPS injection failed: ok"). Source code is unchanged.
#
# Previous (9.3.0.8):
# - FIX: Stable HWID - a single failed/blank WMIC field can no longer change
#        the HWID. Once a full reading succeeds it is cached and frozen, so
#        flaky boots (Win11 24H2 / slow WMIC) never trigger a false reset.
# - FIX: Fuzzy HWID match - existing activations are recognised via junk-filtered,
#        legacy and empty-field variants, then silently re-anchored. No mass reset.
# - FIX: Offline grace - network/server errors no longer delete the local license.
#        The cached activation is trusted until its real expiry when the server
#        can't be reached. Licenses are only removed on server-CONFIRMED revocation.
#
# Previous (9.3.0.7):
# - FIX: HWID now retries WMIC commands 3 times before fallback
# - FIX: Prevents false "License in use on another device" errors
# - FIX: Added logging for HWID generation debugging
# - Increased WMIC timeout from 10s to 15s
# - NEW: License dialog shows existing license for easy support
# - NEW: License is pre-filled and copyable when expired/reset
#
# Previous (9.3.0.6):
# - Telegram auto-connect with QR code
# - "Open Telegram Desktop" button
# - "Copy Link" button for clipboard
# - List of connected Telegrams with remove option
# - Automatic polling for connection status
#
# Previous (9.3.0.4):
# - Auto-check when running from Startup folder
# - Startup folder copy enabled
#
# Previous (9.3.0.3):
# - Agent-level alert filters (IP, GPS, Fail, Success)
# - Independent Telegram alerts (no need for Manager toggle)
# - Error type detection for smarter filtering
#
# Previous (9.3.0.1):
# - Discreet UI redesign (privacy-focused)
# - Registry-only startup (faster, no duplicates)
# - Internet check on startup
# - HWID reset detection fix
# - Auto/Custom GPS coordinates option
# - Enhanced IP info (ISP, Hostname, Type)
# - Uptime-based auto-check detection
#
# Previous features:
# - Auto-update system
# - HWID protection
# - Persistent license storage
# - AppData storage for persistence
###############################################

import customtkinter as ctk
from tkinter import messagebox
import requests
import os
import threading
import json
from pathlib import Path
import time
import base64
import sys
import hashlib
import platform
import uuid
from datetime import datetime
import subprocess
import tempfile
import shutil
import winreg  # For Windows Registry startup
import ctypes  # For system uptime detection
import math  # For circular animation

try:
    from winotify import Notification, audio
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False

try:
    import winsound
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False

SELENIUM_AVAILABLE = False
try:
    from selenium import webdriver
    SELENIUM_AVAILABLE = True
except ImportError:
    pass

# QR Code generation for Telegram auto-link
QR_AVAILABLE = False
try:
    import qrcode
    from PIL import Image, ImageTk
    QR_AVAILABLE = True
except ImportError:
    pass

# App Version - IMPORTANT for auto-update
APP_VERSION = "9.3.1.1"

# Startup Configuration
# Set to True to enable copying app to Startup folder
# Set to False to use only Registry for startup
USE_STARTUP_FOLDER = False

# Supabase Config
SUPABASE_URL = "https://krejyqdlujpemrpeqozc.supabase.co"
# License Manager API for Telegram alerts
LICENSE_MANAGER_URL = "https://geov8-license-manager.vercel.app"
def send_telegram_alert(license_key, status, ip_address, location, message="", chat_ids="",
                        error_type=None, alert_ip=True, alert_gps=True,
                        alert_on_fail=True, alert_on_success=False):
    """Send alert to Telegram via License Manager API

    IMPORTANT: This function ALWAYS calls the API.
    The API handles filtering for both agent and admin independently.
    - Agent filters are passed in the request
    - Admin filters are stored in the database
    This ensures the admin receives notifications even if the agent has them disabled.

    Args:
        license_key: The license key
        status: 'error' or 'success'
        ip_address: The IP address
        location: Location string
        message: Error/success message
        chat_ids: Comma-separated chat IDs for the agent
        error_type: 'ip', 'gps', 'both', 'system', or None (auto-detect)
        alert_ip: Whether agent wants IP error alerts
        alert_gps: Whether agent wants GPS error alerts
        alert_on_fail: Whether agent wants failure alerts
        alert_on_success: Whether agent wants success alerts
    """
    # ═══════════════════════════════════════════════════════════════
    # ALWAYS CALL THE API - Let the server handle filtering
    # The API will filter independently for agent and admin
    # ═══════════════════════════════════════════════════════════════
    print(f"[Telegram] Sending to API: status={status}, error_type={error_type}")
    print(f"[Telegram] Agent filters: alert_ip={alert_ip}, alert_gps={alert_gps}, alert_on_fail={alert_on_fail}, alert_on_success={alert_on_success}")

    try:
        response = requests.post(
            f"{LICENSE_MANAGER_URL}/api/notify",
            json={
                "license_key": license_key,
                "status": status,
                "ip": ip_address,
                "location": location,
                "message": message,
                "chat_ids": chat_ids,
                # Agent-level filters (API will use these for agent only)
                "error_type": error_type,
                "agent_alert_ip": alert_ip,
                "agent_alert_gps": alert_gps,
                "agent_alert_on_fail": alert_on_fail,
                "agent_alert_on_success": alert_on_success,
            },
            timeout=10
        )
        print(f"[Telegram] API response: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"[Telegram] API call failed: {e}")
        return False


def generate_telegram_link_code(hardware_id):
    """Generate a link code for Telegram auto-connection

    Args:
        hardware_id: The device HWID for linking

    Returns:
        dict with code, link, link_id, expires_at or None on error
    """
    try:
        response = requests.post(
            f"{LICENSE_MANAGER_URL}/api/telegram/generate-code",
            json={"hardware_id": hardware_id},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                return {
                    "code": data.get("code"),
                    "link": data.get("link"),
                    "link_id": data.get("link_id"),
                    "expires_at": data.get("expires_at")
                }
        return None
    except Exception as e:
        print(f"[Telegram] Generate code failed: {e}")
        return None


def check_telegram_link_status(link_id):
    """Check if a Telegram link has been used

    Args:
        link_id: The link ID to check

    Returns:
        'pending', 'connected', or 'expired'
    """
    try:
        response = requests.get(
            f"{LICENSE_MANAGER_URL}/api/telegram/status?link_id={link_id}",
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("status", "pending"), data.get("chat_id")
        return "error", None
    except Exception as e:
        print(f"[Telegram] Check status failed: {e}")
        return "error", None


def get_connected_telegrams(hardware_id):
    """Get list of connected Telegram accounts for a hardware ID

    Args:
        hardware_id: The device HWID

    Returns:
        list of connected telegrams or empty list
    """
    try:
        response = requests.get(
            f"{LICENSE_MANAGER_URL}/api/telegram/list?hardware_id={hardware_id}",
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                return data.get("telegrams", [])
        return []
    except Exception as e:
        print(f"[Telegram] Get list failed: {e}")
        return []


def remove_telegram_connection(hardware_id, chat_id):
    """Remove a Telegram connection

    Args:
        hardware_id: The device HWID
        chat_id: The chat ID to remove

    Returns:
        True on success, False on error
    """
    try:
        response = requests.post(
            f"{LICENSE_MANAGER_URL}/api/telegram/remove",
            json={"hardware_id": hardware_id, "chat_id": chat_id},
            timeout=10
        )
        return response.status_code == 200 and response.json().get("success")
    except Exception as e:
        print(f"[Telegram] Remove failed: {e}")
        return False


SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtyZWp5cWRsdWpwZW1ycGVxb3pjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzAzMjA2ODgsImV4cCI6MjA4NTg5NjY4OH0.uEtY3u8Y2dbM5o_B0xHku7RU91u0iAuY7EJBCyOAxQY"

DEFAULT_ALLOWED_STATES = ["Florida", "Texas"]
DEFAULT_ALLOWED_COUNTRIES = ["United States", "USA", "US"]

# Theme colors - Dark Mode
COLORS_DARK = {
    "bg_dark": "#0a0a0f",
    "bg_card": "#12121a",
    "bg_card_hover": "#1a1a25",
    "accent": "#00d4aa",
    "accent_secondary": "#7c3aed",
    "accent_gradient_start": "#00d4aa",
    "accent_gradient_end": "#00a080",
    "success": "#10b981",
    "error": "#ef4444",
    "warning": "#f59e0b",
    "text": "#ffffff",
    "text_secondary": "#71717a",
    "border": "#27272a",
    "header_bg": "#09090b",
}

# Theme colors - Light Mode
COLORS_LIGHT = {
    "bg_dark": "#f4f4f5",
    "bg_card": "#ffffff",
    "bg_card_hover": "#f9f9f9",
    "accent": "#059669",
    "accent_secondary": "#7c3aed",
    "accent_gradient_start": "#059669",
    "accent_gradient_end": "#047857",
    "success": "#059669",
    "error": "#dc2626",
    "warning": "#d97706",
    "text": "#18181b",
    "text_secondary": "#71717a",
    "border": "#e4e4e7",
    "header_bg": "#ffffff",
}

# Start with dark mode
COLORS = COLORS_DARK.copy()

# Determinar directorio de datos persistente
# Usar %APPDATA%/Geo para garantizar permisos de escritura y persistencia
if getattr(sys, 'frozen', False):
    # Compilado como .exe - usar AppData para datos persistentes
    APP_DATA_DIR = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / "GeoV8"
    SCRIPT_DIR = Path(sys.executable).parent.resolve()  # Para recursos/iconos
else:
    # Corriendo como script Python - usar directorio del script
    APP_DATA_DIR = Path(__file__).parent.resolve()
    SCRIPT_DIR = APP_DATA_DIR

# Crear directorio de datos si no existe
try:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
except:
    APP_DATA_DIR = SCRIPT_DIR  # Fallback al directorio del ejecutable

# Archivos de configuración y datos en AppData (persistentes)
LOCAL_CONFIG_PATH = APP_DATA_DIR / "config_local.json"
STATS_PATH = APP_DATA_DIR / "stats.json"
HISTORY_PATH = APP_DATA_DIR / "history.json"
LICENSE_PATH = APP_DATA_DIR / "license_data.json"  # Persistent license storage
HWID_CACHE_PATH = APP_DATA_DIR / "hwid_cache.json"  # Frozen known-good HWID (stability)
FIRST_RUN_PATH = APP_DATA_DIR / "first_run.json"  # Track first run for auto-start
CURRENT_EXE_PATH = APP_DATA_DIR / "current_exe.txt"  # Track current exe location for updates


def save_current_exe_path():
    """
    Save the current executable path to a file.
    This ensures updates can find and delete the correct file,
    even if the user renamed the exe.
    """
    if not getattr(sys, 'frozen', False):
        return  # Only for compiled exe

    try:
        current_exe = Path(sys.executable).resolve()
        with open(CURRENT_EXE_PATH, 'w') as f:
            f.write(str(current_exe))
        print(f"Saved current exe path: {current_exe}")
    except Exception as e:
        print(f"Error saving exe path: {e}")


def get_saved_exe_paths():
    """
    Get all saved exe paths (current and any previous).
    Returns a list of paths that should be deleted during update.
    """
    paths = []
    try:
        if CURRENT_EXE_PATH.exists():
            with open(CURRENT_EXE_PATH, 'r') as f:
                saved_path = f.read().strip()
                if saved_path and Path(saved_path).exists():
                    paths.append(saved_path)
    except Exception as e:
        print(f"Error reading saved exe path: {e}")

    # Also add current exe if different
    if getattr(sys, 'frozen', False):
        current = str(Path(sys.executable).resolve())
        if current not in paths:
            paths.append(current)

    return paths


def get_system_uptime_minutes():
    """
    Get system uptime in minutes since last boot.
    Used to detect if PC just started (for auto-check feature).
    """
    try:
        # GetTickCount64 returns milliseconds since system start
        millis = ctypes.windll.kernel32.GetTickCount64()
        minutes = millis / (1000 * 60)
        return minutes
    except:
        return 9999  # Return high number if can't detect (won't trigger auto-check)


def check_internet_connection():
    """
    Check if there's an active internet connection.
    Returns True if connected, False otherwise.
    """
    test_urls = [
        "https://api.ipify.org",
        "https://www.google.com",
        "https://www.cloudflare.com",
    ]
    for url in test_urls:
        try:
            requests.get(url, timeout=5)
            return True
        except:
            continue
    return False


def get_startup_folder():
    """Get the Windows Startup folder path"""
    try:
        return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    except:
        return None


def is_running_from_startup():
    """
    Check if the app is running from the Startup folder.
    Returns True if the exe is located inside the Startup folder.
    """
    try:
        if not getattr(sys, 'frozen', False):
            return False  # Running as script

        current_exe = Path(sys.executable).resolve()
        startup_folder = get_startup_folder()

        if startup_folder and startup_folder.exists():
            startup_str = str(startup_folder.resolve()).lower()
            current_str = str(current_exe).lower()

            if current_str.startswith(startup_str):
                print(f"Detected: Running from Startup folder")
                return True

        return False
    except Exception as e:
        print(f"Error checking startup location: {e}")
        return False


def is_app_in_startup():
    """Check if app is already in Windows Startup folder or registry"""
    try:
        # Method 1: Check Startup folder for shortcut or exe
        startup_folder = get_startup_folder()
        if startup_folder and startup_folder.exists():
            # Check for any GeoV8 related files
            for item in startup_folder.iterdir():
                if "geo" in item.name.lower() or "geov" in item.name.lower():
                    return True

        # Method 2: Check Windows Registry
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ
            )
            try:
                winreg.QueryValueEx(key, "GeoApp")
                winreg.CloseKey(key)
                return True
            except WindowsError:
                winreg.CloseKey(key)
        except:
            pass

        return False
    except:
        return False


def add_to_startup():
    """Add the application to Windows Startup"""
    try:
        if getattr(sys, 'frozen', False):
            # Running as compiled exe
            app_path = sys.executable
        else:
            # Running as Python script - don't add to startup
            print("Running as script - skipping startup registration")
            return False, "Cannot add to startup when running as script"

        # Method 1: Add to Windows Registry (preferred, more reliable)
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "GeoApp", 0, winreg.REG_SZ, f'"{app_path}" --autostart')
            winreg.CloseKey(key)
            print(f"Added to startup via Registry: {app_path}")
            return True, "Added to startup via Registry"
        except Exception as e:
            print(f"Registry method failed: {e}")

        # Method 2: Copy to Startup folder (fallback) - Only if enabled
        # This is disabled by default (USE_STARTUP_FOLDER = False) to prevent duplicate app instances
        if USE_STARTUP_FOLDER:
            try:
                startup_folder = get_startup_folder()
                if startup_folder and startup_folder.exists():
                    # Create a shortcut or copy the exe
                    dest_path = startup_folder / Path(app_path).name

                    # If source and destination are different, copy
                    if Path(app_path).resolve() != dest_path.resolve():
                        shutil.copy2(app_path, dest_path)
                        print(f"Copied to startup folder: {dest_path}")
                        return True, "Copied to startup folder"
                    else:
                        print("App already in startup folder")
                        return True, "Already in startup folder"
            except Exception as e:
                print(f"Startup folder method failed: {e}")
        else:
            print("Startup folder method disabled (USE_STARTUP_FOLDER = False)")

        return False, "Failed to add to startup"
    except Exception as e:
        print(f"add_to_startup error: {e}")
        return False, str(e)


def is_first_run():
    """Check if this is the first time the app is running"""
    try:
        if FIRST_RUN_PATH.exists():
            with open(FIRST_RUN_PATH, 'r') as f:
                data = json.load(f)
                return not data.get("startup_configured", False)
        return True
    except:
        return True


def mark_startup_configured():
    """Mark that startup has been configured"""
    try:
        data = {}
        if FIRST_RUN_PATH.exists():
            try:
                with open(FIRST_RUN_PATH, 'r') as f:
                    data = json.load(f)
            except:
                pass

        data["startup_configured"] = True
        data["configured_at"] = datetime.now().isoformat()
        data["app_version"] = APP_VERSION

        with open(FIRST_RUN_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error marking startup configured: {e}")


def check_and_setup_startup():
    """Check if app should be added to startup and do it"""
    try:
        # Only run for compiled exe
        if not getattr(sys, 'frozen', False):
            print("Running as script - skipping startup check")
            return

        # Check if first run or if not in startup
        first_run = is_first_run()
        in_startup = is_app_in_startup()

        print(f"First run: {first_run}, In startup: {in_startup}")

        if first_run or not in_startup:
            print("Adding app to Windows Startup...")
            success, message = add_to_startup()

            if success:
                mark_startup_configured()
                print(f"Startup setup complete: {message}")
            else:
                print(f"Startup setup failed: {message}")
    except Exception as e:
        print(f"check_and_setup_startup error: {e}")


def ensure_in_startup():
    """
    If app is not in Startup folder, copy it there (but don't restart).
    App continues running from current location.
    This function copies the exe directly to the Startup folder.

    NOTE: This is disabled by default (USE_STARTUP_FOLDER = False) to prevent
    duplicate app instances. Only Registry startup is used now.
    """
    # Check if Startup folder method is enabled
    if not USE_STARTUP_FOLDER:
        print("Startup folder method disabled - using Registry only")
        return True

    if not getattr(sys, 'frozen', False):
        return True  # Running as script, skip

    try:
        current_exe = sys.executable
        exe_name = os.path.basename(current_exe)
        startup_folder = get_startup_folder()

        if startup_folder is None:
            print("Could not get Startup folder path")
            return True

        startup_exe = startup_folder / exe_name

        # Check if exe already exists in Startup folder
        if not startup_exe.exists():
            # Copy exe to Startup folder (don't restart, just copy)
            shutil.copy2(current_exe, str(startup_exe))
            print(f"Copied to Startup: {startup_exe}")
        else:
            print(f"Already in Startup: {startup_exe}")

    except Exception as e:
        print(f"Could not copy to Startup folder: {e}")

    return True  # Always continue with current instance


def get_common_user_folders():
    """Get all common user folders where the app might be located"""
    folders = []
    try:
        # Get user home directory
        home = Path.home()

        # Common folders where users might put executables
        common_paths = [
            # Startup folder
            Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup",
            # Desktop
            home / "Desktop",
            # Downloads
            home / "Downloads",
            # Documents
            home / "Documents",
            # AppData Local
            Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")),
            # AppData Roaming
            Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")),
            # Program Files (user installable)
            home / "AppData" / "Local" / "Programs",
            # Root of user folder
            home,
            # OneDrive Desktop/Downloads/Documents if exists
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Downloads",
            home / "OneDrive" / "Documents",
        ]

        for p in common_paths:
            if p and p.exists() and p.is_dir():
                folders.append(p)

    except Exception as e:
        print(f"Error getting common folders: {e}")

    return folders


def is_geo_app_executable(file_path):
    """
    Check if a file is likely a GeoV8/Geo app executable.
    Uses multiple heuristics to identify the app even if renamed.
    """
    try:
        file_path = Path(file_path)

        # Must be an exe file
        if file_path.suffix.lower() != '.exe':
            return False

        # Skip if it's the current running executable
        if getattr(sys, 'frozen', False):
            current_exe = Path(sys.executable).resolve()
            if file_path.resolve() == current_exe:
                return False

        # Check file size - GeoV8 exe should be between 10MB and 100MB typically
        file_size = file_path.stat().st_size
        if file_size < 5 * 1024 * 1024 or file_size > 150 * 1024 * 1024:  # 5MB to 150MB
            return False

        # Check 1: Name contains geo-related keywords (case insensitive)
        name_lower = file_path.stem.lower()
        geo_keywords = ['geo', 'geov', 'geo_v', 'geo-v', 'geov8', 'geov9', 'geoapp', 'geo_app', 'geo-app']
        name_match = any(kw in name_lower for kw in geo_keywords)

        # Check 2: Read first few bytes to check for PyInstaller signature
        # PyInstaller executables have specific patterns
        is_pyinstaller = False
        try:
            with open(file_path, 'rb') as f:
                # Read first 2 bytes for MZ header (PE executable)
                header = f.read(2)
                if header == b'MZ':
                    # Read more to look for PyInstaller markers
                    f.seek(0)
                    content = f.read(min(file_size, 1024 * 100))  # Read first 100KB

                    # Look for common PyInstaller strings
                    pyinstaller_markers = [
                        b'pyi-runtime-tmpdir',
                        b'_MEIPASS',
                        b'PyInstaller',
                        b'_pyi_',
                    ]

                    for marker in pyinstaller_markers:
                        if marker in content:
                            is_pyinstaller = True
                            break

                    # Also look for specific app strings
                    app_markers = [
                        b'GeoV',
                        b'geov',
                        b'Geo V',
                        b'SUPABASE',
                        b'krejyqdlujpemrpeqozc.supabase.co',  # Our specific supabase URL
                        b'check_and_setup_startup',
                        b'AutoUpdater',
                        b'SupabaseManager',
                    ]

                    app_match = any(marker in content for marker in app_markers)

                    if app_match:
                        return True
        except:
            pass

        # If name matches and it's a PyInstaller exe, it's likely our app
        if name_match and is_pyinstaller:
            return True

        # If name strongly matches (contains geov + version number pattern)
        import re
        if re.search(r'geo\s*v?\s*\d', name_lower):
            return True

        return False

    except Exception as e:
        print(f"Error checking file {file_path}: {e}")
        return False


def clean_old_versions():
    """
    Find and delete old versions of the GeoV8 app from common locations.
    This runs at startup to prevent conflicts with old versions.
    """
    if not getattr(sys, 'frozen', False):
        print("Running as script - skipping old version cleanup")
        return

    current_exe = Path(sys.executable).resolve()
    deleted_files = []

    print("Scanning for old versions to clean up...")

    folders_to_scan = get_common_user_folders()

    for folder in folders_to_scan:
        try:
            # Scan only immediate files in folder (not recursive to avoid being too aggressive)
            for item in folder.iterdir():
                try:
                    if item.is_file() and item.resolve() != current_exe:
                        if is_geo_app_executable(item):
                            print(f"Found old version: {item}")
                            try:
                                # Try to delete the file
                                item.unlink()
                                deleted_files.append(str(item))
                                print(f"Deleted: {item}")
                            except PermissionError:
                                print(f"Could not delete (in use?): {item}")
                            except Exception as e:
                                print(f"Error deleting {item}: {e}")
                except Exception as e:
                    continue

        except PermissionError:
            continue
        except Exception as e:
            print(f"Error scanning {folder}: {e}")
            continue

    # Also clean up old registry entries that might point to non-existent files
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_ALL_ACCESS
        )
        try:
            # Check if there's an old GeoV8 entry pointing to a different location
            old_path, _ = winreg.QueryValueEx(key, "GeoApp")
            old_path = old_path.strip('"')

            if old_path and Path(old_path).resolve() != current_exe:
                # Old entry points to different location
                if not Path(old_path).exists():
                    # Old file doesn't exist, remove registry entry
                    winreg.DeleteValue(key, "GeoApp")
                    print(f"Removed old registry entry pointing to: {old_path}")
        except WindowsError:
            pass
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        print(f"Error cleaning registry: {e}")

    if deleted_files:
        print(f"Cleaned up {len(deleted_files)} old version(s)")
    else:
        print("No old versions found")

    return deleted_files


class AutoUpdater:
    """Handles automatic app updates"""
    # ... (unchanged, omitted for brevity; see original code above) ...
    def __init__(self, supabase_url, supabase_key):
        self.base_url = f"{supabase_url}/rest/v1"
        self.headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json"
        }

    def check_for_updates(self):
        try:
            r = requests.get(
                f"{self.base_url}/app_version",
                headers=self.headers,
                params={"select": "*", "order": "created_at.desc", "limit": "1"},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    latest = data[0]
                    latest_version = latest.get("version", "0")
                    download_url = latest.get("download_url", "")
                    release_notes = latest.get("release_notes", "")
                    force_update = latest.get("force_update", False)

                    if self._compare_versions(latest_version, APP_VERSION) > 0 and download_url:
                        return {
                            "available": True,
                            "version": latest_version,
                            "download_url": download_url,
                            "release_notes": release_notes,
                            "force_update": force_update
                        }
            return {"available": False}
        except Exception as e:
            print(f"Update check error: {e}")
            return {"available": False}

    def _compare_versions(self, v1, v2):
        try:
            parts1 = [int(x) for x in v1.replace("v", "").split(".")]
            parts2 = [int(x) for x in v2.replace("v", "").split(".")]
            for i in range(max(len(parts1), len(parts2))):
                p1 = parts1[i] if i < len(parts1) else 0
                p2 = parts2[i] if i < len(parts2) else 0
                if p1 > p2:
                    return 1
                elif p1 < p2:
                    return -1
            return 0
        except:
            return 0

    def _find_all_app_locations(self):
        locations_found = []
        try:
            home = Path.home()
            startup_folder = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            folders_to_scan = [
                startup_folder,
                home / "Desktop",
                home / "Downloads",
                home / "Documents",
                home,
                Path(os.environ.get("APPDATA", "")),
                Path(os.environ.get("LOCALAPPDATA", "")),
                home / "OneDrive" / "Desktop",
                home / "OneDrive" / "Downloads",
                home / "OneDrive" / "Documents",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
            ]
            exe_patterns = ["App.exe", "app.exe", "GeoV8.exe", "GeoV9.exe", "Geo.exe"]
            for folder in folders_to_scan:
                if folder and folder.exists() and folder.is_dir():
                    for exe_name in exe_patterns:
                        exe_path = folder / exe_name
                        if exe_path.exists() and exe_path.is_file():
                            try:
                                size = exe_path.stat().st_size
                                if size > 5 * 1024 * 1024:
                                    locations_found.append((str(folder), exe_name))
                                    print(f"Found app copy at: {exe_path}")
                            except:
                                pass
                    try:
                        for item in folder.iterdir():
                            if item.is_file() and item.suffix.lower() == '.exe':
                                name_lower = item.stem.lower()
                                if 'geo' in name_lower and item.stat().st_size > 5 * 1024 * 1024:
                                    loc = (str(folder), item.name)
                                    if loc not in locations_found:
                                        locations_found.append(loc)
                                        print(f"Found app copy at: {item}")
                    except:
                        pass
        except Exception as e:
            print(f"Error scanning for app locations: {e}")
        return locations_found

    def download_and_install(self, download_url, progress_callback=None):
        try:
            if not download_url:
                return False, "No download URL"
            if progress_callback:
                progress_callback("Scanning for existing copies...")
            existing_locations = self._find_all_app_locations()
            print(f"Found {len(existing_locations)} existing app locations")
            if progress_callback:
                progress_callback("Downloading update...")
            response = requests.get(download_url, stream=True, timeout=120)
            if response.status_code != 200:
                return False, f"Download failed: HTTP {response.status_code}"
            total_size = int(response.headers.get('content-length', 0))
            if total_size > 0 and total_size < 100000:
                return False, "Download file too small - check URL"
            update_dir = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / "GeoV8" / "update"
            update_dir.mkdir(parents=True, exist_ok=True)
            new_exe_name = "App.exe"
            temp_file = str(update_dir / new_exe_name)
            downloaded = 0
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            percent = int(downloaded * 100 / total_size)
                            progress_callback(f"Downloading... {percent}%")
            actual_size = os.path.getsize(temp_file)
            if actual_size < 100000:
                return False, f"Downloaded file too small ({actual_size} bytes)"
            if progress_callback:
                progress_callback("Preparing update...")
            if getattr(sys, 'frozen', False):
                current_exe = sys.executable
                current_pid = os.getpid()
                current_exe_name = os.path.basename(current_exe)
                current_exe_folder = str(Path(current_exe).parent.resolve())
            else:
                return False, "Cannot auto-update when running as script"
            startup_folder = str(Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")
            startup_exe_path = os.path.join(startup_folder, new_exe_name)
            home = str(Path.home())
            appdata = os.environ.get("APPDATA", "")
            localappdata = os.environ.get("LOCALAPPDATA", "")

            # Get saved exe paths (handles renamed files)
            saved_exe_paths = get_saved_exe_paths()
            print(f"Saved exe paths to delete: {saved_exe_paths}")
            primary_exe_path = os.path.join(current_exe_folder, current_exe_name)
            restore_locations = []
            for folder, exe_name in existing_locations:
                restore_path = os.path.join(folder, exe_name)
                if restore_path not in restore_locations:
                    restore_locations.append(restore_path)
            if USE_STARTUP_FOLDER and startup_exe_path not in restore_locations:
                restore_locations.append(startup_exe_path)
            if primary_exe_path not in restore_locations:
                restore_locations.append(primary_exe_path)
            print(f"Will restore to {len(restore_locations)} locations:")
            for loc in restore_locations:
                print(f"  - {loc}")
            batch_script = str(update_dir / "geo_updater.bat")

            # Build batch script content
            batch_content = []
            batch_content.append("@echo off")
            batch_content.append("chcp 65001 >nul 2>&1")
            batch_content.append("title Geo App Updater")
            batch_content.append("color 0A")
            batch_content.append("")
            batch_content.append("echo [1/5] Closing app...")
            batch_content.append(f'taskkill /PID {current_pid} /F >nul 2>&1')
            batch_content.append(f'taskkill /IM "{current_exe_name}" /F >nul 2>&1')
            batch_content.append('taskkill /IM "App.exe" /F >nul 2>&1')
            batch_content.append('taskkill /IM "GeoV8.exe" /F >nul 2>&1')
            batch_content.append('taskkill /IM "GeoV9.exe" /F >nul 2>&1')
            batch_content.append("timeout /t 3 /nobreak >nul")
            batch_content.append("echo     Done!")
            batch_content.append("")
            batch_content.append("echo [2/5] Cleaning old versions...")

            # Delete current exe
            batch_content.append(f'if exist "{current_exe}" del /f /q "{current_exe}" >nul 2>&1')

            # Delete saved exe paths (handles renamed files)
            for saved_path in saved_exe_paths:
                batch_content.append(f'if exist "{saved_path}" del /f /q "{saved_path}" >nul 2>&1')

            batch_content.append("echo     Done!")
            batch_content.append("")
            batch_content.append('reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "GeoApp" /f >nul 2>&1')
            batch_content.append("")
            batch_content.append("echo [3/5] Installing new version...")

            # Install to all locations
            for i, restore_path in enumerate(restore_locations):
                restore_folder = str(Path(restore_path).parent)
                batch_content.append(f'if not exist "{restore_folder}" mkdir "{restore_folder}"')
                batch_content.append(f'copy /y "{temp_file}" "{restore_path}" >nul 2>&1')
                batch_content.append(f'echo     Installed to: {restore_path}')

            batch_content.append("")
            batch_content.append(f'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "GeoApp" /t REG_SZ /d "\\"{primary_exe_path}\\"" /f >nul 2>&1')
            batch_content.append("")
            batch_content.append("echo [4/5] Starting new version...")
            batch_content.append(f'start "" "{primary_exe_path}"')
            batch_content.append("timeout /t 2 /nobreak >nul")
            batch_content.append("")
            batch_content.append("echo [5/5] Cleanup...")
            batch_content.append(f'del /f /q "{temp_file}" >nul 2>&1')
            batch_content.append(f'del /f /q "{str(CURRENT_EXE_PATH)}" >nul 2>&1')
            batch_content.append("")
            batch_content.append("echo Update complete!")
            batch_content.append(f"echo Location: {primary_exe_path}")
            batch_content.append("")

            # Self-delete
            cleanup_bat = str(update_dir / "cleanup.bat")
            batch_content.append(f'echo @echo off > "{cleanup_bat}"')
            batch_content.append(f'echo timeout /t 1 /nobreak ^>nul >> "{cleanup_bat}"')
            batch_content.append(f'echo del /f /q "{batch_script}" >> "{cleanup_bat}"')
            batch_content.append(f'echo rmdir /s /q "{str(update_dir)}" >> "{cleanup_bat}"')
            batch_content.append(f'start /b "" cmd /c "{cleanup_bat}"')
            batch_content.append("exit")

            # Write batch file
            with open(batch_script, 'w', encoding='utf-8') as f:
                f.write("\n".join(batch_content))
            if progress_callback:
                progress_callback("Starting update...")
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            subprocess.Popen(
                f'cmd /c "{batch_script}"',
                shell=True,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Update started"
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)[:50]}"
        except Exception as e:
            return False, str(e)


class StatsManager:
    """Manages check statistics"""
    def __init__(self):
        self.stats = self._load_stats()

    def _load_stats(self):
        try:
            if STATS_PATH.exists():
                with open(STATS_PATH, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {"total_checks": 0, "successful_checks": 0, "failed_checks": 0}

    def _save_stats(self):
        try:
            with open(STATS_PATH, 'w') as f:
                json.dump(self.stats, f)
        except:
            pass

    def record_check(self, success):
        self.stats["total_checks"] += 1
        if success:
            self.stats["successful_checks"] += 1
        else:
            self.stats["failed_checks"] += 1
        self._save_stats()

    def get_stats(self):
        return self.stats

    def get_total_checks(self):
        return self.stats.get("total_checks", 0)


class HistoryManager:
    """Manages check history"""
    def __init__(self, max_items=5):
        self.max_items = max_items
        self.history = self._load_history()

    def _load_history(self):
        try:
            if HISTORY_PATH.exists():
                with open(HISTORY_PATH, 'r') as f:
                    return json.load(f)
        except:
            pass
        return []

    def _save_history(self):
        try:
            with open(HISTORY_PATH, 'w') as f:
                json.dump(self.history, f)
        except:
            pass

    def add_entry(self, status, location, ip):
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status": status,
            "location": location,
            "ip": ip
        }
        self.history.insert(0, entry)
        self.history = self.history[:self.max_items]
        self._save_history()

    def get_history(self):
        return self.history


def play_sound(success=True):
    """Play notification sound"""
    if SOUND_AVAILABLE:
        try:
            if success:
                winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
            else:
                winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except:
            pass


# Placeholder / junk serials that motherboards commonly report. Treated as
# "blank" so they can never contribute an unstable value to the HWID.
HW_JUNK_VALUES = {
    "", "none", "null", "0", "00000000", "default string",
    "to be filled by o.e.m.", "to be filled by oem", "system serial number",
    "not applicable", "not specified", "invalid", "unknown", "n/a",
    "oem", "chassis serial number", "base board serial number",
}


def _run_wmic(cmd, max_retries=3, retry_delay=2):
    """Run a WMIC command with retries for stability."""
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, shell=True, timeout=15
            )
            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            value = lines[1] if len(lines) > 1 else ""
            if value:
                print(f"[HWID] {cmd.split()[-1]}: OK")
                return value
            if attempt < max_retries - 1:
                print(f"[HWID] {cmd.split()[-1]}: empty, retry {attempt + 2}/{max_retries}")
                time.sleep(retry_delay)
        except subprocess.TimeoutExpired:
            print(f"[HWID] {cmd.split()[-1]}: timeout, retry {attempt + 2}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        except Exception as e:
            print(f"[HWID] {cmd.split()[-1]}: error ({e})")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    print(f"[HWID] {cmd.split()[-1]}: FAILED after {max_retries} attempts")
    return ""


def _clean_hw_value(v):
    """Normalise a hardware serial; junk/placeholder values become blank."""
    if not v:
        return ""
    v = " ".join(v.split()).strip()
    if v.lower() in HW_JUNK_VALUES:
        return ""
    return v


def _hash_parts(bios, baseboard, system_uuid):
    # CRITICAL: keep exact same format for compatibility with existing licenses.
    combined = f"{bios}-{baseboard}-{system_uuid}"
    return hashlib.sha256(combined.encode()).hexdigest()[:32].upper()


def _load_cached_hwid():
    try:
        if HWID_CACHE_PATH.exists():
            with open(HWID_CACHE_PATH, 'r') as f:
                return (json.load(f).get("hwid") or "").strip() or None
    except Exception:
        pass
    return None


def _save_cached_hwid(hwid):
    try:
        with open(HWID_CACHE_PATH, 'w') as f:
            json.dump({"hwid": hwid}, f)
    except Exception:
        pass


def get_hardware_info():
    """
    Return (primary_hwid, candidate_hwids).

    primary_hwid is STABLE: the first time a *complete* hardware reading
    succeeds it is cached and frozen, so a later boot where a WMIC field is
    blank/slow can never change it (root cause of the "needs HWID reset" bug).

    candidate_hwids is the set of every HWID this exact machine could
    legitimately have produced - junk-filtered, raw/legacy, and empty-field
    variants. It lets us recognise an already-activated device by any of its
    past fingerprints (fuzzy match, like Windows/OEM activation) and then
    silently re-anchor it to the stable primary. No mass reset required.
    """
    raw_bios = _run_wmic("wmic bios get serialnumber")
    raw_board = _run_wmic("wmic baseboard get serialnumber")
    raw_uuid = _run_wmic("wmic csproduct get uuid")

    bios = _clean_hw_value(raw_bios)
    board = _clean_hw_value(raw_board)
    uid = _clean_hw_value(raw_uuid)

    candidates = set()

    # Fuzzy combos: each cleaned field is either present or blank. This matches
    # whatever the machine hashed at activation regardless of which field was
    # flaky then or now.
    for b in {bios, ""}:
        for m in {board, ""}:
            for u in {uid, ""}:
                if b or m or u:
                    candidates.add(_hash_parts(b, m, u))

    # Legacy: exactly how the old code hashed the raw (possibly junk) values.
    if raw_bios or raw_board or raw_uuid:
        candidates.add(_hash_parts(raw_bios, raw_board, raw_uuid))

    # Hardware-less fallback (old behaviour) as a candidate.
    fallback = None
    if not (bios or board or uid):
        try:
            machine_id = str(uuid.getnode())
            processor = platform.processor()
            fallback = hashlib.sha256(f"{machine_id}-{processor}".encode()).hexdigest()[:32].upper()
            candidates.add(fallback)
            print("[HWID] WARNING: All WMIC blank, using fallback (MAC+processor)")
        except Exception:
            pass

    cached = _load_cached_hwid()
    complete = bool(bios and board and uid)

    if cached:
        primary = cached  # frozen - never flips once set
    else:
        if bios or board or uid:
            primary = _hash_parts(bios, board, uid)
        elif fallback:
            primary = fallback
        else:
            primary = _hash_parts("", "", "")
        # Only freeze a trustworthy full reading; a partial one stays recomputable
        # so a later complete boot can set the good cache.
        if complete:
            _save_cached_hwid(primary)

    candidates.add(primary)
    print(f"[HWID] Primary: {primary} ({len(candidates)} candidates)")
    return primary, sorted(candidates)


def get_hardware_id():
    """Backwards-compatible wrapper: returns the stable primary HWID only."""
    return get_hardware_info()[0]


class SupabaseManager:
    # ... (unchanged, omitted for brevity; see original code above) ...
    def __init__(self):
        self.hwid, self.hwid_candidates = get_hardware_info()
        self.is_licensed = False
        self.license_key = None
        self.agent_name = None
        self.days_left = None
        self.headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        self.base_url = f"{SUPABASE_URL}/rest/v1"

    def _get(self, table, params=None):
        try:
            r = requests.get(f"{self.base_url}/{table}", headers=self.headers, params=params, timeout=10)
            return r.json() if r.status_code == 200 else None
        except:
            return None

    def _post(self, table, data):
        try:
            r = requests.post(f"{self.base_url}/{table}", headers=self.headers, json=data, timeout=10)
            return r.status_code in [200, 201]
        except:
            return False

    def _patch(self, table, data, params):
        try:
            r = requests.patch(f"{self.base_url}/{table}", headers=self.headers, json=data, params=params, timeout=10)
            return r.status_code in [200, 204]
        except:
            return False

    def _fetch(self, table, params):
        """Like _get, but distinguishes a reachable server (True, data) from a
        network/server error (False, None). Needed so an outage is NEVER treated
        as an invalid license."""
        try:
            r = requests.get(f"{self.base_url}/{table}", headers=self.headers, params=params, timeout=10)
            if r.status_code == 200:
                return True, r.json()
            return False, None
        except:
            return False, None

    def _hwid_matches(self, server_hwid):
        """True if the server's stored HWID is any fingerprint of THIS machine."""
        sh = (server_hwid or "").strip()
        return bool(sh) and (sh == self.hwid or sh in self.hwid_candidates)

    def _locally_expired(self, local):
        ea = local.get("expires_at")
        if not ea:
            return False
        try:
            exp = datetime.fromisoformat(ea.replace('Z', '+00:00'))
            return exp < datetime.now(exp.tzinfo)
        except:
            return False

    def _apply_license(self, license_key, agent_name, expires_at):
        self.is_licensed = True
        self.license_key = license_key
        self.agent_name = agent_name or "Agent"
        self.days_left = self._calc_days(expires_at)

    def _calc_days(self, expires_at):
        if not expires_at:
            return None
        try:
            exp = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            return max(0, (exp - datetime.now(exp.tzinfo)).days)
        except:
            return None

    def _save_license_locally(self, license_key, agent_name, expires_at):
        try:
            data = {
                "license_key": license_key,
                "agent_name": agent_name,
                "expires_at": expires_at,
                "hwid": self.hwid,
                "saved_at": datetime.now().isoformat()
            }
            with open(LICENSE_PATH, 'w') as f:
                json.dump(data, f)
        except:
            pass

    def _load_license_locally(self):
        try:
            if LICENSE_PATH.exists():
                with open(LICENSE_PATH, 'r') as f:
                    data = json.load(f)
                    if data.get("hwid") == self.hwid:
                        return data
        except:
            pass
        return None

    def _delete_local_license(self):
        try:
            if LICENSE_PATH.exists():
                LICENSE_PATH.unlink()
                print("Local license data deleted")
        except Exception as e:
            print(f"Error deleting local license: {e}")

    def check_license(self):
        """Validate the license.

        Rules that keep legitimate users from being logged out:
        - The local license is ONLY deleted on a server-CONFIRMED revocation
          (deactivated, admin reset, or HWID bound to a genuinely different
          device). A network/server error never deletes it.
        - When the server is unreachable, a cached activation is trusted until
          its real expiry (offline grace).
        - HWID is matched fuzzily against every fingerprint of this machine and
          silently re-anchored to the stable primary when it matches a variant.
        """
        local_license = self._load_license_locally()

        # A) Verify a cached activation against the server.
        if local_license:
            # Hard stop: expiry is enforced even offline.
            if self._locally_expired(local_license):
                return False, "Expired"

            license_key = local_license.get("license_key")
            ok, result = self._fetch("licenses", {"license_key": f"eq.{license_key}", "select": "*"})

            if not ok:
                # Server unreachable -> offline grace, trust the cache. Do NOT delete.
                print("License server unreachable, using offline grace")
                self._apply_license(local_license.get("license_key"),
                                    local_license.get("agent_name"),
                                    local_license.get("expires_at"))
                return True, self.agent_name

            if result and len(result) > 0:
                lic = result[0]
                if not lic.get("is_active", False):
                    self._delete_local_license()
                    return False, "Deactivated"
                server_hwid = (lic.get("hwid") or "").strip()
                if not server_hwid:
                    print("License HWID was reset by admin")
                    self._delete_local_license()
                    return False, "Reset"
                if not self._hwid_matches(server_hwid):
                    print(f"License HWID belongs to another device: server={server_hwid}")
                    self._delete_local_license()
                    return False, "HWID mismatch"
                # Matched (possibly via a legacy variant) -> re-anchor to the stable primary.
                if server_hwid != self.hwid:
                    print(f"Re-anchoring HWID: {server_hwid} -> {self.hwid}")
                    self._patch("licenses", {"hwid": self.hwid}, {"license_key": f"eq.{license_key}"})
                expires_at = lic.get("expires_at")
                if expires_at:
                    exp = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    if exp < datetime.now(exp.tzinfo):
                        return False, "Expired"
                self._apply_license(lic.get("license_key"),
                                    lic.get("customer_name") or "Agent", expires_at)
                self._save_license_locally(self.license_key, self.agent_name, expires_at)
                return True, self.agent_name
            # Reachable but license_key not found (deleted). Fall through to HWID lookup.

        # B) No usable local activation (fresh install or key deleted): look up by HWID.
        candidates = ",".join(self.hwid_candidates)
        ok, result = self._fetch("licenses", {"hwid": f"in.({candidates})", "select": "*"})

        if not ok:
            # Offline: if we still hold a non-expired local license, keep working.
            if local_license and not self._locally_expired(local_license):
                self._apply_license(local_license.get("license_key"),
                                    local_license.get("agent_name"),
                                    local_license.get("expires_at"))
                return True, self.agent_name
            return False, "Offline"

        if result and len(result) > 0:
            lic = result[0]
            if not lic.get("is_active", False):
                return False, "Deactivated"
            expires_at = lic.get("expires_at")
            if expires_at:
                exp = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if exp < datetime.now(exp.tzinfo):
                    return False, "Expired"
            # Re-anchor to the stable primary if it was stored under a variant.
            if (lic.get("hwid") or "").strip() != self.hwid:
                self._patch("licenses", {"hwid": self.hwid}, {"license_key": f"eq.{lic.get('license_key')}"})
            self._apply_license(lic.get("license_key"),
                                lic.get("customer_name") or "Agent", expires_at)
            self._save_license_locally(self.license_key, self.agent_name, expires_at)
            return True, self.agent_name

        return False, "Missing"

    def activate_license(self, license_key):
        try:
            license_key = license_key.strip().upper()
            result = self._get("licenses", {"license_key": f"eq.{license_key}", "select": "*"})
            if not result or len(result) == 0:
                return False, "Invalid license"
            lic = result[0]
            if not lic.get("is_active", False):
                return False, "Expired"
            expires_at = lic.get("expires_at")
            if expires_at:
                exp = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if exp < datetime.now(exp.tzinfo):
                    return False, "Expired"
            existing_hwid = (lic.get("hwid") or "").strip()
            if existing_hwid:
                if not self._hwid_matches(existing_hwid):
                    return False, "License already in use on another device"
                # Same machine (exact or legacy variant) -> re-anchor to primary.
                if existing_hwid != self.hwid:
                    self._patch("licenses", {"hwid": self.hwid}, {"license_key": f"eq.{license_key}"})
                self._apply_license(license_key, lic.get("customer_name") or "Agent", expires_at)
                self._save_license_locally(self.license_key, self.agent_name, expires_at)
                return True, self.agent_name
            if not self._patch("licenses", {"hwid": self.hwid}, {"license_key": f"eq.{license_key}"}):
                return False, "Registration failed"
            self._apply_license(license_key, lic.get("customer_name") or "Agent", expires_at)
            self._save_license_locally(self.license_key, self.agent_name, expires_at)
            return True, self.agent_name
        except:
            return False, "Connection error"

    def load_config(self):
        if not self.is_licensed:
            return None
        try:
            result = self._get("configurations", {"hardware_id": f"eq.{self.hwid}"})
            return result[0] if result and len(result) > 0 else None
        except:
            return None

    def save_config(self, config_data):
        if not self.is_licensed:
            return False
        try:
            config_data["hardware_id"] = self.hwid
            existing = self._get("configurations", {"hardware_id": f"eq.{self.hwid}"})
            if existing and len(existing) > 0:
                return self._patch("configurations", config_data, {"hardware_id": f"eq.{self.hwid}"})
            else:
                return self._post("configurations", config_data)
        except:
            return False

    def log_check(self, ip, ip_loc, gps_loc, status, message):
        try:
            self._post("check_logs", {
                "hwid": self.hwid,
                "license_key": self.license_key,
                "ip_address": ip,
                "ip_country": ip_loc.get("country") if ip_loc else None,
                "ip_state": ip_loc.get("state") if ip_loc else None,
                "ip_city": ip_loc.get("city") if ip_loc else None,
                "gps_country": gps_loc.get("country") if gps_loc else None,
                "gps_state": gps_loc.get("state") if gps_loc else None,
                "gps_city": gps_loc.get("city") if gps_loc else None,
                "status": status,
                "message": message
            })
        except:
            pass


class StatusCard(ctk.CTkFrame):
    def __init__(self, master, title, **kwargs):
        super().__init__(master, fg_color="#1e1e1e", corner_radius=10, **kwargs)
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", padx=10, pady=(8, 2))
        self.value_label = ctk.CTkLabel(self, text="--", font=ctk.CTkFont(size=14, weight="bold"),
                                         text_color=COLORS["text"])
        self.value_label.pack(anchor="w", padx=10, pady=(0, 8))

    def set_value(self, value, color=None):
        self.value_label.configure(text=value if value else "--")
        self.value_label.configure(text_color=color if color else COLORS["text"])


class AnimatedCircle(ctk.CTkCanvas):
    """Custom animated circle widget - progress based on actual check steps"""
    def __init__(self, master, size=180, **kwargs):
        super().__init__(master, width=size, height=size, bg=COLORS["bg_card"],
                        highlightthickness=0, **kwargs)
        self.size = size
        self.center = size // 2
        self.radius = size // 2 - 10
        self.progress = 0
        self.target_progress = 0
        self.animation_id = None
        self.state = "idle"  # idle, running, success, error
        self.draw_circle()

    def draw_circle(self):
        """Draw the circle based on current state"""
        self.delete("all")

        # Background circle
        bg_color = COLORS["bg_card_hover"]
        self.create_oval(10, 10, self.size-10, self.size-10,
                        outline=COLORS["border"], width=4, fill=bg_color)

        if self.state == "idle":
            # Gray circle - empty, no text
            pass

        elif self.state == "running":
            # Yellow progress arc
            extent = self.progress * 3.6  # 0-100 -> 0-360
            if extent > 0:
                self.create_arc(10, 10, self.size-10, self.size-10,
                               start=90, extent=-extent,
                               outline="#f59e0b", width=4, style="arc")
            # Show percentage in center
            self._draw_percentage()

        elif self.state == "success":
            # Green filled circle with thumb up
            self.create_oval(10, 10, self.size-10, self.size-10,
                            outline=COLORS["success"], width=4, fill="#0d3d2e")
            self._draw_thumb("👍", COLORS["success"])

        elif self.state == "error":
            # Red filled circle with thumb down
            self.create_oval(10, 10, self.size-10, self.size-10,
                            outline=COLORS["error"], width=4, fill="#3d1a1a")
            self._draw_thumb("👎", COLORS["error"])

    def _draw_thumb(self, text, color):
        """Draw thumb icon in center"""
        self.create_text(self.center, self.center, text=text,
                        font=("Segoe UI Emoji", 48), fill=color)

    def _draw_percentage(self):
        """Draw percentage number in center"""
        percent_text = f"{int(self.progress)}%"
        self.create_text(self.center, self.center, text=percent_text,
                        font=("Segoe UI", 28, "bold"), fill="#f59e0b")

    def start(self):
        """Start - set to running state at 0%"""
        self.state = "running"
        self.progress = 0
        self.target_progress = 0
        self.draw_circle()

    def set_progress(self, percent):
        """Set progress to a specific percentage (animates smoothly)"""
        self.target_progress = min(percent, 100)
        self._smooth_animate()

    def _smooth_animate(self):
        """Smoothly animate to target progress"""
        if self.animation_id:
            self.after_cancel(self.animation_id)

        if self.state != "running":
            return

        if self.progress < self.target_progress:
            # Animate towards target
            diff = self.target_progress - self.progress
            step = max(0.5, diff / 10)  # Smooth step
            self.progress = min(self.progress + step, self.target_progress)
            self.draw_circle()
            self.animation_id = self.after(30, self._smooth_animate)
        elif self.progress > self.target_progress:
            self.progress = self.target_progress
            self.draw_circle()

    def finish(self, success=True):
        """Finish the check - animate to 100% then show result"""
        if self.animation_id:
            self.after_cancel(self.animation_id)
            self.animation_id = None

        self.target_progress = 100
        self._finish_animation(success)

    def _finish_animation(self, success):
        """Animate to 100% then show result"""
        if self.progress < 100:
            self.progress = min(self.progress + 3, 100)
            self.draw_circle()
            self.after(20, lambda: self._finish_animation(success))
        else:
            self.state = "success" if success else "error"
            self.draw_circle()

    def reset(self):
        """Reset to idle state"""
        if self.animation_id:
            self.after_cancel(self.animation_id)
            self.animation_id = None
        self.state = "idle"
        self.progress = 0
        self.target_progress = 0
        self.draw_circle()


class LicenseDialog(ctk.CTkToplevel):
    def __init__(self, parent, supabase_manager, error_msg=None):
        super().__init__(parent)
        self.title("License")
        self.configure(fg_color=COLORS["bg_dark"])
        self.resizable(False, False)
        self.parent = parent
        self.supabase = supabase_manager
        self.activated = False

        # Try to get existing license from local file for support
        existing_license = None
        try:
            if LICENSE_PATH.exists():
                with open(LICENSE_PATH, 'r') as f:
                    data = json.load(f)
                    existing_license = data.get("license_key")
        except:
            pass

        # Adjust window size based on whether we have license info to show
        has_info = existing_license or error_msg in ["Expired", "Reset", "HWID mismatch", "Deactivated", "Offline"]
        window_height = 320 if has_info else 250
        self.geometry(f"400x{window_height}")

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 400) // 2
        y = (self.winfo_screenheight() - window_height) // 2
        self.geometry(f"400x{window_height}+{x}+{y}")
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        if error_msg == "Expired":
            ctk.CTkLabel(self, text="⚠️ License Expired", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["error"]).pack(pady=(20, 5))
            ctk.CTkLabel(self, text="Contact support to renew", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(pady=(0, 10))
        elif error_msg == "Reset":
            ctk.CTkLabel(self, text="🔄 License Reset", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["warning"]).pack(pady=(20, 5))
            ctk.CTkLabel(self, text="Your license was reset by admin", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(pady=(0, 10))
        elif error_msg == "HWID mismatch":
            ctk.CTkLabel(self, text="🖥️ Device Changed", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["error"]).pack(pady=(20, 5))
            ctk.CTkLabel(self, text="Contact support for HWID reset", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(pady=(0, 10))
        elif error_msg == "Deactivated":
            ctk.CTkLabel(self, text="🚫 License Deactivated", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["error"]).pack(pady=(20, 5))
            ctk.CTkLabel(self, text="Contact support for help", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(pady=(0, 10))
        elif error_msg == "Offline":
            ctk.CTkLabel(self, text="📡 No Internet Connection", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["warning"]).pack(pady=(20, 5))
            ctk.CTkLabel(self, text="Connect to the internet to activate, or enter your key", font=ctk.CTkFont(size=11), text_color=COLORS["text_secondary"]).pack(pady=(0, 10))
        elif error_msg == "No license":
            ctk.CTkLabel(self, text="Enter License Key", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["text"]).pack(pady=(30, 20))
        else:
            # Show the error message if it's something else (like connection errors)
            ctk.CTkLabel(self, text="License Error", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["error"]).pack(pady=(20, 5))
            if error_msg:
                ctk.CTkLabel(self, text=error_msg, font=ctk.CTkFont(size=11), text_color=COLORS["text_secondary"]).pack(pady=(0, 10))

        # Show existing license for support (copyable)
        if existing_license:
            info_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=8)
            info_frame.pack(fill="x", padx=30, pady=(5, 10))
            ctk.CTkLabel(info_frame, text="Your license:", font=ctk.CTkFont(size=10),
                        text_color=COLORS["text_secondary"]).pack(anchor="w", padx=10, pady=(5, 0))
            license_display = ctk.CTkEntry(info_frame, width=260, height=28, justify="center",
                                           font=ctk.CTkFont(size=12, weight="bold"),
                                           fg_color=COLORS["bg_dark"], border_width=0)
            license_display.pack(padx=10, pady=(2, 8))
            license_display.insert(0, existing_license)
            license_display.configure(state="readonly")  # Make it copyable but not editable

        self.license_entry = ctk.CTkEntry(self, width=300, height=45, justify="center",
                                          placeholder_text="XXXX-XXXX-XXXX-XXXX",
                                          font=ctk.CTkFont(size=16))
        self.license_entry.pack(pady=(0, 10))
        self.license_entry.bind("<Return>", lambda e: self.activate())

        # Pre-fill with existing license if available
        if existing_license:
            self.license_entry.insert(0, existing_license)
            self.license_entry.select_range(0, 'end')

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11), text_color=COLORS["error"])
        self.status_label.pack(pady=(0, 10))

        self.activate_btn = ctk.CTkButton(self, text="Activate", width=150, height=40,
                                          fg_color=COLORS["accent"], hover_color=COLORS["accent_gradient_end"],
                                          text_color="#000", font=ctk.CTkFont(weight="bold"),
                                          command=self.activate)
        self.activate_btn.pack(pady=10)

    def activate(self):
        license_key = self.license_entry.get().strip()
        if not license_key:
            self.status_label.configure(text="Enter license key")
            return
        self.activate_btn.configure(state="disabled", text="...")
        self.status_label.configure(text="")
        def do_activate():
            success, message = self.supabase.activate_license(license_key)
            self.after(0, lambda: self._done(success, message))
        threading.Thread(target=do_activate, daemon=True).start()

    def _done(self, success, message):
        self.activate_btn.configure(state="normal", text="Activate")
        if success:
            self.activated = True
            self.destroy()
        else:
            self.status_label.configure(text=message)

    def on_close(self):
        if not self.activated:
            self.parent.destroy()
            sys.exit(0)
        self.destroy()


class UpdateDialog(ctk.CTkToplevel):
    def __init__(self, parent, update_info, auto_updater):
        super().__init__(parent)
        self.title("Update Available")
        self.geometry("450x200")
        self.configure(fg_color=COLORS["bg_dark"])
        self.resizable(False, False)
        self.parent = parent
        self.update_info = update_info
        self.auto_updater = auto_updater
        self.updating = False
        self.can_close = True
        self.force_update = update_info.get("force_update", False)
        self.user_skipped = False

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 450) // 2
        y = (self.winfo_screenheight() - 200) // 2
        self.geometry(f"450x200+{x}+{y}")
        self.transient(parent)
        self.grab_set()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        ctk.CTkLabel(self, text="New Version Available!",
                    font=ctk.CTkFont(size=20, weight="bold"),
                    text_color=COLORS["accent"]).pack(pady=(25, 10))

        ctk.CTkLabel(self, text=f"Version {update_info.get('version', '?')} is ready to install",
                    font=ctk.CTkFont(size=14),
                    text_color=COLORS["text"]).pack(pady=(0, 15))

        self.progress_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                           text_color=COLORS["warning"])
        self.progress_label.pack(pady=(10, 5))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=15)

        self.update_btn = ctk.CTkButton(btn_frame, text="Update Now", width=140, height=40,
                                        fg_color=COLORS["accent"],
                                        hover_color=COLORS["accent_gradient_end"],
                                        text_color="#000", font=ctk.CTkFont(weight="bold"),
                                        command=self.start_update)
        self.update_btn.pack(side="left", padx=5)

        if not self.force_update:
            self.skip_btn = ctk.CTkButton(btn_frame, text="Skip", width=100, height=40,
                                          fg_color=COLORS["bg_card"],
                                          hover_color=COLORS["bg_card_hover"],
                                          border_width=1, border_color=COLORS["border"],
                                          command=self.skip_update)
            self.skip_btn.pack(side="left", padx=5)
        else:
            ctk.CTkLabel(self, text="This update is required - you must update to continue",
                        font=ctk.CTkFont(size=10),
                        text_color=COLORS["error"]).pack()

    def start_update(self):
        self.updating = True
        self.can_close = False
        self.update_btn.configure(state="disabled", text="Updating...")
        if hasattr(self, 'skip_btn'):
            self.skip_btn.configure(state="disabled")

        def do_update():
            success, message = self.auto_updater.download_and_install(
                self.update_info.get("download_url"),
                progress_callback=lambda msg: self.after(0, lambda: self.progress_label.configure(text=msg))
            )
            if success:
                self.after(0, lambda: self.progress_label.configure(text="Closing app...", text_color=COLORS["success"]))
                self.after(500, self.force_exit)
            else:
                self.can_close = True
                self.after(0, lambda: self.update_failed(message))

        threading.Thread(target=do_update, daemon=True).start()

    def force_exit(self):
        try:
            self.parent.destroy()
        except:
            pass
        os._exit(0)

    def on_close(self):
        if self.updating and not self.can_close:
            return
        if self.force_update:
            try:
                self.parent.destroy()
            except:
                pass
            sys.exit(0)
        self.updating = False
        self.user_skipped = True
        self.destroy()

    def update_failed(self, message):
        self.updating = False
        self.progress_label.configure(text=f"Update failed: {message}", text_color=COLORS["error"])
        self.update_btn.configure(state="normal", text="Retry")
        if hasattr(self, 'skip_btn'):
            self.skip_btn.configure(state="normal")

    def skip_update(self):
        self.updating = False
        self.can_close = True
        self.user_skipped = True
        self.destroy()


class GeoApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("")  # Empty title for discretion
        self.geometry("700x650")
        self.minsize(650, 600)

        # Theme state
        self.is_dark_mode = True
        self.update_theme()

        # Set window icon
        icon_path = SCRIPT_DIR / "geo.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))

        self.supabase = SupabaseManager()
        self.auto_updater = AutoUpdater(SUPABASE_URL, SUPABASE_KEY)
        self.stats_manager = StatsManager()
        self.history_manager = HistoryManager()
        self.auto_check_job = None
        self.countdown_job = None

        # Check internet first, then updates
        self.after(100, self.check_internet_and_continue)

    # ... existing code ... <check_internet_and_continue through check_license methods>

    def check_internet_and_continue(self):
        def do_check():
            has_internet = check_internet_connection()
            self.after(0, lambda: self.handle_internet_result(has_internet))
        threading.Thread(target=do_check, daemon=True).start()

    def handle_internet_result(self, has_internet):
        if not has_internet:
            messagebox.showerror(
                "No Internet Connection",
                "This app requires an internet connection to work.\n\n"
                "Please check your connection and try again."
            )
            self.destroy()
            sys.exit(0)
        else:
            self.check_for_updates()

    def update_theme(self):
        global COLORS
        if self.is_dark_mode:
            COLORS = COLORS_DARK.copy()
            ctk.set_appearance_mode("dark")
        else:
            COLORS = COLORS_LIGHT.copy()
            ctk.set_appearance_mode("light")
        self.configure(fg_color=COLORS["bg_dark"])

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.update_theme()
        self.refresh_ui_colors()

    def refresh_ui_colors(self):
        try:
            self.configure(fg_color=COLORS["bg_dark"])
            if hasattr(self, 'main_container'):
                for widget in self.main_container.winfo_children():
                    widget.destroy()
                self.create_header()
                self.content_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
                self.content_frame.pack(fill="both", expand=True, pady=(20, 0))
                self.dashboard_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
                self.settings_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
                self.create_dashboard()
                self.create_settings()
                self.show_dashboard()
                self.load_config()
        except:
            pass

    def check_for_updates(self):
        def do_check():
            update_info = self.auto_updater.check_for_updates()
            self.after(0, lambda: self.handle_update_result(update_info))
        threading.Thread(target=do_check, daemon=True).start()

    def handle_update_result(self, update_info):
        if update_info.get("available"):
            self.show_update_dialog(update_info)
        else:
            self.check_license()

    def show_update_dialog(self, update_info):
        dialog = UpdateDialog(self, update_info, self.auto_updater)
        self.wait_window(dialog)
        if not dialog.updating:
            self.check_license()

    def check_license(self):
        is_valid, message = self.supabase.check_license()
        if not is_valid:
            dialog = LicenseDialog(self, self.supabase, message)
            self.wait_window(dialog)
            if dialog.activated:
                self.agent_name = self.supabase.agent_name
                self.days_left = self.supabase.days_left
                self.initialize_app()
            else:
                self.destroy()
                sys.exit(0)
        else:
            self.agent_name = message
            self.days_left = self.supabase.days_left
            self.initialize_app()

    def initialize_app(self):
        self.after(100, check_and_setup_startup)
        self.port = 50080
        self.base_uri = f"http://localhost:{self.port}"
        self.headers = {}
        self.is_running = False
        self.browser_driver = None
        self.current_data = {
            "ip": "--", "country": "--", "state": "--", "city": "--", "status": "unknown",
            "lat": "--", "lon": "--", "coord_country": "--", "coord_state": "--", "coord_city": "--",
            "isp": "--", "hostname": "--", "ip_type": "--", "ip_version": "--"
        }
        self.allowed_countries = DEFAULT_ALLOWED_COUNTRIES.copy()
        self.allowed_states = DEFAULT_ALLOWED_STATES.copy()
        self.next_check_time = None
        self.auto_interval = 5
        self.create_widgets()
        self.after(200, self.load_config)
        self.after(1000, self.auto_run_on_boot)

    def is_system_just_booted(self, max_minutes=3):
        try:
            uptime = get_system_uptime_minutes()
            print(f"System uptime: {uptime:.1f} minutes")
            return uptime <= max_minutes
        except:
            return False

    def auto_run_on_boot(self):
        # Check if app should auto-run:
        # 1. Started with --autostart argument (from Registry)
        # 2. Running from Startup folder
        should_auto_run = "--autostart" in sys.argv or is_running_from_startup()

        if not should_auto_run:
            print("Manual launch - skipping auto-check")
            return

        print("Auto-start detected - running check...")
        try:
            u = self.username_entry.get().strip()
            p = self.password_entry.get().strip()

            # Check if using auto GPS mode
            use_auto_coords = hasattr(self, 'gps_mode_var') and self.gps_mode_var.get() == "auto"

            if use_auto_coords:
                # Auto GPS mode - only need username and password
                if all([u, p]):
                    self.run_check()
                else:
                    print("Auto-check skipped: missing username/password")
            else:
                # Custom GPS mode - need all fields
                lat_s = self.lat_entry.get().strip()
                lon_s = self.lon_entry.get().strip()
                if all([u, p, lat_s, lon_s]):
                    self.run_check()
                else:
                    print("Auto-check skipped: missing configuration")
        except Exception as e:
            print(f"Auto-check error: {e}")

    def create_widgets(self):
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=15, pady=15)
        self.create_header()
        self.content_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, pady=(15, 0))
        self.dashboard_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.details_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.settings_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.create_dashboard()
        self.create_details()
        self.create_settings()
        self.show_dashboard()

    def create_header(self):
        """Minimal header with navigation only"""
        hf = ctk.CTkFrame(self.main_container, fg_color="transparent")
        hf.pack(fill="x")

        # Navigation buttons only - right side
        nav = ctk.CTkFrame(hf, fg_color="transparent")
        nav.pack(side="right")

        self.dashboard_btn = ctk.CTkButton(nav, text="⌂", width=40, height=35, corner_radius=8,
                                           fg_color=COLORS["accent"], hover_color=COLORS["accent_gradient_end"],
                                           text_color="#000", font=ctk.CTkFont(size=18, weight="bold"),
                                           command=self.show_dashboard)
        self.dashboard_btn.pack(side="left", padx=3)

        self.details_btn = ctk.CTkButton(nav, text="◉", width=40, height=35, corner_radius=8,
                                          fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
                                          border_width=1, border_color=COLORS["border"],
                                          font=ctk.CTkFont(size=16),
                                          command=self.show_details)
        self.details_btn.pack(side="left", padx=3)

        self.settings_btn = ctk.CTkButton(nav, text="⚙", width=40, height=35, corner_radius=8,
                                          fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
                                          border_width=1, border_color=COLORS["border"],
                                          font=ctk.CTkFont(size=16),
                                          command=self.show_settings)
        self.settings_btn.pack(side="left", padx=3)

        self.version_label = ctk.CTkLabel(nav, text=f"v{APP_VERSION}",
                                          font=ctk.CTkFont(size=9),
                                          text_color=COLORS["text_secondary"])
        self.version_label.pack(side="left", padx=(10, 0))
        self.version_label.pack_forget()

    def create_dashboard(self):
        status_container = ctk.CTkFrame(self.dashboard_frame, fg_color=COLORS["bg_card"], corner_radius=20)
        status_container.pack(fill="both", expand=True, pady=(0, 15))

        center = ctk.CTkFrame(status_container, fg_color="transparent")
        center.place(relx=0.5, rely=0.45, anchor="center")

        self.status_circle = AnimatedCircle(center, size=180)
        self.status_circle.pack()

        btn_container = ctk.CTkFrame(status_container, fg_color="transparent")
        btn_container.place(relx=0.5, rely=0.85, anchor="center")

        self.run_btn = ctk.CTkButton(btn_container, text="▶  Start", width=140, height=45, corner_radius=22,
                                      fg_color=COLORS["accent"], hover_color=COLORS["accent_gradient_end"],
                                      text_color="#000", font=ctk.CTkFont(size=15, weight="bold"),
                                      command=self.run_check)
        self.run_btn.pack()

        # Auto-close countdown (hidden until a successful check)
        self.auto_close_job = None
        self.auto_close_frame = ctk.CTkFrame(status_container, fg_color="transparent")
        self.auto_close_label = ctk.CTkLabel(self.auto_close_frame, text="",
                                             font=ctk.CTkFont(size=11),
                                             text_color=COLORS["text_secondary"])
        self.auto_close_label.pack(side="left", padx=(0, 8))
        self.auto_close_cancel_btn = ctk.CTkButton(self.auto_close_frame, text="✕ Cancel", width=70, height=24,
                                                   corner_radius=12, fg_color=COLORS["bg_card"],
                                                   hover_color=COLORS["border"], text_color=COLORS["text"],
                                                   border_width=1, border_color=COLORS["border"],
                                                   font=ctk.CTkFont(size=11),
                                                   command=self.cancel_auto_close)
        self.auto_close_cancel_btn.pack(side="left")

        # Animation state for button dots
        self.btn_animation_id = None
        self.btn_dot_phase = 0

    def create_details(self):
        """Details page with IP and GPS info cards"""
        scroll = ctk.CTkScrollableFrame(self.details_frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # IP Information Card
        ip_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        ip_card.pack(fill="x", pady=(0, 10))

        self.ip_label = ctk.CTkLabel(ip_card, text="---.---.---.---",
                                     font=ctk.CTkFont(size=18, weight="bold"),
                                     text_color=COLORS["text"])
        self.ip_label.pack(pady=(15, 2))

        ctk.CTkLabel(ip_card, text="Public IP", font=ctk.CTkFont(size=10),
                    text_color=COLORS["text_secondary"]).pack(pady=(0, 10))

        sep = ctk.CTkFrame(ip_card, fg_color=COLORS["border"], height=1)
        sep.pack(fill="x", padx=15, pady=5)

        details_frame = ctk.CTkFrame(ip_card, fg_color="transparent")
        details_frame.pack(fill="x", padx=15, pady=(5, 15))

        self.ip_country_row = self._create_detail_row(details_frame, "Country:", "--")
        self.ip_location_row = self._create_detail_row(details_frame, "Location:", "--")
        self.ip_isp_row = self._create_detail_row(details_frame, "ISP:", "--")
        self.ip_hostname_row = self._create_detail_row(details_frame, "Hostname:", "--")
        self.ip_type_row = self._create_detail_row(details_frame, "Type:", "--")
        self.ip_version_row = self._create_detail_row(details_frame, "Version:", "--")
        self.ip_status_row = self._create_detail_row(details_frame, "Status:", "--")

        gps_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        gps_card.pack(fill="x", pady=(0, 10))

        gps_header = ctk.CTkFrame(gps_card, fg_color="transparent")
        gps_header.pack(fill="x", padx=15, pady=(12, 8))
        ctk.CTkLabel(gps_header, text="📍 GPS Coordinates", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=COLORS["accent"]).pack(side="left")

        sep2 = ctk.CTkFrame(gps_card, fg_color=COLORS["border"], height=1)
        sep2.pack(fill="x", padx=15)

        gps_details = ctk.CTkFrame(gps_card, fg_color="transparent")
        gps_details.pack(fill="x", padx=15, pady=(8, 15))

        self.gps_coords_row = self._create_detail_row(gps_details, "Coords:", "--")
        self.gps_location_row = self._create_detail_row(gps_details, "Location:", "--")
        self.gps_status_row = self._create_detail_row(gps_details, "Status:", "--")

    def _create_detail_row(self, parent, label, value):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=11),
                    text_color=COLORS["text_secondary"], width=70, anchor="w").pack(side="left")
        val_label = ctk.CTkLabel(row, text=value, font=ctk.CTkFont(size=11),
                                text_color=COLORS["text"], anchor="w")
        val_label.pack(side="left", fill="x", expand=True)
        return val_label



    def toggle_auto_check(self):
        if self.auto_switch.get():
            self.start_auto_check()
        else:
            self.stop_auto_check()

    def start_auto_check(self):
        try:
            self.auto_interval = int(self.interval_entry.get() or "5")
        except:
            self.auto_interval = 5

        interval_ms = self.auto_interval * 60 * 1000
        self.auto_label.configure(text="ON", text_color=COLORS["success"])
        self.countdown_label.configure(text=f"Checking every {self.auto_interval} min", text_color=COLORS["success"])

        def run_and_schedule():
            if self.auto_switch.get() and not self.is_running:
                self.run_check()
                self.next_check_time = datetime.now() + __import__('datetime').timedelta(minutes=self.auto_interval)
            if self.auto_switch.get():
                self.auto_check_job = self.after(interval_ms, run_and_schedule)

        if not self.is_running:
            self.run_check()
        self.next_check_time = datetime.now() + __import__('datetime').timedelta(minutes=self.auto_interval)
        self.auto_check_job = self.after(interval_ms, run_and_schedule)
        self.countdown_job = self.after(1000, self.update_countdown)

    def stop_auto_check(self):
        if self.auto_check_job:
            self.after_cancel(self.auto_check_job)
            self.auto_check_job = None
        if self.countdown_job:
            self.after_cancel(self.countdown_job)
            self.countdown_job = None
        self.auto_label.configure(text="OFF", text_color=COLORS["text_secondary"])
        self.countdown_label.configure(text="")

    def update_countdown(self):
        if not self.auto_switch.get():
            return
        if self.next_check_time:
            remaining = (self.next_check_time - datetime.now()).total_seconds()
            if remaining > 0:
                mins, secs = int(remaining // 60), int(remaining % 60)
                self.countdown_label.configure(text=f"Next check in {mins}:{secs:02d}", text_color=COLORS["accent"])
            else:
                self.countdown_label.configure(text="Checking...", text_color=COLORS["warning"])
        self.countdown_job = self.after(1000, self.update_countdown)

    def show_dashboard(self):
        self.settings_frame.pack_forget()
        self.details_frame.pack_forget()
        self.dashboard_frame.pack(fill="both", expand=True)
        self.dashboard_btn.configure(fg_color=COLORS["accent"], text_color="#000", border_width=0)
        self.details_btn.configure(fg_color=COLORS["bg_card"], text_color=COLORS["text"], border_width=1)
        self.settings_btn.configure(fg_color=COLORS["bg_card"], text_color=COLORS["text"], border_width=1)
        if hasattr(self, 'version_label'):
            self.version_label.pack_forget()

    def show_details(self):
        self.cancel_auto_close()
        self.dashboard_frame.pack_forget()
        self.settings_frame.pack_forget()
        self.details_frame.pack(fill="both", expand=True)
        self.details_btn.configure(fg_color=COLORS["accent"], text_color="#000", border_width=0)
        self.dashboard_btn.configure(fg_color=COLORS["bg_card"], text_color=COLORS["text"], border_width=1)
        self.settings_btn.configure(fg_color=COLORS["bg_card"], text_color=COLORS["text"], border_width=1)
        if hasattr(self, 'version_label'):
            self.version_label.pack_forget()

    def show_settings(self):
        self.cancel_auto_close()
        self.dashboard_frame.pack_forget()
        self.details_frame.pack_forget()
        self.settings_frame.pack(fill="both", expand=True)
        self.settings_btn.configure(fg_color=COLORS["accent"], text_color="#000", border_width=0)
        self.dashboard_btn.configure(fg_color=COLORS["bg_card"], text_color=COLORS["text"], border_width=1)
        self.details_btn.configure(fg_color=COLORS["bg_card"], text_color=COLORS["text"], border_width=1)
        if hasattr(self, 'version_label'):
            self.version_label.pack(side="left", padx=(10, 0))

    def start_auto_close_countdown(self):
        # Skip while periodic auto-check is ON: closing would stop the monitoring loop
        if hasattr(self, 'auto_switch') and self.auto_switch.get():
            return
        self.cancel_auto_close()
        self.auto_close_remaining = 3
        self.auto_close_frame.place(relx=0.5, rely=0.97, anchor="s")
        self._tick_auto_close()

    def _tick_auto_close(self):
        if self.auto_close_remaining <= 0:
            self.destroy()
            return
        self.auto_close_label.configure(text=f"Closing in {self.auto_close_remaining}s")
        self.auto_close_remaining -= 1
        self.auto_close_job = self.after(1000, self._tick_auto_close)

    def cancel_auto_close(self):
        if getattr(self, 'auto_close_job', None):
            self.after_cancel(self.auto_close_job)
            self.auto_close_job = None
        if hasattr(self, 'auto_close_frame'):
            self.auto_close_frame.place_forget()

    def update_status(self, status, msg):
        if status == "ready":
            self.status_circle.reset()
            self._stop_btn_animation()
            self.run_btn.configure(state="normal", text="▶  Start")
        elif status == "running":
            self.status_circle.start()
            self.run_btn.configure(state="disabled", text="")
            self._start_btn_animation()
        elif status == "success":
            self._stop_btn_animation()
            self.status_circle.finish(success=True)
            self.run_btn.configure(state="normal", text="▶  Start")
        elif status == "error":
            self._stop_btn_animation()
            self.status_circle.finish(success=False)
            self.run_btn.configure(state="normal", text="▶  Start")

    def set_progress(self, percent):
        """Update circle progress from check steps"""
        if hasattr(self, 'status_circle'):
            self.status_circle.set_progress(percent)

    def _start_btn_animation(self):
        """Start animated dots in the button"""
        self.btn_dot_phase = 0
        self.btn_animating = True
        self._animate_btn_dots()

    def _animate_btn_dots(self):
        """Animate dots in button: ●○○ → ○●○ → ○○● → ..."""
        # Check if we should continue animating
        if not getattr(self, 'btn_animating', False):
            return

        dots = ["○", "○", "○"]
        filled_idx = self.btn_dot_phase % 3
        dots[filled_idx] = "●"

        self.run_btn.configure(text=f"  {dots[0]}  {dots[1]}  {dots[2]}  ")
        self.btn_dot_phase += 1
        self.btn_animation_id = self.after(300, self._animate_btn_dots)

    def _stop_btn_animation(self):
        """Stop button animation"""
        self.btn_animating = False
        if hasattr(self, 'btn_animation_id') and self.btn_animation_id:
            self.after_cancel(self.btn_animation_id)
            self.btn_animation_id = None

    def update_details(self):
        ip_valid = self.current_data.get("ip_valid")
        if ip_valid is True:
            ip_color = COLORS["success"]
            ip_status = "✓ Valid"
        elif ip_valid is False:
            ip_color = COLORS["error"]
            ip_status = "✗ Invalid"
        else:
            ip_color = COLORS["text"]
            ip_status = "--"

        self.ip_label.configure(text=self.current_data.get("ip", "---.---.---.---"), text_color=ip_color)
        self.ip_country_row.configure(text=self.current_data.get("country", "--"))
        self.ip_location_row.configure(text=f"{self.current_data.get('city', '--')}, {self.current_data.get('state', '--')}")
        self.ip_isp_row.configure(text=self.current_data.get("isp", "--"))
        self.ip_hostname_row.configure(text=self.current_data.get("hostname", "--"))
        self.ip_type_row.configure(text=self.current_data.get("ip_type", "--"))
        self.ip_version_row.configure(text=self.current_data.get("ip_version", "--"))
        self.ip_status_row.configure(text=ip_status, text_color=ip_color)

        coord_valid = self.current_data.get("coord_valid")
        if coord_valid is True:
            gps_color = COLORS["success"]
            gps_status = "✓ Valid"
        elif coord_valid is False:
            gps_color = COLORS["error"]
            gps_status = "✗ Invalid"
        else:
            gps_color = COLORS["text"]
            gps_status = "--"

        lat = self.current_data.get("lat", "--")
        lon = self.current_data.get("lon", "--")
        self.gps_coords_row.configure(text=f"{lat}, {lon}")
        coord_city = self.current_data.get("coord_city", "--")
        coord_state = self.current_data.get("coord_state", "--")
        self.gps_location_row.configure(text=f"{coord_city}, {coord_state}")
        self.gps_status_row.configure(text=gps_status, text_color=gps_color)

    def send_notification(self, title, msg):
        if NOTIFICATIONS_AVAILABLE:
            try:
                Notification(app_id="Location Service", title=title, msg=msg, duration="short").show()
            except:
                pass
        if SOUND_AVAILABLE:
            try:
                winsound.MessageBeep()
            except:
                pass

    def load_config(self):
        config = None
        try:
            config = self.supabase.load_config()
        except:
            pass
        if not config and LOCAL_CONFIG_PATH.exists():
            try:
                with open(LOCAL_CONFIG_PATH, "r") as f:
                    config = json.load(f)
            except:
                pass

        if config:
            self.username_entry.delete(0, "end")
            self.username_entry.insert(0, config.get("username", ""))
            self.password_entry.delete(0, "end")
            self.password_entry.insert(0, config.get("password", ""))
            self.lat_entry.delete(0, "end")
            self.lat_entry.insert(0, config.get("latitude", ""))
            self.lon_entry.delete(0, "end")
            self.lon_entry.insert(0, config.get("longitude", ""))
            self.countries_entry.delete("1.0", "end")
            countries = config.get("allowed_countries", DEFAULT_ALLOWED_COUNTRIES)
            self.allowed_countries = countries if isinstance(countries, list) else DEFAULT_ALLOWED_COUNTRIES
            self.countries_entry.insert("1.0", ", ".join(self.allowed_countries))
            self.states_entry.delete("1.0", "end")
            states = config.get("allowed_states", DEFAULT_ALLOWED_STATES)
            self.allowed_states = states if isinstance(states, list) else DEFAULT_ALLOWED_STATES
            self.states_entry.insert("1.0", ", ".join(self.allowed_states))
            self.interval_entry.delete(0, "end")
            self.interval_entry.insert(0, config.get("service_interval", "5"))
            try:
                if hasattr(self, 'telegram_switch') and hasattr(self, 'telegram_chat_ids'):
                    if config.get("telegram_enabled"):
                        self.telegram_switch.select()
                    else:
                        self.telegram_switch.deselect()
                    self.telegram_chat_ids.delete(0, "end")
                    self.telegram_chat_ids.insert(0, config.get("telegram_chat_ids", ""))
            except Exception as e:
                print(f"Error loading telegram settings: {e}")

            # Load GPS mode
            try:
                if hasattr(self, 'gps_mode_var'):
                    gps_mode = config.get("gps_mode", "custom")
                    self.gps_mode_var.set(gps_mode)
                    self.toggle_gps_mode()  # Apply the state
            except Exception as e:
                print(f"Error loading gps mode: {e}")

            # Load alert filters
            try:
                if hasattr(self, 'alert_ip_var'):
                    self.alert_ip_var.set(config.get("alert_ip", True))
                if hasattr(self, 'alert_gps_var'):
                    self.alert_gps_var.set(config.get("alert_gps", True))
                if hasattr(self, 'alert_on_fail_var'):
                    self.alert_on_fail_var.set(config.get("alert_on_fail", True))
                if hasattr(self, 'alert_on_success_var'):
                    self.alert_on_success_var.set(config.get("alert_on_success", False))
            except Exception as e:
                print(f"Error loading alert filters: {e}")

    def save_config(self):
        try:
            countries = [c.strip() for c in self.countries_entry.get("1.0", "end").strip().split(",") if c.strip()]
            states = [s.strip() for s in self.states_entry.get("1.0", "end").strip().split(",") if s.strip()]
            config = {
                "username": self.username_entry.get().strip(),
                "password": self.password_entry.get().strip(),
                "latitude": self.lat_entry.get().strip(),
                "longitude": self.lon_entry.get().strip(),
                "allowed_countries": countries,
                "allowed_states": states,
                "service_interval": self.interval_entry.get().strip() or "5",
                "telegram_enabled": self.telegram_switch.get() if hasattr(self, 'telegram_switch') else False,
                "telegram_chat_ids": self.telegram_chat_ids.get().strip() if hasattr(self, 'telegram_chat_ids') else "",
                "gps_mode": self.gps_mode_var.get() if hasattr(self, 'gps_mode_var') else "custom",
                # Alert filters
                "alert_ip": self.alert_ip_var.get() if hasattr(self, 'alert_ip_var') else True,
                "alert_gps": self.alert_gps_var.get() if hasattr(self, 'alert_gps_var') else True,
                "alert_on_fail": self.alert_on_fail_var.get() if hasattr(self, 'alert_on_fail_var') else True,
                "alert_on_success": self.alert_on_success_var.get() if hasattr(self, 'alert_on_success_var') else False,
            }
            self.allowed_countries = countries
            self.allowed_states = states
            self.supabase.save_config(config)
            with open(LOCAL_CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
            messagebox.showinfo("Success", "Settings saved!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def get_auth_headers(self, u, p):
        return {"Authorization": f"Basic {base64.b64encode(f'{u}:{p}'.encode()).decode()}"}

    def test_device_portal(self):
        try:
            r = requests.get(f"{self.base_uri}/api/os/info", headers=self.headers, timeout=5)
            if r.status_code == 401:
                return False, "auth_failed"
            elif r.status_code == 200:
                return True, "ok"
            else:
                return False, "unavailable"
        except requests.exceptions.ConnectionError:
            return False, "unavailable"
        except:
            return False, "unavailable"

    def get_available_browser(self):
        if not SELENIUM_AVAILABLE:
            return None
        try:
            from selenium.webdriver.edge.options import Options as EO
            o = EO()
            o.add_argument("--headless=new")
            o.add_argument("--disable-gpu")
            o.add_argument("--no-sandbox")
            o.add_argument("--ignore-certificate-errors")
            o.add_argument("--log-level=3")
            o.add_experimental_option('excludeSwitches', ['enable-logging'])
            try:
                from webdriver_manager.microsoft import EdgeChromiumDriverManager
                from selenium.webdriver.edge.service import Service
                return webdriver.Edge(service=Service(EdgeChromiumDriverManager().install()), options=o)
            except:
                return webdriver.Edge(options=o)
        except:
            pass
        try:
            from selenium.webdriver.chrome.options import Options as CO
            o = CO()
            o.add_argument("--headless=new")
            o.add_argument("--disable-gpu")
            o.add_argument("--ignore-certificate-errors")
            o.add_argument("--log-level=3")
            o.add_experimental_option('excludeSwitches', ['enable-logging'])
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                from selenium.webdriver.chrome.service import Service
                return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=o)
            except:
                return webdriver.Chrome(options=o)
        except:
            pass
        return None

    def activate_location_service(self):
        if not SELENIUM_AVAILABLE:
            return False
        try:
            d = self.get_available_browser()
            if not d:
                return False
            self.browser_driver = d
            d.get(f"http://localhost:{self.port}/#Location")
            time.sleep(2)
            if "certprompt" in d.current_url.lower():
                try:
                    d.execute_script("document.querySelectorAll('input[type=\"checkbox\"]').forEach(c=>{if(!c.checked)c.click()});")
                    time.sleep(0.5)
                    d.execute_script("document.querySelectorAll('button').forEach(b=>{if(b.textContent.toLowerCase().includes('continue'))b.click()});")
                    time.sleep(2)
                except:
                    pass
            d.get(f"http://localhost:{self.port}/#Location")
            time.sleep(2)
            return True
        except:
            return False
        finally:
            if self.browser_driver:
                try:
                    self.browser_driver.quit()
                except:
                    pass
                self.browser_driver = None

    def initialize_location(self):
        for ep in [f"{self.base_uri}/ext/location",
                   f"{self.base_uri}/ext/location/override",
                   f"{self.base_uri}/ext/location/position"]:
            try:
                requests.get(ep, headers=self.headers, timeout=5)
            except:
                pass
        time.sleep(1)

    def set_position(self, lat, lon):
        try:
            r1 = requests.put(f"{self.base_uri}/ext/location/override",
                        headers={**self.headers, "Content-Type": "application/json"},
                        json={"Override": True}, timeout=5)
            print(f"Override response: {r1.status_code}")

            if r1.status_code == 401:
                return False, "auth_failed"
            if r1.status_code not in [200, 204]:
                return False, "override_failed"

            r2 = requests.put(f"{self.base_uri}/ext/location/position",
                        headers={**self.headers, "Content-Type": "application/json"},
                        json={"Latitude": lat, "Longitude": lon, "Altitude": 0}, timeout=5)
            print(f"Position response: {r2.status_code}")

            if r2.status_code == 401:
                return False, "auth_failed"
            if r2.status_code not in [200, 204]:
                return False, "position_failed"

            return True, "ok"
        except requests.exceptions.ConnectionError:
            return False, "connection_failed"
        except Exception as e:
            print(f"set_position error: {e}")
            return False, str(e)

    def get_position(self):
        try:
            r = requests.get(f"{self.base_uri}/ext/location/position", headers=self.headers, timeout=5)
            if r.status_code == 200:
                return r.json()
            return None
        except:
            return None

    def get_public_ip(self):
        for url, t in [("https://api.ipify.org?format=json", "json"), ("https://ipv4.icanhazip.com/", "text")]:
            try:
                r = requests.get(url, timeout=10)
                return r.json().get("ip") if t == "json" else r.text.strip()
            except:
                continue
        return None

    def get_location_data(self, ip):
        try:
            fields = "status,country,countryCode,region,regionName,city,isp,reverse,proxy,hosting,mobile,lat,lon"
            d = requests.get(f"http://ip-api.com/json/{ip}?fields={fields}", timeout=10).json()
            if d.get("status") == "success":
                if d.get("hosting"):
                    ip_type = "Datacenter"
                elif d.get("proxy"):
                    ip_type = "Proxy/VPN"
                elif d.get("mobile"):
                    ip_type = "Mobile"
                else:
                    ip_type = "Residential"
                ip_version = "IPv6" if ":" in ip else "IPv4"
                return {
                    "country": d.get("country", "Unknown"),
                    "city": d.get("city", "Unknown"),
                    "state": d.get("regionName", "Unknown"),
                    "isp": d.get("isp", "Unknown"),
                    "hostname": d.get("reverse", "No hostname") or "No hostname",
                    "ip_type": ip_type,
                    "ip_version": ip_version,
                    "lat": d.get("lat"),
                    "lon": d.get("lon"),
                }
        except Exception as e:
            print(f"get_location_data error: {e}")
        return None

    def get_location_from_coordinates(self, lat, lon):
        try:
            print(f"Trying Nominatim for {lat}, {lon}")
            d = requests.get(
                f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&addressdetails=1",
                headers={"User-Agent": "GeoApp/8.33"},
                timeout=15
            ).json()
            print(f"Nominatim response: {d}")
            if "address" in d:
                a = d["address"]
                return {
                    "country": a.get("country", "Unknown"),
                    "state": a.get("state", a.get("region", a.get("province", "Unknown"))),
                    "city": a.get("city", a.get("town", a.get("village", a.get("municipality", a.get("county", "Unknown")))))
                }
        except Exception as e:
            print(f"Nominatim error: {e}")

        try:
            print(f"Trying BigDataCloud for {lat}, {lon}")
            d = requests.get(
                f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en",
                timeout=15
            ).json()
            print(f"BigDataCloud response: {d}")
            return {
                "country": d.get("countryName", "Unknown"),
                "state": d.get("principalSubdivision", "Unknown"),
                "city": d.get("city", d.get("locality", "Unknown"))
            }
        except Exception as e:
            print(f"BigDataCloud error: {e}")

        try:
            print(f"Trying geocode.xyz for {lat}, {lon}")
            d = requests.get(
                f"https://geocode.xyz/{lat},{lon}?geoit=json",
                timeout=15
            ).json()
            print(f"geocode.xyz response: {d}")
            if d.get("country"):
                return {
                    "country": d.get("country", "Unknown"),
                    "state": d.get("state", d.get("region", "Unknown")),
                    "city": d.get("city", "Unknown")
                }
        except Exception as e:
            print(f"geocode.xyz error: {e}")

        return None

    def is_location_allowed(self, country, state):
        if not country:
            return False, "country"

        country_aliases = {
            "usa": ["united states", "us", "usa", "america", "united states of america", "u.s.", "u.s.a."],
            "uk": ["united kingdom", "uk", "great britain", "england", "gb", "britain"],
            "uae": ["united arab emirates", "uae", "emirates"],
        }

        state_aliases = {
            "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas",
            "ca": "california", "co": "colorado", "ct": "connecticut", "de": "delaware",
            "fl": "florida", "ga": "georgia", "hi": "hawaii", "id": "idaho",
            "il": "illinois", "in": "indiana", "ia": "iowa", "ks": "kansas",
            "ky": "kentucky", "la": "louisiana", "me": "maine", "md": "maryland",
            "ma": "massachusetts", "mi": "michigan", "mn": "minnesota", "ms": "mississippi",
            "mo": "missouri", "mt": "montana", "ne": "nebraska", "nv": "nevada",
            "nh": "new hampshire", "nj": "new jersey", "nm": "new mexico", "ny": "new york",
            "nc": "north carolina", "nd": "north dakota", "oh": "ohio", "ok": "oklahoma",
            "or": "oregon", "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina",
            "sd": "south dakota", "tn": "tennessee", "tx": "texas", "ut": "utah",
            "vt": "vermont", "va": "virginia", "wa": "washington", "wv": "west virginia",
            "wi": "wisconsin", "wy": "wyoming", "dc": "district of columbia",
            "pr": "puerto rico", "vi": "virgin islands", "gu": "guam"
        }

        state_aliases_reverse = {v: k for k, v in state_aliases.items()}

        def normalize_country(c):
            c_lower = c.lower().strip()
            for key, aliases in country_aliases.items():
                if c_lower in aliases or any(c_lower in alias or alias in c_lower for alias in aliases):
                    return key
            return c_lower

        def normalize_state(s):
            if not s:
                return ""
            s_lower = s.lower().strip()
            if s_lower in state_aliases:
                return state_aliases[s_lower]
            if s_lower in state_aliases_reverse:
                return s_lower
            return s_lower

        def matches_country(allowed, actual):
            allowed_norm = normalize_country(allowed)
            actual_norm = normalize_country(actual)
            if allowed_norm == actual_norm:
                return True
            if allowed_norm in actual_norm or actual_norm in allowed_norm:
                return True
            return False

        def matches_state(allowed, actual):
            if not actual:
                return False

            allowed_norm = normalize_state(allowed)
            actual_norm = normalize_state(actual)

            if allowed_norm == actual_norm:
                return True

            allowed_lower = allowed.lower().strip()
            actual_lower = actual.lower().strip()

            if allowed_lower in state_aliases and state_aliases[allowed_lower] == actual_norm:
                return True

            if actual_lower in state_aliases and state_aliases[actual_lower] == allowed_norm:
                return True

            if allowed_norm in actual_norm or actual_norm in allowed_norm:
                return True

            return False

        country_ok = any(matches_country(c, country) for c in self.allowed_countries)
        if not country_ok:
            return False, "country"

        if self.allowed_states:
            state_ok = any(matches_state(s, state) for s in self.allowed_states)
            if not state_ok:
                return False, "state"

        return True, None

    def run_check(self):
        if self.is_running:
            return
        self.cancel_auto_close()
        u = self.username_entry.get().strip()
        p = self.password_entry.get().strip()

        use_auto_coords = hasattr(self, 'gps_mode_var') and self.gps_mode_var.get() == "auto"

        if not u:
            self.show_settings()
            messagebox.showwarning("Settings Required", "Username is required")
            return
        if not p:
            self.show_settings()
            messagebox.showwarning("Settings Required", "Password is required")
            return

        lat, lon = None, None

        if use_auto_coords:
            pass
        else:
            lat_s = self.lat_entry.get().strip()
            lon_s = self.lon_entry.get().strip()

            if not lat_s:
                self.show_settings()
                messagebox.showwarning("Settings Required", "Latitude is required")
                return
            if not lon_s:
                self.show_settings()
                messagebox.showwarning("Settings Required", "Longitude is required")
                return

            try:
                lat, lon = float(lat_s), float(lon_s)
            except:
                messagebox.showerror("Error", "Invalid coordinates!")
                return

        self.base_uri = "http://localhost:50080"
        self.headers = self.get_auth_headers(u, p)
        self.is_running = True
        self.run_btn.configure(state="disabled", text="...")

        threading.Thread(target=self._run_check, args=(lat, lon, use_auto_coords), daemon=True).start()

    def _run_check(self, lat, lon, use_auto_coords=False):
        errors = []
        ip_loc = None
        gps_loc = None
        ip = None

        def update_progress(percent):
            """Update progress from background thread"""
            self.after(0, lambda: self.set_progress(percent))

        def finish_error(msg):
            """Handle critical system errors - these ALWAYS send alerts (not filtered by IP/GPS)"""
            self.current_data["status"] = "error"
            self.update_status("error", msg)
            self.update_details()
            self.send_notification("Error", msg)
            self.supabase.log_check(ip, ip_loc, gps_loc, "error", msg)
            self.stats_manager.record_check(False)
            play_sound(success=False)

            # Send Telegram alert for critical system errors
            # These are NOT filtered by IP/GPS - only by alert_on_fail
            agent_chat_ids = self.telegram_chat_ids.get().strip() if self.telegram_switch.get() else ""
            agent_alert_on_fail = self.alert_on_fail_var.get() if hasattr(self, 'alert_on_fail_var') else True
            agent_alert_on_success = self.alert_on_success_var.get() if hasattr(self, 'alert_on_success_var') else False

            # The filtering is now done inside send_telegram_alert
            send_telegram_alert(
                self.supabase.license_key,
                "error",
                self.current_data.get("ip", "unknown"),
                f"{self.current_data.get('city', '--')}, {self.current_data.get('state', '--')}",
                msg,
                agent_chat_ids,
                error_type="system",  # System error - not IP or GPS
                alert_ip=True,   # Not used for system errors
                alert_gps=True,  # Not used for system errors
                alert_on_fail=agent_alert_on_fail,
                alert_on_success=agent_alert_on_success
            )

        try:
            update_progress(5)

            if use_auto_coords:
                self.update_status("running", "Getting IP coordinates...")
                update_progress(10)
                ip = self.get_public_ip()
                if ip:
                    ip_loc_temp = self.get_location_data(ip)
                    if ip_loc_temp and ip_loc_temp.get("lat") and ip_loc_temp.get("lon"):
                        lat = ip_loc_temp["lat"]
                        lon = ip_loc_temp["lon"]
                        update_progress(15)
                    else:
                        finish_error("Could not get coordinates from IP")
                        return
                else:
                    finish_error("Could not get public IP for auto-coords")
                    return

            update_progress(20)
            self.update_status("running", "Connecting to Device Portal...")
            portal_ok, portal_error = self.test_device_portal()

            if not portal_ok:
                if portal_error == "auth_failed":
                    finish_error("Device Portal: Bad username/password")
                    return
                update_progress(25)
                time.sleep(2)
                portal_ok, portal_error = self.test_device_portal()
                if not portal_ok:
                    if portal_error == "auth_failed":
                        finish_error("Device Portal: Bad username/password")
                    else:
                        finish_error("Device Portal unavailable")
                    return

            update_progress(30)
            self.update_status("running", "Activating location...")
            self.activate_location_service()

            update_progress(40)
            self.update_status("running", "Setting GPS coordinates...")
            self.initialize_location()

            update_progress(50)
            inject_success = False
            inject_error = ""

            for attempt in range(3):
                update_progress(50 + (attempt * 5))
                success, error = self.set_position(lat, lon)
                if success:
                    time.sleep(1)
                    pos = self.get_position()
                    if pos and pos.get("Latitude", 0) != 0:
                        inject_success = True
                        update_progress(65)
                        break
                inject_error = error
                if error == "auth_failed":
                    finish_error("Device Portal: Bad username/password")
                    return
                time.sleep(1)

            if not inject_success:
                finish_error(f"GPS injection failed: {inject_error}")
                return

            self.current_data["lat"] = round(lat, 6)
            self.current_data["lon"] = round(lon, 6)

            update_progress(70)
            self.update_status("running", "Verifying GPS coordinates...")
            gps_loc = self.get_location_from_coordinates(lat, lon)

            update_progress(75)
            if gps_loc:
                self.current_data["coord_country"] = gps_loc["country"]
                self.current_data["coord_state"] = gps_loc["state"]
                self.current_data["coord_city"] = gps_loc["city"]
                coord_valid, coord_error = self.is_location_allowed(gps_loc["country"], gps_loc["state"])
                self.current_data["coord_valid"] = coord_valid
                if not coord_valid:
                    if coord_error == "country":
                        errors.append(f"GPS: {gps_loc['country']} not allowed")
                    else:
                        errors.append(f"GPS: {gps_loc['state']} not allowed")
            else:
                self.current_data["coord_country"] = "Unknown"
                self.current_data["coord_state"] = "Unknown"
                self.current_data["coord_city"] = "Unknown"
                self.current_data["coord_valid"] = False

            update_progress(80)
            self.update_status("running", "Checking public IP...")
            ip = self.get_public_ip()

            update_progress(85)
            if ip:
                self.current_data["ip"] = ip
                ip_loc = self.get_location_data(ip)
                update_progress(90)
                if ip_loc:
                    self.current_data["country"] = ip_loc["country"]
                    self.current_data["state"] = ip_loc["state"]
                    self.current_data["city"] = ip_loc["city"]
                    self.current_data["isp"] = ip_loc.get("isp", "--")
                    self.current_data["hostname"] = ip_loc.get("hostname", "--")
                    self.current_data["ip_type"] = ip_loc.get("ip_type", "--")
                    self.current_data["ip_version"] = ip_loc.get("ip_version", "--")

                    ip_valid, ip_error = self.is_location_allowed(ip_loc["country"], ip_loc["state"])
                    self.current_data["ip_valid"] = ip_valid
                    if not ip_valid:
                        if ip_error == "country":
                            errors.append(f"IP: {ip_loc['country']} not allowed")
                        else:
                            errors.append(f"IP: {ip_loc['state']} not allowed")
                else:
                    self.current_data["ip_valid"] = False
                    errors.append("Could not verify IP location")
            else:
                self.current_data["ip_valid"] = False
                errors.append("Could not get public IP")

            update_progress(95)

            self.supabase.log_check(ip, ip_loc, gps_loc, "error" if errors else "success", " | ".join(errors) or "OK")

            if errors:
                self.current_data["status"] = "error"
                self.update_status("error", errors[0][:60])
                self.send_notification("Location Error", errors[0])
                agent_chat_ids = self.telegram_chat_ids.get().strip() if self.telegram_switch.get() else ""

                # ═══════════════════════════════════════════════════════════════
                # IMPROVED ERROR TYPE DETECTION
                # Analyze ALL errors to determine if it's IP, GPS, or BOTH
                # ═══════════════════════════════════════════════════════════════
                has_ip_error = False
                has_gps_error = False

                for err in errors:
                    err_lower = err.lower()
                    # Check for IP errors
                    if "ip:" in err_lower or "ip " in err_lower or "ip location" in err_lower:
                        has_ip_error = True
                    # Check for GPS errors
                    if "gps:" in err_lower or "gps " in err_lower or "coordinate" in err_lower:
                        has_gps_error = True

                # Also check current_data for invalid flags
                if self.current_data.get("ip_valid") == False:
                    has_ip_error = True
                if self.current_data.get("coord_valid") == False:
                    has_gps_error = True

                # Determine error_type
                if has_ip_error and has_gps_error:
                    error_type = "both"
                elif has_ip_error:
                    error_type = "ip"
                elif has_gps_error:
                    error_type = "gps"
                else:
                    error_type = "system"  # Unknown error, treat as system

                print(f"Error detection: has_ip_error={has_ip_error}, has_gps_error={has_gps_error}, error_type={error_type}")

                # Get agent alert filters
                agent_alert_ip = self.alert_ip_var.get() if hasattr(self, 'alert_ip_var') else True
                agent_alert_gps = self.alert_gps_var.get() if hasattr(self, 'alert_gps_var') else True
                agent_alert_on_fail = self.alert_on_fail_var.get() if hasattr(self, 'alert_on_fail_var') else True
                agent_alert_on_success = self.alert_on_success_var.get() if hasattr(self, 'alert_on_success_var') else False

                send_telegram_alert(
                    self.supabase.license_key,
                    "error",
                    self.current_data.get("ip", "unknown"),
                    f"{self.current_data.get('city', '')}, {self.current_data.get('state', '')}",
                    " | ".join(errors),  # Send ALL errors, not just first
                    agent_chat_ids,
                    error_type=error_type,
                    alert_ip=agent_alert_ip,
                    alert_gps=agent_alert_gps,
                    alert_on_fail=agent_alert_on_fail,
                    alert_on_success=agent_alert_on_success
                )
                self.stats_manager.record_check(False)
                play_sound(success=False)
            else:
                self.current_data["status"] = "success"
                self.update_status("success", "Ready to work!")
                self.send_notification("Ready to work!", f"{self.current_data['city']}, {self.current_data['state']}")
                agent_chat_ids = self.telegram_chat_ids.get().strip() if self.telegram_switch.get() else ""

                # Get agent alert filters
                agent_alert_ip = self.alert_ip_var.get() if hasattr(self, 'alert_ip_var') else True
                agent_alert_gps = self.alert_gps_var.get() if hasattr(self, 'alert_gps_var') else True
                agent_alert_on_fail = self.alert_on_fail_var.get() if hasattr(self, 'alert_on_fail_var') else True
                agent_alert_on_success = self.alert_on_success_var.get() if hasattr(self, 'alert_on_success_var') else False

                send_telegram_alert(
                    self.supabase.license_key,
                    "success",
                    self.current_data.get("ip", "unknown"),
                    f"{self.current_data.get('city', '')}, {self.current_data.get('state', '')}",
                    "Ready to work!",
                    agent_chat_ids,
                    error_type=None,
                    alert_ip=agent_alert_ip,
                    alert_gps=agent_alert_gps,
                    alert_on_fail=agent_alert_on_fail,
                    alert_on_success=agent_alert_on_success
                )
                self.stats_manager.record_check(True)
                play_sound(success=True)
                self.after(0, self.start_auto_close_countdown)

            self.update_details()

        except Exception as e:
            import traceback
            traceback.print_exc()
            finish_error(str(e)[:50])
        finally:
            self.is_running = False
            self.run_btn.configure(state="normal", text="▶  Start")

    def create_settings(self):
        scroll = ctk.CTkScrollableFrame(self.settings_frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # App Info at TOP
        info = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        info.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(info, text="App Info", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 5))

        ctk.CTkLabel(info, text=f"Agent: {self.agent_name}", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=COLORS["accent"]).pack(anchor="w", padx=16)

        if self.days_left is not None:
            days_color = COLORS["error"] if self.days_left <= 3 else COLORS["warning"] if self.days_left <= 7 else COLORS["success"]
            ctk.CTkLabel(info, text=f"License: {self.days_left} days left", font=ctk.CTkFont(size=11),
                        text_color=days_color).pack(anchor="w", padx=16)
        else:
            ctk.CTkLabel(info, text="License: Active", font=ctk.CTkFont(size=11),
                        text_color=COLORS["success"]).pack(anchor="w", padx=16)

        ctk.CTkLabel(info, text=f"Version: {APP_VERSION}", font=ctk.CTkFont(size=10),
                    text_color=COLORS["text_secondary"]).pack(anchor="w", padx=16)
        if hasattr(self, 'supabase') and self.supabase.license_key:
            ctk.CTkLabel(info, text=f"License Key: {self.supabase.license_key}", font=ctk.CTkFont(size=10),
                        text_color=COLORS["text_secondary"]).pack(anchor="w", padx=16)
        if hasattr(self, 'supabase') and self.supabase.hwid:
            ctk.CTkLabel(info, text=f"HWID: {self.supabase.hwid[:20]}...", font=ctk.CTkFont(size=10),
                        text_color=COLORS["text_secondary"]).pack(anchor="w", padx=16, pady=(0, 12))

        # Auto-Check Section
        auto_sec = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        auto_sec.pack(fill="x", pady=(0, 10))

        auto_header = ctk.CTkFrame(auto_sec, fg_color="transparent")
        auto_header.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkLabel(auto_header, text="Auto-Check", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        self.auto_switch = ctk.CTkSwitch(auto_header, text="", width=50, command=self.toggle_auto_check,
                                          progress_color=COLORS["success"], button_color=COLORS["text"])
        self.auto_switch.pack(side="right")
        self.auto_label = ctk.CTkLabel(auto_header, text="OFF", font=ctk.CTkFont(size=11, weight="bold"),
                                        text_color=COLORS["text_secondary"])
        self.auto_label.pack(side="right", padx=(0, 10))

        auto_config = ctk.CTkFrame(auto_sec, fg_color="transparent")
        auto_config.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(auto_config, text="Interval:", width=60, anchor="w",
                    text_color=COLORS["text_secondary"], font=ctk.CTkFont(size=11)).pack(side="left")
        self.interval_entry = ctk.CTkEntry(auto_config, width=50, height=28, font=ctk.CTkFont(size=11))
        self.interval_entry.pack(side="left")
        self.interval_entry.insert(0, "5")
        ctk.CTkLabel(auto_config, text="min", text_color=COLORS["text_secondary"],
                    font=ctk.CTkFont(size=11)).pack(side="left", padx=(5, 0))

        self.countdown_label = ctk.CTkLabel(auto_sec, text="", font=ctk.CTkFont(size=10),
                                            text_color=COLORS["text_secondary"])
        self.countdown_label.pack(anchor="w", padx=16, pady=(0, 12))

        cred = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        cred.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(cred, text="Device Portal", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 8))

        uf = ctk.CTkFrame(cred, fg_color="transparent")
        uf.pack(fill="x", padx=16, pady=2)
        ctk.CTkLabel(uf, text="Username", width=70, anchor="w", text_color=COLORS["text_secondary"],
                    font=ctk.CTkFont(size=11)).pack(side="left")
        self.username_entry = ctk.CTkEntry(uf, height=28, font=ctk.CTkFont(size=11))
        self.username_entry.pack(side="left", fill="x", expand=True)

        pf = ctk.CTkFrame(cred, fg_color="transparent")
        pf.pack(fill="x", padx=16, pady=(2, 12))
        ctk.CTkLabel(pf, text="Password", width=70, anchor="w", text_color=COLORS["text_secondary"],
                    font=ctk.CTkFont(size=11)).pack(side="left")
        self.password_entry = ctk.CTkEntry(pf, show="*", height=28, font=ctk.CTkFont(size=11))
        self.password_entry.pack(side="left", fill="x", expand=True)

        gps = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        gps.pack(fill="x", pady=(0, 10))

        gps_header = ctk.CTkFrame(gps, fg_color="transparent")
        gps_header.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkLabel(gps_header, text="GPS Coordinates", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        self.gps_mode_var = ctk.StringVar(value="custom")
        gps_mode = ctk.CTkFrame(gps, fg_color="transparent")
        gps_mode.pack(fill="x", padx=16, pady=(0, 8))

        self.gps_auto_radio = ctk.CTkRadioButton(gps_mode, text="Use IP coords", variable=self.gps_mode_var,
                                                  value="auto", font=ctk.CTkFont(size=11),
                                                  command=self.toggle_gps_mode)
        self.gps_auto_radio.pack(side="left", padx=(0, 15))
        self.gps_custom_radio = ctk.CTkRadioButton(gps_mode, text="Custom", variable=self.gps_mode_var,
                                                    value="custom", font=ctk.CTkFont(size=11),
                                                    command=self.toggle_gps_mode)
        self.gps_custom_radio.pack(side="left")

        lf = ctk.CTkFrame(gps, fg_color="transparent")
        lf.pack(fill="x", padx=16, pady=2)
        ctk.CTkLabel(lf, text="Latitude", width=70, anchor="w", text_color=COLORS["text_secondary"],
                    font=ctk.CTkFont(size=11)).pack(side="left")
        self.lat_entry = ctk.CTkEntry(lf, height=28, font=ctk.CTkFont(size=11))
        self.lat_entry.pack(side="left", fill="x", expand=True)

        lof = ctk.CTkFrame(gps, fg_color="transparent")
        lof.pack(fill="x", padx=16, pady=(2, 12))
        ctk.CTkLabel(lof, text="Longitude", width=70, anchor="w", text_color=COLORS["text_secondary"],
                    font=ctk.CTkFont(size=11)).pack(side="left")
        self.lon_entry = ctk.CTkEntry(lof, height=28, font=ctk.CTkFont(size=11))
        self.lon_entry.pack(side="left", fill="x", expand=True)

        co = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        co.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(co, text="Allowed Countries", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 4))
        self.countries_entry = ctk.CTkTextbox(co, height=40, corner_radius=6, fg_color=COLORS["bg_dark"], font=ctk.CTkFont(size=11))
        self.countries_entry.pack(fill="x", padx=16, pady=(0, 12))

        st = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        st.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(st, text="Allowed States", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 4))
        self.states_entry = ctk.CTkTextbox(st, height=40, corner_radius=6, fg_color=COLORS["bg_dark"], font=ctk.CTkFont(size=11))
        self.states_entry.pack(fill="x", padx=16, pady=(0, 12))

        tg = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        tg.pack(fill="x", pady=(0, 10))

        tg_header = ctk.CTkFrame(tg, fg_color="transparent")
        tg_header.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkLabel(tg_header, text="Telegram Notifications", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        self.telegram_switch = ctk.CTkSwitch(tg_header, text="", width=50,
                                              progress_color=COLORS["success"], button_color=COLORS["text"],
                                              command=self.on_telegram_switch_changed)
        self.telegram_switch.pack(side="right")

        # ═══════════════════════════════════════════
        # CONNECTED TELEGRAMS LIST
        # ═══════════════════════════════════════════
        self.tg_list_frame = ctk.CTkFrame(tg, fg_color="transparent")
        self.tg_list_frame.pack(fill="x", padx=16, pady=(0, 8))

        # Connect button
        self.tg_connect_btn = ctk.CTkButton(
            self.tg_list_frame,
            text="+ Connect Telegram",
            height=32,
            fg_color=COLORS["accent_secondary"],
            hover_color="#6d28d9",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.show_telegram_connect_dialog
        )
        self.tg_connect_btn.pack(fill="x", pady=(0, 8))

        # Connected telegrams will be shown here
        self.tg_connected_frame = ctk.CTkFrame(self.tg_list_frame, fg_color="transparent")
        self.tg_connected_frame.pack(fill="x")

        # Hidden entry for chat_ids (for compatibility)
        self.telegram_chat_ids = ctk.CTkEntry(tg, height=1, font=ctk.CTkFont(size=1))
        # Don't pack - keep hidden but accessible

        # ═══════════════════════════════════════════
        # ALERT FILTERS
        # ═══════════════════════════════════════════

        # Separator line
        ctk.CTkFrame(tg, fg_color=COLORS["border"], height=1).pack(fill="x", padx=16, pady=(12, 10))

        # ── SECTION 1: When to notify ──
        notify_box = ctk.CTkFrame(tg, fg_color=COLORS["bg_dark"], corner_radius=8)
        notify_box.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(notify_box, text="WHEN TO NOTIFY:",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color=COLORS["warning"]).pack(anchor="w", padx=12, pady=(10, 6))

        notify_row = ctk.CTkFrame(notify_box, fg_color="transparent")
        notify_row.pack(fill="x", padx=12, pady=(0, 10))

        self.alert_on_fail_var = ctk.BooleanVar(value=True)
        fail_check = ctk.CTkCheckBox(notify_row, text="When check FAILS",
                                     variable=self.alert_on_fail_var,
                                     font=ctk.CTkFont(size=11),
                                     checkbox_width=20, checkbox_height=20,
                                     fg_color="#ef4444", hover_color="#dc2626",
                                     text_color="#ef4444")
        fail_check.pack(side="left", padx=(0, 25))

        self.alert_on_success_var = ctk.BooleanVar(value=False)
        success_check = ctk.CTkCheckBox(notify_row, text="When check SUCCESS",
                                        variable=self.alert_on_success_var,
                                        font=ctk.CTkFont(size=11),
                                        checkbox_width=20, checkbox_height=20,
                                        fg_color="#10b981", hover_color="#059669",
                                        text_color="#10b981")
        success_check.pack(side="left")

        # ── SECTION 2: Error types ──
        error_box = ctk.CTkFrame(tg, fg_color=COLORS["bg_dark"], corner_radius=8)
        error_box.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(error_box, text="ALERT FOR THESE ISSUES:",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color=COLORS["warning"]).pack(anchor="w", padx=12, pady=(10, 6))

        error_row = ctk.CTkFrame(error_box, fg_color="transparent")
        error_row.pack(fill="x", padx=12, pady=(0, 10))

        self.alert_ip_var = ctk.BooleanVar(value=True)
        ip_check = ctk.CTkCheckBox(error_row, text="IP Location issue",
                                   variable=self.alert_ip_var,
                                   font=ctk.CTkFont(size=11),
                                   checkbox_width=20, checkbox_height=20,
                                   fg_color="#3b82f6", hover_color="#2563eb")
        ip_check.pack(side="left", padx=(0, 25))

        self.alert_gps_var = ctk.BooleanVar(value=True)
        gps_check = ctk.CTkCheckBox(error_row, text="GPS Coords issue",
                                    variable=self.alert_gps_var,
                                    font=ctk.CTkFont(size=11),
                                    checkbox_width=20, checkbox_height=20,
                                    fg_color="#10b981", hover_color="#059669")
        gps_check.pack(side="left")

        # Load connected telegrams
        self.refresh_connected_telegrams()

        # Save Button
        ctk.CTkButton(scroll, text="Save", width=120, height=36, corner_radius=10,
                     fg_color=COLORS["accent"], hover_color=COLORS["accent_gradient_end"], text_color="#000",
                     font=ctk.CTkFont(size=12, weight="bold"), command=self.save_config).pack(pady=10)

    def on_telegram_switch_changed(self):
        """Called when telegram switch is toggled"""
        if self.telegram_switch.get():
            # If turning ON and no telegrams connected, show connect dialog
            chat_ids = self.telegram_chat_ids.get().strip()
            if not chat_ids:
                self.show_telegram_connect_dialog()

    def refresh_connected_telegrams(self):
        """Refresh the list of connected Telegram accounts"""
        # Clear current list
        for widget in self.tg_connected_frame.winfo_children():
            widget.destroy()

        # Get HWID
        hwid = self.supabase.hwid if hasattr(self, 'supabase') and self.supabase else None
        if not hwid:
            return

        # Fetch connected telegrams
        def fetch():
            telegrams = get_connected_telegrams(hwid)
            self.after(0, lambda: self.display_connected_telegrams(telegrams))

        threading.Thread(target=fetch, daemon=True).start()

    def display_connected_telegrams(self, telegrams):
        """Display the list of connected Telegram accounts"""
        # Clear current list
        for widget in self.tg_connected_frame.winfo_children():
            widget.destroy()

        # Update chat_ids field for compatibility
        chat_ids = ",".join([t.get("chat_id", "") for t in telegrams])
        self.telegram_chat_ids.delete(0, "end")
        self.telegram_chat_ids.insert(0, chat_ids)

        if not telegrams:
            no_tg = ctk.CTkLabel(
                self.tg_connected_frame,
                text="No Telegram accounts connected",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_secondary"]
            )
            no_tg.pack(pady=5)
            return

        for tg in telegrams:
            row = ctk.CTkFrame(self.tg_connected_frame, fg_color=COLORS["bg_dark"], corner_radius=6)
            row.pack(fill="x", pady=2)

            # Icon
            ctk.CTkLabel(row, text="📱", font=ctk.CTkFont(size=14)).pack(side="left", padx=(8, 4))

            # Username or name
            name = tg.get("username")
            if name:
                name = f"@{name}"
            else:
                name = tg.get("first_name", "Telegram User")

            ctk.CTkLabel(
                row, text=name,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLORS["text"]
            ).pack(side="left", padx=4)

            # Chat ID
            ctk.CTkLabel(
                row, text=f"({tg.get('chat_id', '')})",
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_secondary"]
            ).pack(side="left", padx=4)

            # Remove button
            chat_id = tg.get("chat_id", "")
            remove_btn = ctk.CTkButton(
                row, text="✕", width=24, height=24,
                fg_color="transparent", hover_color="#ef4444",
                text_color="#ef4444", font=ctk.CTkFont(size=12),
                command=lambda cid=chat_id: self.remove_telegram(cid)
            )
            remove_btn.pack(side="right", padx=4, pady=4)

    def remove_telegram(self, chat_id):
        """Remove a Telegram connection"""
        hwid = self.supabase.hwid if hasattr(self, 'supabase') and self.supabase else None
        if not hwid:
            return

        def do_remove():
            success = remove_telegram_connection(hwid, chat_id)
            if success:
                self.after(0, self.refresh_connected_telegrams)

        threading.Thread(target=do_remove, daemon=True).start()

    def show_telegram_connect_dialog(self):
        """Show dialog with QR code to connect Telegram"""
        hwid = self.supabase.hwid if hasattr(self, 'supabase') and self.supabase else None
        if not hwid:
            messagebox.showerror("Error", "Please activate your license first")
            return

        # Create dialog window
        dialog = ctk.CTkToplevel(self)
        dialog.title("Connect Telegram")
        dialog.geometry("400x500")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        # Center dialog
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 400) // 2
        y = self.winfo_y() + (self.winfo_height() - 500) // 2
        dialog.geometry(f"+{x}+{y}")

        # Configure dialog colors
        dialog.configure(fg_color=COLORS["bg_dark"])

        # Header
        ctk.CTkLabel(
            dialog, text="📱 Connect Telegram",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(20, 10))

        # Status label
        status_label = ctk.CTkLabel(
            dialog, text="Generating link...",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        )
        status_label.pack(pady=5)

        # QR frame
        qr_frame = ctk.CTkFrame(dialog, fg_color=COLORS["bg_card"], corner_radius=12)
        qr_frame.pack(padx=20, pady=10, fill="x")

        qr_label = ctk.CTkLabel(qr_frame, text="")
        qr_label.pack(pady=15)

        # Code display (for manual entry)
        code_label = ctk.CTkLabel(
            qr_frame, text="",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_secondary"]
        )
        code_label.pack(pady=(0, 10))

        # Buttons frame
        btns_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btns_frame.pack(fill="x", padx=20, pady=5)

        # Open Telegram button (Desktop/Mobile)
        link_btn = ctk.CTkButton(
            btns_frame, text="🖥️  Open Telegram Desktop",
            fg_color=COLORS["accent_secondary"],
            hover_color="#6d28d9",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            state="disabled"
        )
        link_btn.pack(fill="x", pady=2)

        # Copy link button
        copy_btn = ctk.CTkButton(
            btns_frame, text="📋  Copy Link",
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
            font=ctk.CTkFont(size=11),
            height=32,
            state="disabled"
        )
        copy_btn.pack(fill="x", pady=2)

        # Instructions
        instructions = """📱 Mobile: Scan QR with your phone camera
🖥️ Desktop: Click "Open Telegram Desktop"
📋 Or copy the link and paste in Telegram

After opening, press START in the bot chat."""

        ctk.CTkLabel(
            dialog, text=instructions,
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_secondary"],
            justify="left"
        ).pack(padx=20, pady=8)

        # Cancel button
        ctk.CTkButton(
            dialog, text="Cancel",
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["bg_card"],
            command=dialog.destroy
        ).pack(pady=10)

        # Store polling state
        dialog.polling = True
        dialog.link_data = None

        def generate_and_show():
            link_data = generate_telegram_link_code(hwid)
            if not link_data:
                self.after(0, lambda: status_label.configure(text="Error generating link. Try again.", text_color="#ef4444"))
                return

            dialog.link_data = link_data

            # Generate QR code
            qr_image = None
            if QR_AVAILABLE:
                try:
                    qr = qrcode.QRCode(version=1, box_size=6, border=2)
                    qr.add_data(link_data["link"])
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    img = img.resize((180, 180))
                    qr_image = ImageTk.PhotoImage(img)
                except Exception as e:
                    print(f"QR generation error: {e}")

            def update_ui():
                status_label.configure(text="Waiting for connection...", text_color=COLORS["accent"])

                if qr_image:
                    qr_label.configure(image=qr_image)
                    qr_label.image = qr_image  # Keep reference
                else:
                    qr_label.configure(text=f"📱 Scan QR or use buttons below")

                # Show code for reference
                code_label.configure(text=f"Code: {link_data['code']}")

                # Open Telegram link
                def open_link():
                    import webbrowser
                    webbrowser.open(link_data["link"])

                link_btn.configure(state="normal", command=open_link)

                # Copy link to clipboard
                def copy_link():
                    try:
                        dialog.clipboard_clear()
                        dialog.clipboard_append(link_data["link"])
                        copy_btn.configure(text="✓ Copied!")
                        self.after(2000, lambda: copy_btn.configure(text="📋  Copy Link"))
                    except:
                        pass

                copy_btn.configure(state="normal", command=copy_link)

            self.after(0, update_ui)

            # Start polling
            poll_status()

        def poll_status():
            if not dialog.winfo_exists() or not dialog.polling:
                return

            if not dialog.link_data:
                self.after(2000, poll_status)
                return

            status, chat_id = check_telegram_link_status(dialog.link_data["link_id"])

            if status == "connected":
                dialog.polling = False
                self.after(0, lambda: on_connected(chat_id))
            elif status == "expired":
                dialog.polling = False
                self.after(0, lambda: status_label.configure(text="Code expired. Close and try again.", text_color="#ef4444"))
            else:
                # Still pending, poll again
                self.after(3000, poll_status)

        def on_connected(chat_id):
            status_label.configure(text="✓ Connected successfully!", text_color=COLORS["success"])
            link_btn.configure(text="Done!", state="disabled")

            # Refresh list and close after delay
            self.refresh_connected_telegrams()
            self.telegram_switch.select()  # Turn on switch

            self.after(1500, dialog.destroy)

        # Handle dialog close
        def on_close():
            dialog.polling = False
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_close)

        # Start generation in background
        threading.Thread(target=generate_and_show, daemon=True).start()

    def toggle_gps_mode(self):
        if self.gps_mode_var.get() == "auto":
            self.lat_entry.configure(state="disabled")
            self.lon_entry.configure(state="disabled")
        else:
            self.lat_entry.configure(state="normal")
            self.lon_entry.configure(state="normal")


if __name__ == "__main__":
    # Save current exe path for reliable updates (even if renamed)
    save_current_exe_path()

    clean_old_versions()
    ensure_in_startup()
    app = GeoApp()
    app.mainloop()
