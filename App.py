###############################################
# Geo V8.36 - Simple Dashboard Application
# Just a GUI app - no background services
# Auto-runs check ONLY when launched from Startup folder
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

try:
    from winotify import Notification, audio
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False

SELENIUM_AVAILABLE = False
try:
    from selenium import webdriver
    SELENIUM_AVAILABLE = True
except ImportError:
    pass

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Supabase Config
SUPABASE_URL = "https://krejyqdlujpemrpeqozc.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtyZWp5cWRsdWpwZW1ycGVxb3pjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzAzMjA2ODgsImV4cCI6MjA4NTg5NjY4OH0.uEtY3u8Y2dbM5o_B0xHku7RU91u0iAuY7EJBCyOAxQY"

DEFAULT_ALLOWED_STATES = ["Florida", "Texas"]
DEFAULT_ALLOWED_COUNTRIES = ["United States", "USA", "US"]

COLORS = {
    "bg_dark": "#0f0f0f",
    "bg_card": "#1a1a1a",
    "bg_card_hover": "#252525",
    "accent": "#00d4aa",
    "accent_dark": "#00a080",
    "success": "#00c853",
    "error": "#ff5252",
    "warning": "#ffab00",
    "text": "#ffffff",
    "text_secondary": "#888888",
    "border": "#333333"
}

SCRIPT_DIR = Path(__file__).parent.resolve()
LOCAL_CONFIG_PATH = SCRIPT_DIR / "config_local.json"


def get_hardware_id():
    """Generate HWID from physical hardware (doesn't change on Windows reset)"""
    import subprocess

    def run_wmic(cmd):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=10)
            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            return lines[1] if len(lines) > 1 else ""
        except:
            return ""

    try:
        bios_serial = run_wmic("wmic bios get serialnumber")
        baseboard_serial = run_wmic("wmic baseboard get serialnumber")
        system_uuid = run_wmic("wmic csproduct get uuid")
        combined = f"{bios_serial}-{baseboard_serial}-{system_uuid}"
        if combined == "--":
            machine_id = str(uuid.getnode())
            processor = platform.processor()
            combined = f"{machine_id}-{processor}"
        return hashlib.sha256(combined.encode()).hexdigest()[:32].upper()
    except:
        machine_id = str(uuid.getnode())
        processor = platform.processor()
        combined = f"{machine_id}-{processor}"
        return hashlib.sha256(combined.encode()).hexdigest()[:32].upper()


class SupabaseManager:
    def __init__(self):
        self.hwid = get_hardware_id()
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

    def _calc_days(self, expires_at):
        if not expires_at:
            return None
        try:
            exp = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            return max(0, (exp - datetime.now(exp.tzinfo)).days)
        except:
            return None

    def check_license(self):
        try:
            result = self._get("licenses", {"hwid": f"eq.{self.hwid}", "select": "*"})
            if result and len(result) > 0:
                lic = result[0]
                if not lic.get("is_active", False):
                    return False, "Expired"
                expires_at = lic.get("expires_at")
                if expires_at:
                    exp = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    if exp < datetime.now(exp.tzinfo):
                        return False, "Expired"
                    self.days_left = self._calc_days(expires_at)
                else:
                    self.days_left = None
                self.is_licensed = True
                self.license_key = lic.get("license_key")
                self.agent_name = lic.get("customer_name") or "Agent"
                return True, self.agent_name
            return False, "Missing"
        except:
            return False, "Connection error"

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
            if not self._patch("licenses", {"hwid": self.hwid}, {"license_key": f"eq.{license_key}"}):
                return False, "Registration failed"
            self.is_licensed = True
            self.license_key = license_key
            self.agent_name = lic.get("customer_name") or "Agent"
            self.days_left = self._calc_days(expires_at)
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


class LicenseDialog(ctk.CTkToplevel):
    def __init__(self, parent, supabase_manager, error_msg=None):
        super().__init__(parent)
        self.title("License")
        self.geometry("400x250")
        self.configure(fg_color=COLORS["bg_dark"])
        self.resizable(False, False)
        self.parent = parent
        self.supabase = supabase_manager
        self.activated = False
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 400) // 2
        y = (self.winfo_screenheight() - 250) // 2
        self.geometry(f"400x250+{x}+{y}")
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        if error_msg == "Expired":
            ctk.CTkLabel(self, text="License Expired", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["error"]).pack(pady=(20, 5))
            ctk.CTkLabel(self, text="Enter a new license key", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(pady=(0, 15))
        elif error_msg == "Missing":
            ctk.CTkLabel(self, text="Enter License Key", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["text"]).pack(pady=(30, 20))
        else:
            ctk.CTkLabel(self, text="Enter License Key", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["text"]).pack(pady=(30, 20))

        self.license_entry = ctk.CTkEntry(self, width=300, height=45, justify="center",
                                          placeholder_text="XXXX-XXXX-XXXX-XXXX",
                                          font=ctk.CTkFont(size=16))
        self.license_entry.pack(pady=(0, 10))
        self.license_entry.bind("<Return>", lambda e: self.activate())

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11), text_color=COLORS["error"])
        self.status_label.pack(pady=(0, 10))

        self.activate_btn = ctk.CTkButton(self, text="Activate", width=150, height=40,
                                          fg_color=COLORS["accent"], hover_color=COLORS["accent_dark"],
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


class GeoApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Geo V8.36")
        self.geometry("900x700")
        self.minsize(800, 600)
        self.configure(fg_color=COLORS["bg_dark"])

        # Set window icon
        icon_path = SCRIPT_DIR / "geo.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))
        self.supabase = SupabaseManager()
        self.auto_check_job = None
        self.countdown_job = None
        self.after(100, self.check_license)

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
        self.port = 50080
        self.base_uri = f"http://localhost:{self.port}"
        self.headers = {}
        self.is_running = False
        self.browser_driver = None
        self.current_data = {"ip": "--", "country": "--", "state": "--", "city": "--", "status": "unknown",
                            "lat": "--", "lon": "--", "coord_country": "--", "coord_state": "--", "coord_city": "--"}
        self.allowed_countries = DEFAULT_ALLOWED_COUNTRIES.copy()
        self.allowed_states = DEFAULT_ALLOWED_STATES.copy()
        self.next_check_time = None
        self.auto_interval = 5
        self.create_widgets()
        self.after(200, self.load_config)
        # Auto-run check on startup (after config loads)
        self.after(1000, self.auto_run_on_startup)

    def is_running_from_startup(self):
        """Check if app is running from Windows Startup folder"""
        try:
            # Get the path where the app is running from
            if getattr(sys, 'frozen', False):
                # Running as compiled exe (PyInstaller)
                app_path = sys.executable
            else:
                # Running as script
                app_path = os.path.abspath(__file__)

            app_path_lower = app_path.lower()

            # Check if path contains "startup" folder
            if "startup" in app_path_lower:
                return True

            # Also check the specific Windows Startup path
            startup_path = os.path.join(
                os.environ.get("APPDATA", ""),
                "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
            ).lower()

            if startup_path in app_path_lower:
                return True

            return False
        except:
            return False

    def auto_run_on_startup(self):
        """Automatically run check ONLY when launched from Startup folder"""
        # Only auto-run if launched from Startup folder
        if not self.is_running_from_startup():
            return

        # Only run if we have all required settings
        try:
            u = self.username_entry.get().strip()
            p = self.password_entry.get().strip()
            lat_s = self.lat_entry.get().strip()
            lon_s = self.lon_entry.get().strip()
            if all([u, p, lat_s, lon_s]):
                self.run_check()
        except:
            pass

    def create_widgets(self):
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=20, pady=20)
        self.create_header()
        self.content_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, pady=(20, 0))
        self.dashboard_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.settings_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.create_dashboard()
        self.create_settings()
        self.show_dashboard()

    def create_header(self):
        hf = ctk.CTkFrame(self.main_container, fg_color="transparent")
        hf.pack(fill="x")
        left = ctk.CTkFrame(hf, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="GEO V8.36", font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=COLORS["accent"]).pack(side="left")

        if self.days_left is not None:
            days_color = COLORS["error"] if self.days_left <= 3 else COLORS["warning"] if self.days_left <= 7 else COLORS["success"]
            ctk.CTkLabel(left, text=f"  |  {self.agent_name}", font=ctk.CTkFont(size=14),
                        text_color=COLORS["success"]).pack(side="left", padx=(10, 0))
            ctk.CTkLabel(left, text=f"  ({self.days_left} days)", font=ctk.CTkFont(size=14),
                        text_color=days_color).pack(side="left")
        else:
            ctk.CTkLabel(left, text=f"  |  {self.agent_name}", font=ctk.CTkFont(size=14),
                        text_color=COLORS["success"]).pack(side="left", padx=(10, 0))

        right = ctk.CTkFrame(hf, fg_color="transparent")
        right.pack(side="right")
        self.dashboard_btn = ctk.CTkButton(right, text="Dashboard", width=100, height=35, corner_radius=8,
                                           fg_color=COLORS["accent"], hover_color=COLORS["accent_dark"],
                                           text_color="#000", font=ctk.CTkFont(weight="bold"),
                                           command=self.show_dashboard)
        self.dashboard_btn.pack(side="left", padx=5)
        self.settings_btn = ctk.CTkButton(right, text="Settings", width=100, height=35, corner_radius=8,
                                          fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
                                          border_width=1, border_color=COLORS["border"],
                                          command=self.show_settings)
        self.settings_btn.pack(side="left", padx=5)

    def create_dashboard(self):
        # Status bar
        sf = ctk.CTkFrame(self.dashboard_frame, fg_color=COLORS["bg_card"], corner_radius=16, height=70)
        sf.pack(fill="x", pady=(0, 15))
        sf.pack_propagate(False)
        si = ctk.CTkFrame(sf, fg_color="transparent")
        si.place(relx=0.5, rely=0.5, anchor="center")
        self.status_dot = ctk.CTkLabel(si, text="●", font=ctk.CTkFont(size=28), text_color=COLORS["text_secondary"])
        self.status_dot.pack(side="left", padx=(0, 12))
        self.status_text = ctk.CTkLabel(si, text="Ready to check", font=ctk.CTkFont(size=18, weight="bold"),
                                        text_color=COLORS["text"])
        self.status_text.pack(side="left")

        # IP Section
        ip_sec = ctk.CTkFrame(self.dashboard_frame, fg_color=COLORS["bg_card"], corner_radius=12)
        ip_sec.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(ip_sec, text="  IP LOCATION", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLORS["accent"]).pack(anchor="w", pady=(10, 6))
        ip_grid = ctk.CTkFrame(ip_sec, fg_color="transparent")
        ip_grid.pack(fill="x", padx=10, pady=(0, 10))
        for i in range(4):
            ip_grid.grid_columnconfigure(i, weight=1)
        self.ip_card = StatusCard(ip_grid, "PUBLIC IP")
        self.ip_card.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
        self.country_card = StatusCard(ip_grid, "COUNTRY")
        self.country_card.grid(row=0, column=1, padx=4, pady=4, sticky="nsew")
        self.state_card = StatusCard(ip_grid, "STATE")
        self.state_card.grid(row=0, column=2, padx=4, pady=4, sticky="nsew")
        self.city_card = StatusCard(ip_grid, "CITY")
        self.city_card.grid(row=0, column=3, padx=4, pady=4, sticky="nsew")

        # GPS Section
        gps_sec = ctk.CTkFrame(self.dashboard_frame, fg_color=COLORS["bg_card"], corner_radius=12)
        gps_sec.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(gps_sec, text="  GPS COORDINATES", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLORS["accent"]).pack(anchor="w", pady=(10, 6))
        gps_grid = ctk.CTkFrame(gps_sec, fg_color="transparent")
        gps_grid.pack(fill="x", padx=10, pady=(0, 10))
        for i in range(5):
            gps_grid.grid_columnconfigure(i, weight=1)
        self.lat_card = StatusCard(gps_grid, "LATITUDE")
        self.lat_card.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
        self.lon_card = StatusCard(gps_grid, "LONGITUDE")
        self.lon_card.grid(row=0, column=1, padx=4, pady=4, sticky="nsew")
        self.coord_country_card = StatusCard(gps_grid, "COUNTRY")
        self.coord_country_card.grid(row=0, column=2, padx=4, pady=4, sticky="nsew")
        self.coord_state_card = StatusCard(gps_grid, "STATE")
        self.coord_state_card.grid(row=0, column=3, padx=4, pady=4, sticky="nsew")
        self.coord_city_card = StatusCard(gps_grid, "CITY")
        self.coord_city_card.grid(row=0, column=4, padx=4, pady=4, sticky="nsew")

        # Controls
        ctrl = ctk.CTkFrame(self.dashboard_frame, fg_color="transparent")
        ctrl.pack(fill="x", pady=(10, 0))
        self.run_btn = ctk.CTkButton(ctrl, text="▶  Run Check", width=150, height=45, corner_radius=12,
                                      fg_color=COLORS["accent"], hover_color=COLORS["accent_dark"],
                                      text_color="#000", font=ctk.CTkFont(size=14, weight="bold"),
                                      command=self.run_check)
        self.run_btn.pack(side="left")

        # Auto-check section
        auto_sec = ctk.CTkFrame(self.dashboard_frame, fg_color=COLORS["bg_card"], corner_radius=12)
        auto_sec.pack(fill="x", pady=(15, 0))

        auto_row = ctk.CTkFrame(auto_sec, fg_color="transparent")
        auto_row.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(auto_row, text="AUTO-CHECK", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLORS["accent"]).pack(side="left")

        self.auto_switch = ctk.CTkSwitch(auto_row, text="", width=50, command=self.toggle_auto_check,
                                          progress_color=COLORS["success"], button_color=COLORS["text"])
        self.auto_switch.pack(side="right")

        self.auto_label = ctk.CTkLabel(auto_row, text="OFF", font=ctk.CTkFont(size=12, weight="bold"),
                                        text_color=COLORS["text_secondary"])
        self.auto_label.pack(side="right", padx=(0, 10))

        self.countdown_label = ctk.CTkLabel(auto_sec, text="", font=ctk.CTkFont(size=11),
                                            text_color=COLORS["text_secondary"])
        self.countdown_label.pack(anchor="w", padx=12, pady=(0, 10))

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
        self.dashboard_frame.pack(fill="both", expand=True)
        self.dashboard_btn.configure(fg_color=COLORS["accent"], text_color="#000", border_width=0)
        self.settings_btn.configure(fg_color=COLORS["bg_card"], text_color=COLORS["text"], border_width=1)

    def show_settings(self):
        self.dashboard_frame.pack_forget()
        self.settings_frame.pack(fill="both", expand=True)
        self.settings_btn.configure(fg_color=COLORS["accent"], text_color="#000", border_width=0)
        self.dashboard_btn.configure(fg_color=COLORS["bg_card"], text_color=COLORS["text"], border_width=1)

    def update_status(self, status, msg):
        colors = {"ready": COLORS["text_secondary"], "running": COLORS["warning"],
                  "success": COLORS["success"], "error": COLORS["error"]}
        self.status_dot.configure(text_color=colors.get(status, COLORS["text_secondary"]))
        self.status_text.configure(text=msg)

    def update_cards(self):
        # IP Location cards - green if IP allowed, red if IP not allowed
        ip_valid = self.current_data.get("ip_valid")
        if ip_valid is True:
            ip_color = COLORS["success"]
        elif ip_valid is False:
            ip_color = COLORS["error"]
        else:
            ip_color = COLORS["text"]

        self.ip_card.set_value(self.current_data["ip"], ip_color)
        self.country_card.set_value(self.current_data["country"], ip_color)
        self.state_card.set_value(self.current_data["state"], ip_color)
        self.city_card.set_value(self.current_data["city"], ip_color)

        # GPS cards - green if GPS allowed, red if GPS not allowed
        coord_valid = self.current_data.get("coord_valid")
        if coord_valid is True:
            gps_color = COLORS["success"]
        elif coord_valid is False:
            gps_color = COLORS["error"]
        else:
            gps_color = COLORS["text"]

        self.lat_card.set_value(str(self.current_data["lat"]), gps_color)
        self.lon_card.set_value(str(self.current_data["lon"]), gps_color)
        self.coord_country_card.set_value(self.current_data.get("coord_country", "--"), gps_color)
        self.coord_state_card.set_value(self.current_data.get("coord_state", "--"), gps_color)
        self.coord_city_card.set_value(self.current_data.get("coord_city", "--"), gps_color)

    def send_notification(self, title, msg):
        if NOTIFICATIONS_AVAILABLE:
            try:
                Notification(app_id="Location Service", title=title, msg=msg, duration="short").show()
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
                "service_interval": self.interval_entry.get().strip() or "5"
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
        """Test Device Portal connection AND authentication"""
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
        """Activate location service via browser"""
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
        """Wake up location endpoints - CRITICAL for GPS injection to work"""
        for ep in [f"{self.base_uri}/ext/location",
                   f"{self.base_uri}/ext/location/override",
                   f"{self.base_uri}/ext/location/position"]:
            try:
                requests.get(ep, headers=self.headers, timeout=5)
            except:
                pass
        time.sleep(1)

    def set_position(self, lat, lon):
        """Set GPS position and return success status with error details"""
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
        """Get current GPS position from device"""
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
            d = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,region,regionName,city", timeout=10).json()
            if d.get("status") == "success":
                return {"country": d.get("country", "Unknown"), "city": d.get("city", "Unknown"), "state": d.get("regionName", "Unknown")}
        except:
            pass
        return None

    def get_location_from_coordinates(self, lat, lon):
        """Get location from coordinates - tries multiple APIs"""
        # Try Nominatim first
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

        # Try BigDataCloud as backup
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

        # Try geocode.xyz as third option
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
        """Check if location is allowed - with full country and state aliases"""
        if not country:
            return False, "country"

        # Country aliases
        country_aliases = {
            "usa": ["united states", "us", "usa", "america", "united states of america", "u.s.", "u.s.a."],
            "uk": ["united kingdom", "uk", "great britain", "england", "gb", "britain"],
            "uae": ["united arab emirates", "uae", "emirates"],
        }

        # US State aliases (abbreviation -> full name)
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

        # Reverse state aliases (full name -> abbreviation)
        state_aliases_reverse = {v: k for k, v in state_aliases.items()}

        def normalize_country(c):
            """Normalize country to standard form"""
            c_lower = c.lower().strip()
            # Check if it matches any alias group
            for key, aliases in country_aliases.items():
                if c_lower in aliases or any(c_lower in alias or alias in c_lower for alias in aliases):
                    return key
            return c_lower

        def normalize_state(s):
            """Normalize state to full name"""
            if not s:
                return ""
            s_lower = s.lower().strip()
            # If it's an abbreviation, convert to full name
            if s_lower in state_aliases:
                return state_aliases[s_lower]
            # If it's already a full name, return as is
            if s_lower in state_aliases_reverse:
                return s_lower
            return s_lower

        def matches_country(allowed, actual):
            """Check if allowed country matches actual country"""
            allowed_norm = normalize_country(allowed)
            actual_norm = normalize_country(actual)

            # Direct match after normalization
            if allowed_norm == actual_norm:
                return True

            # Check if one contains the other
            if allowed_norm in actual_norm or actual_norm in allowed_norm:
                return True

            return False

        def matches_state(allowed, actual):
            """Check if allowed state matches actual state"""
            if not actual:
                return False

            allowed_norm = normalize_state(allowed)
            actual_norm = normalize_state(actual)

            # Direct match after normalization
            if allowed_norm == actual_norm:
                return True

            # Check abbreviation match
            allowed_lower = allowed.lower().strip()
            actual_lower = actual.lower().strip()

            # allowed is abbreviation, actual is full name
            if allowed_lower in state_aliases and state_aliases[allowed_lower] == actual_norm:
                return True

            # allowed is full name, actual is abbreviation
            if actual_lower in state_aliases and state_aliases[actual_lower] == allowed_norm:
                return True

            # Partial match
            if allowed_norm in actual_norm or actual_norm in allowed_norm:
                return True

            return False

        # Check country
        country_ok = any(matches_country(c, country) for c in self.allowed_countries)
        if not country_ok:
            return False, "country"

        # Check state (if states are specified)
        if self.allowed_states:
            state_ok = any(matches_state(s, state) for s in self.allowed_states)
            if not state_ok:
                return False, "state"

        return True, None

    def run_check(self):
        if self.is_running:
            return
        u = self.username_entry.get().strip()
        p = self.password_entry.get().strip()
        lat_s = self.lat_entry.get().strip()
        lon_s = self.lon_entry.get().strip()

        if not u:
            self.show_settings()
            messagebox.showwarning("Settings Required", "Username is required")
            return
        if not p:
            self.show_settings()
            messagebox.showwarning("Settings Required", "Password is required")
            return
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
        self.run_btn.configure(state="disabled", text="Checking...")
        threading.Thread(target=self._run_check, args=(lat, lon), daemon=True).start()

    def _run_check(self, lat, lon):
        """Run check with full verification"""
        errors = []
        ip_loc = None
        gps_loc = None
        ip = None

        def finish_error(msg):
            self.current_data["status"] = "error"
            self.update_status("error", msg)
            self.update_cards()
            self.send_notification("Error", msg)
            self.supabase.log_check(ip, ip_loc, gps_loc, "error", msg)

        try:
            # Step 1: Test Device Portal connection
            self.update_status("running", "Connecting to Device Portal...")
            portal_ok, portal_error = self.test_device_portal()

            if not portal_ok:
                if portal_error == "auth_failed":
                    finish_error("Device Portal: Bad username/password")
                    return
                # Retry
                time.sleep(2)
                portal_ok, portal_error = self.test_device_portal()
                if not portal_ok:
                    if portal_error == "auth_failed":
                        finish_error("Device Portal: Bad username/password")
                    else:
                        finish_error("Device Portal unavailable")
                    return

            # Step 2: Activate location service
            self.update_status("running", "Activating location...")
            self.activate_location_service()

            # Step 3: Initialize location endpoints (CRITICAL!)
            self.update_status("running", "Setting GPS coordinates...")
            self.initialize_location()

            # Step 4: Set position with verification
            inject_success = False
            inject_error = ""

            for attempt in range(3):
                success, error = self.set_position(lat, lon)
                if success:
                    time.sleep(1)
                    pos = self.get_position()
                    if pos and pos.get("Latitude", 0) != 0:
                        inject_success = True
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

            # Step 5: Verify GPS coordinates location
            self.update_status("running", "Verifying GPS coordinates...")
            gps_loc = self.get_location_from_coordinates(lat, lon)

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
                print(f"WARNING: Could not get location from coordinates {lat}, {lon}")

            # Step 6: Check public IP
            self.update_status("running", "Checking public IP...")
            ip = self.get_public_ip()
            if ip:
                self.current_data["ip"] = ip
                ip_loc = self.get_location_data(ip)
                if ip_loc:
                    self.current_data["country"] = ip_loc["country"]
                    self.current_data["state"] = ip_loc["state"]
                    self.current_data["city"] = ip_loc["city"]
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

            # Step 7: Final result
            self.supabase.log_check(ip, ip_loc, gps_loc, "error" if errors else "success", " | ".join(errors) or "OK")

            if errors:
                self.current_data["status"] = "error"
                self.update_status("error", errors[0][:60])
                self.send_notification("Location Error", errors[0])
            else:
                self.current_data["status"] = "success"
                self.update_status("success", "Ready to work!")
                self.send_notification("Ready to work!", f"{self.current_data['city']}, {self.current_data['state']}")

            self.update_cards()

        except Exception as e:
            import traceback
            traceback.print_exc()
            finish_error(str(e)[:50])
        finally:
            self.is_running = False
            self.run_btn.configure(state="normal", text="▶  Run Check")

    def create_settings(self):
        scroll = ctk.CTkScrollableFrame(self.settings_frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # License
        lic = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        lic.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(lic, text="License", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 5))
        masked_hwid = "****" + self.supabase.hwid[-6:]
        ctk.CTkLabel(lic, text=f"ID: {masked_hwid}", font=ctk.CTkFont(size=11),
                    text_color=COLORS["text_secondary"]).pack(anchor="w", padx=16)
        ctk.CTkLabel(lic, text=f"Agent: {self.agent_name}", font=ctk.CTkFont(size=11),
                    text_color=COLORS["success"]).pack(anchor="w", padx=16, pady=(0, 12))

        # Credentials
        cred = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        cred.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(cred, text="Device Portal", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 10))

        uf = ctk.CTkFrame(cred, fg_color="transparent")
        uf.pack(fill="x", padx=16, pady=3)
        ctk.CTkLabel(uf, text="Username", width=80, anchor="w", text_color=COLORS["text_secondary"]).pack(side="left")
        self.username_entry = ctk.CTkEntry(uf, height=32)
        self.username_entry.pack(side="left", fill="x", expand=True)

        pf = ctk.CTkFrame(cred, fg_color="transparent")
        pf.pack(fill="x", padx=16, pady=(3, 12))
        ctk.CTkLabel(pf, text="Password", width=80, anchor="w", text_color=COLORS["text_secondary"]).pack(side="left")
        self.password_entry = ctk.CTkEntry(pf, show="*", height=32)
        self.password_entry.pack(side="left", fill="x", expand=True)

        # GPS
        gps = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        gps.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(gps, text="GPS Coordinates", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 10))

        lf = ctk.CTkFrame(gps, fg_color="transparent")
        lf.pack(fill="x", padx=16, pady=3)
        ctk.CTkLabel(lf, text="Latitude", width=80, anchor="w", text_color=COLORS["text_secondary"]).pack(side="left")
        self.lat_entry = ctk.CTkEntry(lf, height=32)
        self.lat_entry.pack(side="left", fill="x", expand=True)

        lof = ctk.CTkFrame(gps, fg_color="transparent")
        lof.pack(fill="x", padx=16, pady=(3, 12))
        ctk.CTkLabel(lof, text="Longitude", width=80, anchor="w", text_color=COLORS["text_secondary"]).pack(side="left")
        self.lon_entry = ctk.CTkEntry(lof, height=32)
        self.lon_entry.pack(side="left", fill="x", expand=True)

        # Countries
        co = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        co.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(co, text="Allowed Countries", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 6))
        self.countries_entry = ctk.CTkTextbox(co, height=50, corner_radius=6, fg_color=COLORS["bg_dark"])
        self.countries_entry.pack(fill="x", padx=16, pady=(0, 12))

        # States
        st = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        st.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(st, text="Allowed States", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 6))
        self.states_entry = ctk.CTkTextbox(st, height=50, corner_radius=6, fg_color=COLORS["bg_dark"])
        self.states_entry.pack(fill="x", padx=16, pady=(0, 12))

        # Interval
        iv = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        iv.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(iv, text="Auto-Check Interval", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 10))
        ivf = ctk.CTkFrame(iv, fg_color="transparent")
        ivf.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(ivf, text="Minutes", width=80, anchor="w", text_color=COLORS["text_secondary"]).pack(side="left")
        self.interval_entry = ctk.CTkEntry(ivf, width=70, height=32)
        self.interval_entry.pack(side="left")
        self.interval_entry.insert(0, "5")

        # Save
        ctk.CTkButton(scroll, text="Save Settings", width=150, height=42, corner_radius=10,
                     fg_color=COLORS["accent"], hover_color=COLORS["accent_dark"], text_color="#000",
                     font=ctk.CTkFont(size=14, weight="bold"), command=self.save_config).pack(pady=15)


if __name__ == "__main__":
    app = GeoApp()
    app.mainloop()
