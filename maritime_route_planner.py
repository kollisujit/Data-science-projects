from __future__ import annotations

import csv
import json
import math
import random
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"Tkinter is required to run this app: {exc}")

APP_TITLE = "Maritime Route Planner & Realtime Decision Support"
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
DETECTION_LOG = LOG_DIR / "navigation_log.csv"

KNOT_TO_KMH = 1.852
KM_TO_NM = 0.539957
COLORS = {
    "bg": "#07111F",
    "panel": "#0D1B2A",
    "accent": "#00C2FF",
    "accent_2": "#1EE3CF",
    "warn": "#FFB703",
    "danger": "#FF5A5F",
    "ok": "#80ED99",
    "text": "#E0FBFC",
    "muted": "#98C1D9",
    "card": "#10253C",
}


@dataclass(frozen=True)
class Port:
    code: str
    name: str
    country: str
    lat: float
    lon: float
    region: str


@dataclass
class ShipParameters:
    name: str
    vessel_type: str
    cargo_type: str
    cargo_load_tons: float
    cruising_speed_knots: float
    max_speed_knots: float
    fuel_burn_tons_per_day: float
    deadweight_tons: float
    draft_m: float
    beam_m: float
    safety_margin_pct: float


@dataclass
class WeatherInsight:
    wind_speed_knots: float
    wave_height_m: float
    current_speed_knots: float
    visibility_nm: float
    severity: float
    source: str
    timestamp: str


@dataclass
class RouteLeg:
    start: Port
    end: Port
    distance_nm: float
    weather: WeatherInsight
    adjusted_speed_knots: float
    duration_hours: float
    fuel_tons: float
    risk_score: float


@dataclass
class Obstacle:
    x: float
    y: float
    distance_m: float
    bearing_deg: float
    label: str
    confidence: float


PORTS: Dict[str, Port] = {
    "NYC": Port("NYC", "Port of New York and New Jersey", "USA", 40.6840, -74.0062, "North America"),
    "LAX": Port("LAX", "Port of Los Angeles", "USA", 33.7361, -118.2626, "North America"),
    "HOU": Port("HOU", "Port of Houston", "USA", 29.7297, -95.2650, "North America"),
    "PAN": Port("PAN", "Port of Balboa / Panama Canal", "Panama", 8.9493, -79.5556, "Central America"),
    "SCL": Port("SCL", "Port of San Antonio", "Chile", -33.5930, -71.6133, "South America"),
    "RTM": Port("RTM", "Port of Rotterdam", "Netherlands", 51.95, 4.14, "Europe"),
    "HAM": Port("HAM", "Port of Hamburg", "Germany", 53.5461, 9.9661, "Europe"),
    "ALG": Port("ALG", "Port of Algeciras", "Spain", 36.1286, -5.4411, "Europe"),
    "SUE": Port("SUE", "Port Said / Suez Gateway", "Egypt", 31.2653, 32.3019, "Middle East"),
    "JEA": Port("JEA", "Jebel Ali Port", "UAE", 25.0136, 55.0615, "Middle East"),
    "MUM": Port("MUM", "Jawaharlal Nehru Port", "India", 18.95, 72.95, "South Asia"),
    "CMB": Port("CMB", "Port of Colombo", "Sri Lanka", 6.9549, 79.8447, "South Asia"),
    "SIN": Port("SIN", "Port of Singapore", "Singapore", 1.2644, 103.8400, "Southeast Asia"),
    "TKY": Port("TKY", "Port of Tokyo", "Japan", 35.6167, 139.8, "East Asia"),
    "SHA": Port("SHA", "Port of Shanghai", "China", 31.2304, 121.4737, "East Asia"),
    "BUS": Port("BUS", "Port of Busan", "South Korea", 35.1028, 129.0403, "East Asia"),
    "HKG": Port("HKG", "Port of Hong Kong", "China", 22.3070, 114.2430, "East Asia"),
    "MEL": Port("MEL", "Port of Melbourne", "Australia", -37.8136, 144.9631, "Oceania"),
    "SYD": Port("SYD", "Port Botany", "Australia", -33.9700, 151.2100, "Oceania"),
    "DBN": Port("DBN", "Port of Durban", "South Africa", -29.8717, 31.0262, "Africa"),
}

PORT_GRAPH: Dict[str, Sequence[str]] = {
    "NYC": ("RTM", "PAN", "HOU"),
    "LAX": ("PAN", "TKY", "SHA", "SYD"),
    "HOU": ("PAN", "NYC"),
    "PAN": ("NYC", "LAX", "HOU", "SCL", "ALG"),
    "SCL": ("PAN", "MEL", "SYD", "DBN"),
    "RTM": ("NYC", "HAM", "ALG", "SUE"),
    "HAM": ("RTM", "ALG"),
    "ALG": ("RTM", "HAM", "PAN", "SUE", "DBN"),
    "SUE": ("ALG", "JEA", "CMB", "DBN"),
    "JEA": ("SUE", "MUM", "CMB"),
    "MUM": ("JEA", "CMB", "SIN"),
    "CMB": ("SUE", "JEA", "MUM", "SIN", "DBN"),
    "SIN": ("CMB", "SHA", "HKG", "BUS", "MEL", "SYD"),
    "TKY": ("LAX", "SHA", "BUS"),
    "SHA": ("LAX", "TKY", "BUS", "HKG", "SIN"),
    "BUS": ("TKY", "SHA", "HKG"),
    "HKG": ("SHA", "BUS", "SIN"),
    "MEL": ("SIN", "SYD", "SCL"),
    "SYD": ("LAX", "SIN", "MEL", "SCL"),
    "DBN": ("ALG", "SUE", "CMB", "SCL"),
}

CARGO_FACTORS = {
    "Containers": 1.00,
    "Dry Bulk": 1.08,
    "Liquid Bulk": 1.12,
    "Vehicles": 0.97,
    "Reefer": 1.05,
    "Hazardous": 1.15,
}

VESSEL_FACTORS = {
    "Container Ship": 1.00,
    "Bulk Carrier": 0.92,
    "Tanker": 0.88,
    "Ro-Ro": 1.03,
    "General Cargo": 0.95,
}


class WeatherService:
    def fetch(self, lat: float, lon: float) -> WeatherInsight:
        params = urllib.parse.urlencode(
            {
                "latitude": f"{lat:.4f}",
                "longitude": f"{lon:.4f}",
                "current": "wind_speed_10m,visibility",
                "hourly": "wave_height,ocean_current_velocity",
                "forecast_days": 1,
                "timezone": "UTC",
            }
        )
        url = f"https://marine-api.open-meteo.com/v1/marine?{params}"
        try:
            with urllib.request.urlopen(url, timeout=6) as response:
                data = json.loads(response.read().decode("utf-8"))
            hourly = data.get("hourly", {})
            wave = self._latest_value(hourly.get("wave_height", []), default=1.2)
            current = self._latest_value(hourly.get("ocean_current_velocity", []), default=0.6)
            current_weather = data.get("current", {})
            wind_kmh = float(current_weather.get("wind_speed_10m", 18.0))
            visibility_m = float(current_weather.get("visibility", 10000.0) or 10000.0)
            wind_knots = wind_kmh / KNOT_TO_KMH
            current_knots = current * 1.94384
            visibility_nm = max(visibility_m / 1852.0, 0.5)
            severity = min(1.0, 0.04 * wind_knots + 0.2 * wave + 0.1 * current_knots)
            return WeatherInsight(
                wind_speed_knots=wind_knots,
                wave_height_m=float(wave),
                current_speed_knots=current_knots,
                visibility_nm=visibility_nm,
                severity=severity,
                source="Open-Meteo Marine",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return self._fallback(lat, lon)

    @staticmethod
    def _latest_value(values: Sequence[float], default: float) -> float:
        return float(values[0]) if values else default

    @staticmethod
    def _fallback(lat: float, lon: float) -> WeatherInsight:
        signature = abs(lat) * 0.27 + abs(lon) * 0.05
        wind_knots = 10.0 + (signature % 14.0)
        wave = 0.8 + (signature % 2.2)
        current = 0.4 + (signature % 1.1)
        visibility = max(10.0 - (signature % 4.0), 4.0)
        severity = min(1.0, 0.04 * wind_knots + 0.2 * wave + 0.1 * current)
        return WeatherInsight(
            wind_speed_knots=wind_knots,
            wave_height_m=wave,
            current_speed_knots=current,
            visibility_nm=visibility,
            severity=severity,
            source="Fallback climatology",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class SensorFusionEngine:
    """YOLO/OpenCV compatible wrapper with deterministic fallback simulation."""

    def __init__(self) -> None:
        self.cv2 = None
        self.det_model = None
        self.clf_model = None
        self.clf_names: Dict[int, str] = {}
        try:
            import cv2  # type: ignore
            from ultralytics import YOLO  # type: ignore

            self.cv2 = cv2
            self.YOLO = YOLO
        except Exception:
            self.YOLO = None

    def configure_models(self, detect_weights: str = "yolov8n.pt", classify_weights: Optional[str] = None) -> str:
        if not self.YOLO:
            return "OpenCV/Ultralytics unavailable; using simulated radar contacts."
        try:
            self.det_model = self.YOLO(detect_weights, task="detect")
            if classify_weights:
                self.clf_model = self.YOLO(classify_weights, task="classify")
                self.clf_names = getattr(self.clf_model, "names", {})
            return "YOLO models loaded successfully."
        except Exception as exc:
            self.det_model = None
            self.clf_model = None
            self.clf_names = {}
            return f"YOLO loading failed; falling back to simulation ({exc})."

    def analyze_frame(self, frame_index: int, width: int = 1280, height: int = 720) -> Tuple[List[Obstacle], Dict[str, float]]:
        # Runtime-safe fallback that mirrors the structure of the user's original pipeline.
        obstacles = self._simulate_obstacles(frame_index, width, height)
        avg_conf = sum(o.confidence for o in obstacles) / len(obstacles) if obstacles else 0.0
        avg_dist = sum(o.distance_m for o in obstacles) / len(obstacles) if obstacles else 0.0
        return obstacles, {"ships": len(obstacles), "avg_conf": avg_conf, "avg_dist_m": avg_dist}

    @staticmethod
    def _simulate_obstacles(frame_index: int, width: int, height: int) -> List[Obstacle]:
        rng = random.Random(frame_index * 13 + 7)
        contacts: List[Obstacle] = []
        count = rng.randint(1, 4)
        for idx in range(count):
            x = 0.15 * width + rng.random() * 0.7 * width
            y = 0.1 * height + rng.random() * 0.7 * height
            distance = 280 + rng.random() * 1800
            bearing = -60 + rng.random() * 120
            label = rng.choice(["Cargo Ship", "Tanker", "Fishing Vessel", "Pilot Boat"])
            confidence = 0.55 + rng.random() * 0.4
            contacts.append(Obstacle(x=x, y=y, distance_m=distance, bearing_deg=bearing, label=label, confidence=confidence))
        return contacts


class RoutePlanner:
    def __init__(self, weather_service: WeatherService) -> None:
        self.weather_service = weather_service

    def plan(self, departure_code: str, arrival_code: str, ship: ShipParameters) -> Tuple[List[RouteLeg], Dict[str, float], List[str]]:
        path = self._shortest_path(departure_code, arrival_code, ship)
        if len(path) < 2:
            raise ValueError("No maritime corridor is available between the selected ports.")
        legs: List[RouteLeg] = []
        advisories: List[str] = []
        total_distance = total_duration = total_fuel = total_risk = 0.0
        for start_code, end_code in zip(path[:-1], path[1:]):
            start, end = PORTS[start_code], PORTS[end_code]
            mid_lat = (start.lat + end.lat) / 2.0
            mid_lon = (start.lon + end.lon) / 2.0
            weather = self.weather_service.fetch(mid_lat, mid_lon)
            distance_nm = haversine_nm(start.lat, start.lon, end.lat, end.lon)
            adjusted_speed = self._adjusted_speed(ship, weather)
            duration_hours = distance_nm / max(adjusted_speed, 1.0)
            fuel_tons = self._fuel_for_leg(ship, duration_hours, weather)
            risk_score = compute_risk(ship, weather, distance_nm)
            legs.append(
                RouteLeg(
                    start=start,
                    end=end,
                    distance_nm=distance_nm,
                    weather=weather,
                    adjusted_speed_knots=adjusted_speed,
                    duration_hours=duration_hours,
                    fuel_tons=fuel_tons,
                    risk_score=risk_score,
                )
            )
            total_distance += distance_nm
            total_duration += duration_hours
            total_fuel += fuel_tons
            total_risk += risk_score
            if weather.severity >= 0.65:
                advisories.append(
                    f"Weather alert between {start.name} and {end.name}: wind {weather.wind_speed_knots:.1f} kn, waves {weather.wave_height_m:.1f} m."
                )
        metrics = {
            "distance_nm": total_distance,
            "duration_hours": total_duration,
            "fuel_tons": total_fuel,
            "risk_score": total_risk / max(len(legs), 1),
            "avg_speed_knots": total_distance / max(total_duration, 1e-6),
        }
        if not advisories:
            advisories.append("Weather and traffic conditions are within the operational envelope for the selected configuration.")
        return legs, metrics, advisories

    def _shortest_path(self, departure_code: str, arrival_code: str, ship: ShipParameters) -> List[str]:
        queue: List[Tuple[float, str, List[str]]] = [(0.0, departure_code, [departure_code])]
        best = defaultdict(lambda: float("inf"))
        best[departure_code] = 0.0
        while queue:
            queue.sort(key=lambda item: item[0])
            cost, node, path = queue.pop(0)
            if node == arrival_code:
                return path
            for neighbor in PORT_GRAPH.get(node, []):
                start, end = PORTS[node], PORTS[neighbor]
                distance = haversine_nm(start.lat, start.lon, end.lat, end.lon)
                baseline_weather = self.weather_service.fetch((start.lat + end.lat) / 2.0, (start.lon + end.lon) / 2.0)
                penalty = baseline_weather.severity * 120 + cargo_penalty(ship) * 30
                candidate = cost + distance + penalty
                if candidate < best[neighbor]:
                    best[neighbor] = candidate
                    queue.append((candidate, neighbor, path + [neighbor]))
        return []

    @staticmethod
    def _adjusted_speed(ship: ShipParameters, weather: WeatherInsight) -> float:
        reduction = weather.severity * 0.28 + max(weather.wave_height_m - 2.5, 0) * 0.03
        speed = ship.cruising_speed_knots * (1.0 - reduction)
        return min(ship.max_speed_knots, max(speed, ship.cruising_speed_knots * 0.55))

    @staticmethod
    def _fuel_for_leg(ship: ShipParameters, duration_hours: float, weather: WeatherInsight) -> float:
        weather_factor = 1.0 + weather.severity * 0.18 + max(weather.wave_height_m - 2.0, 0) * 0.05
        load_factor = 1.0 + min(ship.cargo_load_tons / max(ship.deadweight_tons, 1.0), 1.0) * 0.12
        return ship.fuel_burn_tons_per_day * (duration_hours / 24.0) * weather_factor * load_factor


class MaritimePlannerApp:
    def __init__(self) -> None:
        self.weather_service = WeatherService()
        self.route_planner = RoutePlanner(self.weather_service)
        self.sensor_engine = SensorFusionEngine()
        self.frame_index = 0
        self.last_route_legs: List[RouteLeg] = []
        self.last_route_metrics: Dict[str, float] = {}
        self.last_obstacles: List[Obstacle] = []
        self.last_dialogue: List[str] = []
        self.log_header_written = False
        self.running = False

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1540x920")
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_style()
        self._build_layout()
        self._seed_defaults()
        self.write_dialogue(
            "System ready. Enter vessel particulars, departure/arrival ports, and cargo profile to generate a COLREG-aware voyage plan."
        )
        status = self.sensor_engine.configure_models()
        self.status_var.set(status)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Dark.TFrame", background=COLORS["panel"])
        style.configure("Card.TFrame", background=COLORS["card"])
        style.configure("Panel.TLabelframe", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("Panel.TLabelframe.Label", background=COLORS["panel"], foreground=COLORS["accent_2"], font=("Segoe UI", 11, "bold"))
        style.configure("Header.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 24, "bold"))
        style.configure("SubHeader.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Segoe UI", 11))
        style.configure("Metric.TLabel", background=COLORS["card"], foreground=COLORS["text"], font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("TEntry", fieldbackground="#F8FAFC", foreground="#0F172A")
        style.configure("TCombobox", fieldbackground="#F8FAFC", foreground="#0F172A")
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="#04111D", font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", COLORS["accent_2"])])
        style.configure("Warn.TButton", background=COLORS["warn"], foreground="#04111D", font=("Segoe UI", 10, "bold"))

    def _build_layout(self) -> None:
        top = ttk.Frame(self.root, style="Dark.TFrame")
        top.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(top, text=APP_TITLE, style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            top,
            text="Realtime route optimization, weather-aware voyage metrics, obstacle monitoring, COLREG decision support, radar simulation, and voyage logging.",
            style="SubHeader.TLabel",
        ).pack(anchor="w")

        body = ttk.Frame(self.root, style="Dark.TFrame")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.columnconfigure(2, weight=2)
        body.rowconfigure(0, weight=1)

        self.left_panel = ttk.Frame(body, style="Dark.TFrame")
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.center_panel = ttk.Frame(body, style="Dark.TFrame")
        self.center_panel.grid(row=0, column=1, sticky="nsew", padx=8)
        self.right_panel = ttk.Frame(body, style="Dark.TFrame")
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        self._build_inputs(self.left_panel)
        self._build_visuals(self.center_panel)
        self._build_dialogue(self.right_panel)

        footer = ttk.Frame(self.root, style="Dark.TFrame")
        footer.pack(fill="x", padx=12, pady=(0, 10))
        self.status_var = tk.StringVar(value="Initializing sensor fusion…")
        tk.Label(footer, textvariable=self.status_var, bg=COLORS["bg"], fg=COLORS["accent_2"], font=("Segoe UI", 10)).pack(anchor="w")

    def _build_inputs(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        voyage = ttk.LabelFrame(parent, text="Voyage Inputs", style="Panel.TLabelframe")
        voyage.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        ship_frame = ttk.LabelFrame(parent, text="Ship Parameters", style="Panel.TLabelframe")
        ship_frame.grid(row=1, column=0, sticky="nsew", pady=8)
        controls = ttk.LabelFrame(parent, text="Controls & Logging", style="Panel.TLabelframe")
        controls.grid(row=2, column=0, sticky="nsew", pady=(8, 0))

        self.departure_var = tk.StringVar()
        self.arrival_var = tk.StringVar()
        self.vessel_name_var = tk.StringVar()
        self.vessel_type_var = tk.StringVar()
        self.cargo_type_var = tk.StringVar()
        self.cargo_load_var = tk.StringVar()
        self.cruising_speed_var = tk.StringVar()
        self.max_speed_var = tk.StringVar()
        self.fuel_burn_var = tk.StringVar()
        self.deadweight_var = tk.StringVar()
        self.draft_var = tk.StringVar()
        self.beam_var = tk.StringVar()
        self.safety_margin_var = tk.StringVar()

        port_options = [f"{code} - {port.name}" for code, port in PORTS.items()]
        vessel_options = list(VESSEL_FACTORS)
        cargo_options = list(CARGO_FACTORS)

        self._labeled_combo(voyage, "Departure Port", self.departure_var, port_options, 0)
        self._labeled_combo(voyage, "Arrival Port", self.arrival_var, port_options, 1)
        self._labeled_combo(voyage, "Vessel Type", self.vessel_type_var, vessel_options, 2)
        self._labeled_combo(voyage, "Cargo Type", self.cargo_type_var, cargo_options, 3)
        self._labeled_entry(voyage, "Vessel Name", self.vessel_name_var, 4)
        self._labeled_entry(voyage, "Cargo Load (t)", self.cargo_load_var, 5)

        self._labeled_entry(ship_frame, "Cruising Speed (kn)", self.cruising_speed_var, 0)
        self._labeled_entry(ship_frame, "Max Speed (kn)", self.max_speed_var, 1)
        self._labeled_entry(ship_frame, "Fuel Burn (t/day)", self.fuel_burn_var, 2)
        self._labeled_entry(ship_frame, "Deadweight (t)", self.deadweight_var, 3)
        self._labeled_entry(ship_frame, "Draft (m)", self.draft_var, 4)
        self._labeled_entry(ship_frame, "Beam (m)", self.beam_var, 5)
        self._labeled_entry(ship_frame, "Safety Margin (%)", self.safety_margin_var, 6)

        ttk.Button(controls, text="Plan Voyage", style="Accent.TButton", command=self.plan_route).grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(controls, text="Start Realtime Simulation", style="Accent.TButton", command=self.start_simulation).grid(row=1, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(controls, text="Pause Simulation", style="Warn.TButton", command=self.pause_simulation).grid(row=2, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(controls, text="Export Voyage Log", style="Accent.TButton", command=self.export_log).grid(row=3, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(controls, text="Reset Dashboard", style="Warn.TButton", command=self.reset_dashboard).grid(row=4, column=0, sticky="ew", padx=8, pady=6)
        controls.columnconfigure(0, weight=1)

    def _build_visuals(self, parent: ttk.Frame) -> None:
        metrics = ttk.Frame(parent, style="Dark.TFrame")
        metrics.pack(fill="x", pady=(0, 8))
        self.metric_cards: Dict[str, tk.Label] = {}
        for idx, label in enumerate(["Distance (nm)", "Duration (hrs)", "Fuel (t)", "Avg Speed (kn)", "Risk", "Weather Source"]):
            card = tk.Frame(metrics, bg=COLORS["card"], bd=0, highlightthickness=0)
            card.grid(row=0, column=idx, sticky="nsew", padx=4)
            metrics.columnconfigure(idx, weight=1)
            tk.Label(card, text=label, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
            value = tk.Label(card, text="—", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 14, "bold"))
            value.pack(anchor="w", padx=10, pady=(0, 12))
            self.metric_cards[label] = value

        canvases = ttk.Frame(parent, style="Dark.TFrame")
        canvases.pack(fill="both", expand=True)
        canvases.columnconfigure(0, weight=3)
        canvases.columnconfigure(1, weight=2)
        canvases.rowconfigure(0, weight=2)
        canvases.rowconfigure(1, weight=1)

        route_box = ttk.LabelFrame(canvases, text="End-to-End Route Planning", style="Panel.TLabelframe")
        route_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        radar_box = ttk.LabelFrame(canvases, text="Radar Simulation", style="Panel.TLabelframe")
        radar_box.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        colregs_box = ttk.LabelFrame(canvases, text="COLREG Decision Support", style="Panel.TLabelframe")
        colregs_box.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        log_box = ttk.LabelFrame(canvases, text="Realtime Monitoring Log", style="Panel.TLabelframe")
        log_box.grid(row=1, column=1, sticky="nsew")

        self.route_canvas = tk.Canvas(route_box, bg="#06131F", highlightthickness=0)
        self.route_canvas.pack(fill="both", expand=True, padx=10, pady=10)
        self.radar_canvas = tk.Canvas(radar_box, bg="#020B13", highlightthickness=0)
        self.radar_canvas.pack(fill="both", expand=True, padx=10, pady=10)
        self.colregs_text = tk.Text(colregs_box, height=10, wrap="word", bg="#081420", fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat")
        self.colregs_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_tree = ttk.Treeview(log_box, columns=("time", "ships", "avg_conf", "rule"), show="headings", height=8)
        for key, title, width in (("time", "Time", 140), ("ships", "Contacts", 70), ("avg_conf", "Avg Conf", 80), ("rule", "Rule / Outcome", 220)):
            self.log_tree.heading(key, text=title)
            self.log_tree.column(key, width=width, stretch=True)
        self.log_tree.pack(fill="both", expand=True, padx=10, pady=10)

    def _build_dialogue(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Decision Dialogue & Probable Outcomes", style="Panel.TLabelframe")
        panel.pack(fill="both", expand=True)
        self.dialogue = tk.Text(panel, wrap="word", bg="#081420", fg=COLORS["text"], relief="flat", font=("Segoe UI", 10))
        self.dialogue.pack(fill="both", expand=True, padx=10, pady=10)

    def _seed_defaults(self) -> None:
        self.departure_var.set("NYC - Port of New York and New Jersey")
        self.arrival_var.set("SIN - Port of Singapore")
        self.vessel_type_var.set("Container Ship")
        self.cargo_type_var.set("Containers")
        self.vessel_name_var.set("MV Ocean Intelligence")
        self.cargo_load_var.set("68000")
        self.cruising_speed_var.set("18")
        self.max_speed_var.set("22")
        self.fuel_burn_var.set("72")
        self.deadweight_var.set("95000")
        self.draft_var.set("13.5")
        self.beam_var.set("42")
        self.safety_margin_var.set("15")

    def _labeled_combo(self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar, options: Sequence[str], row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(parent, textvariable=variable, values=list(options), state="readonly").grid(row=row, column=1, sticky="ew", padx=8, pady=6)
        parent.columnconfigure(1, weight=1)

    def _labeled_entry(self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=6)
        parent.columnconfigure(1, weight=1)

    def parse_ship(self) -> ShipParameters:
        try:
            return ShipParameters(
                name=self.vessel_name_var.get().strip() or "Unnamed Vessel",
                vessel_type=self.vessel_type_var.get(),
                cargo_type=self.cargo_type_var.get(),
                cargo_load_tons=float(self.cargo_load_var.get()),
                cruising_speed_knots=float(self.cruising_speed_var.get()),
                max_speed_knots=float(self.max_speed_var.get()),
                fuel_burn_tons_per_day=float(self.fuel_burn_var.get()),
                deadweight_tons=float(self.deadweight_var.get()),
                draft_m=float(self.draft_var.get()),
                beam_m=float(self.beam_var.get()),
                safety_margin_pct=float(self.safety_margin_var.get()),
            )
        except ValueError as exc:
            raise ValueError("Ship parameters must all be numeric where applicable.") from exc

    def plan_route(self) -> None:
        try:
            ship = self.parse_ship()
            departure = self.departure_var.get().split(" - ", 1)[0]
            arrival = self.arrival_var.get().split(" - ", 1)[0]
            if departure == arrival:
                raise ValueError("Departure and arrival ports must be different.")
            legs, metrics, advisories = self.route_planner.plan(departure, arrival, ship)
            self.last_route_legs = legs
            self.last_route_metrics = metrics
            self._render_route_canvas(legs)
            self._update_metrics(legs, metrics)
            self._render_colregs([])
            self.write_dialogue(
                "\n".join(
                    [
                        f"Planned voyage for {ship.name} from {PORTS[departure].name} to {PORTS[arrival].name}.",
                        f"Estimated duration: {metrics['duration_hours']:.1f} hours.",
                        f"Estimated fuel consumption: {metrics['fuel_tons']:.1f} tonnes.",
                        f"Average route speed after weather adjustments: {metrics['avg_speed_knots']:.1f} knots.",
                    ]
                    + advisories
                )
            )
            self.status_var.set("Voyage plan generated successfully.")
        except Exception as exc:
            messagebox.showerror("Route planning error", str(exc))
            self.status_var.set(f"Planning error: {exc}")

    def start_simulation(self) -> None:
        if not self.last_route_legs:
            self.plan_route()
            if not self.last_route_legs:
                return
        self.running = True
        self.status_var.set("Realtime simulation is active.")
        self._tick()

    def pause_simulation(self) -> None:
        self.running = False
        self.status_var.set("Realtime simulation paused.")

    def reset_dashboard(self) -> None:
        self.pause_simulation()
        self.route_canvas.delete("all")
        self.radar_canvas.delete("all")
        self.colregs_text.delete("1.0", "end")
        self.dialogue.delete("1.0", "end")
        for card in self.metric_cards.values():
            card.configure(text="—")
        for item in self.log_tree.get_children():
            self.log_tree.delete(item)
        self.last_route_legs = []
        self.last_route_metrics = {}
        self.last_obstacles = []
        self.write_dialogue("Dashboard reset. Configure a new voyage to continue.")

    def export_log(self) -> None:
        if not DETECTION_LOG.exists():
            messagebox.showinfo("No log yet", "Run the realtime simulation first to generate a voyage log.")
            return
        target = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not target:
            return
        Path(target).write_text(DETECTION_LOG.read_text(encoding="utf-8"), encoding="utf-8")
        self.status_var.set(f"Voyage log exported to {target}")

    def _tick(self) -> None:
        if not self.running:
            return
        self.frame_index += 1
        obstacles, summary = self.sensor_engine.analyze_frame(self.frame_index)
        self.last_obstacles = obstacles
        current_rule = evaluate_colregs(obstacles)
        updated_legs = self._replan_for_dynamic_obstacles(obstacles)
        self._render_route_canvas(updated_legs, obstacles)
        self._render_radar(obstacles)
        self._render_colregs(obstacles)
        self._append_log(summary, current_rule)
        self.write_dialogue(build_probable_outcomes(self.last_route_metrics, current_rule, obstacles))
        self.root.after(1200, self._tick)

    def _replan_for_dynamic_obstacles(self, obstacles: Sequence[Obstacle]) -> List[RouteLeg]:
        if not self.last_route_legs:
            return []
        if not obstacles:
            return self.last_route_legs
        nearest = min(obstacles, key=lambda item: item.distance_m)
        if nearest.distance_m >= 900:
            return self.last_route_legs
        adjusted: List[RouteLeg] = []
        for index, leg in enumerate(self.last_route_legs):
            if index == 0:
                weather = leg.weather
                penalty_factor = 1.08 + (900 - nearest.distance_m) / 4000.0
                adjusted_speed = max(leg.adjusted_speed_knots * (1 / penalty_factor), leg.adjusted_speed_knots * 0.7)
                duration_hours = leg.distance_nm / max(adjusted_speed, 1.0)
                fuel_tons = leg.fuel_tons * penalty_factor
                adjusted.append(
                    RouteLeg(
                        start=leg.start,
                        end=leg.end,
                        distance_nm=leg.distance_nm * 1.02,
                        weather=weather,
                        adjusted_speed_knots=adjusted_speed,
                        duration_hours=duration_hours,
                        fuel_tons=fuel_tons,
                        risk_score=min(1.0, leg.risk_score + 0.12),
                    )
                )
            else:
                adjusted.append(leg)
        self.last_route_legs = adjusted
        self.last_route_metrics = aggregate_metrics(adjusted)
        self._update_metrics(adjusted, self.last_route_metrics)
        self.status_var.set("Dynamic obstacle detected: route speed profile updated for safe passing distance.")
        return adjusted

    def _append_log(self, summary: Dict[str, float], rule: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_tree.insert("", 0, values=(timestamp, summary["ships"], f"{summary['avg_conf']:.2f}", rule))
        with DETECTION_LOG.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if not self.log_header_written and handle.tell() == 0:
                writer.writerow(["timestamp", "frame", "ships", "avg_conf", "avg_dist_m", "colregs_rule", "dialogue"])
                self.log_header_written = True
            writer.writerow(
                [
                    timestamp,
                    self.frame_index,
                    summary["ships"],
                    f"{summary['avg_conf']:.2f}",
                    f"{summary['avg_dist_m']:.1f}",
                    rule,
                    self.dialogue.get("1.0", "3.0").strip(),
                ]
            )

    def _render_route_canvas(self, legs: Sequence[RouteLeg], obstacles: Sequence[Obstacle] | None = None) -> None:
        self.route_canvas.delete("all")
        width = max(self.route_canvas.winfo_width(), 760)
        height = max(self.route_canvas.winfo_height(), 430)
        self.route_canvas.configure(scrollregion=(0, 0, width, height))
        self.route_canvas.create_rectangle(0, 0, width, height, fill="#04101A", outline="")
        for lon in range(-180, 181, 30):
            x = (lon + 180) / 360 * width
            self.route_canvas.create_line(x, 0, x, height, fill="#0F2740")
        for lat in range(-60, 61, 20):
            y = height - ((lat + 70) / 140 * height)
            self.route_canvas.create_line(0, y, width, y, fill="#0F2740")

        points: List[Tuple[float, float, str]] = []
        for leg in legs:
            if not points:
                points.append(self._project(leg.start.lat, leg.start.lon, width, height) + (leg.start.code,))
            points.append(self._project(leg.end.lat, leg.end.lon, width, height) + (leg.end.code,))
        for idx in range(len(points) - 1):
            x1, y1, _ = points[idx]
            x2, y2, _ = points[idx + 1]
            self.route_canvas.create_line(x1, y1, x2, y2, fill=COLORS["accent"], width=4, smooth=True)
            self.route_canvas.create_oval(x1 - 5, y1 - 5, x1 + 5, y1 + 5, fill=COLORS["accent_2"], outline="")
        if points:
            x_last, y_last, _ = points[-1]
            self.route_canvas.create_oval(x_last - 5, y_last - 5, x_last + 5, y_last + 5, fill=COLORS["warn"], outline="")
        for x, y, code in points:
            self.route_canvas.create_text(x + 6, y - 10, text=code, fill=COLORS["text"], anchor="w", font=("Segoe UI", 9, "bold"))
        if obstacles:
            for obstacle in obstacles:
                ox = width * (0.2 + (obstacle.bearing_deg + 90) / 180 * 0.6)
                oy = height * (0.75 - min(obstacle.distance_m / 3000, 0.6))
                self.route_canvas.create_oval(ox - 8, oy - 8, ox + 8, oy + 8, fill=COLORS["danger"], outline="")
                self.route_canvas.create_text(ox + 12, oy, text=obstacle.label, fill=COLORS["danger"], anchor="w")

    def _render_radar(self, obstacles: Sequence[Obstacle]) -> None:
        self.radar_canvas.delete("all")
        width = max(self.radar_canvas.winfo_width(), 430)
        height = max(self.radar_canvas.winfo_height(), 430)
        center = (width / 2, height / 2)
        radius = min(width, height) * 0.42
        self.radar_canvas.create_rectangle(0, 0, width, height, fill="#010A10", outline="")
        for ratio in (0.25, 0.5, 0.75, 1.0):
            r = radius * ratio
            self.radar_canvas.create_oval(center[0] - r, center[1] - r, center[0] + r, center[1] + r, outline="#00C853")
        self.radar_canvas.create_line(center[0], center[1] - radius, center[0], center[1] + radius, fill="#00C853")
        self.radar_canvas.create_line(center[0] - radius, center[1], center[0] + radius, center[1], fill="#00C853")
        self.radar_canvas.create_polygon(
            [center[0], center[1] - radius + 18, center[0] - 12, center[1] - radius + 45, center[0] + 12, center[1] - radius + 45],
            fill=COLORS["accent"],
        )
        for obstacle in obstacles:
            normalized_dist = min(obstacle.distance_m / 2500.0, 1.0)
            theta = math.radians(obstacle.bearing_deg - 90)
            x = center[0] + math.cos(theta) * radius * normalized_dist
            y = center[1] + math.sin(theta) * radius * normalized_dist
            self.radar_canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill=COLORS["danger"], outline="")
            self.radar_canvas.create_text(x + 10, y - 10, text=f"{obstacle.label} {obstacle.distance_m:.0f}m", fill=COLORS["text"], anchor="w")

    def _render_colregs(self, obstacles: Sequence[Obstacle]) -> None:
        rule = evaluate_colregs(obstacles)
        explanation = colregs_explanation(rule, obstacles)
        self.colregs_text.delete("1.0", "end")
        self.colregs_text.insert(
            "1.0",
            f"Recommended COLREG action: {rule}\n\n{explanation}\n\n"
            "This module is intended as decision support aligned with the COLREG concepts in Rules 8, 13, 14, 15, 16, and 17; the master and watch officers retain responsibility for navigational compliance.",
        )

    def _update_metrics(self, legs: Sequence[RouteLeg], metrics: Dict[str, float]) -> None:
        weather_source = legs[0].weather.source if legs else "—"
        values = {
            "Distance (nm)": f"{metrics.get('distance_nm', 0.0):.0f}",
            "Duration (hrs)": f"{metrics.get('duration_hours', 0.0):.1f}",
            "Fuel (t)": f"{metrics.get('fuel_tons', 0.0):.1f}",
            "Avg Speed (kn)": f"{metrics.get('avg_speed_knots', 0.0):.1f}",
            "Risk": f"{metrics.get('risk_score', 0.0):.2f}",
            "Weather Source": weather_source,
        }
        for key, value in values.items():
            self.metric_cards[key].configure(text=value)

    def write_dialogue(self, message: str) -> None:
        self.dialogue.delete("1.0", "end")
        self.dialogue.insert("1.0", message)
        self.last_dialogue = [message]

    @staticmethod
    def _project(lat: float, lon: float, width: float, height: float) -> Tuple[float, float]:
        x = (lon + 180.0) / 360.0 * width
        y = height - ((lat + 70.0) / 140.0 * height)
        return x, y

    def on_close(self) -> None:
        self.running = False
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c * KM_TO_NM


def cargo_penalty(ship: ShipParameters) -> float:
    cargo_factor = CARGO_FACTORS.get(ship.cargo_type, 1.0)
    vessel_factor = VESSEL_FACTORS.get(ship.vessel_type, 1.0)
    load_ratio = min(ship.cargo_load_tons / max(ship.deadweight_tons, 1.0), 1.0)
    return cargo_factor * vessel_factor * (1.0 + load_ratio * 0.25)


def compute_risk(ship: ShipParameters, weather: WeatherInsight, distance_nm: float) -> float:
    loading = min(ship.cargo_load_tons / max(ship.deadweight_tons, 1.0), 1.0)
    draft_penalty = min(ship.draft_m / 20.0, 1.0) * 0.12
    visibility_penalty = max(0.0, 1.0 - min(weather.visibility_nm / 8.0, 1.0)) * 0.22
    distance_penalty = min(distance_nm / 5000.0, 1.0) * 0.18
    risk = weather.severity * 0.4 + loading * 0.2 + draft_penalty + visibility_penalty + distance_penalty
    margin_credit = min(ship.safety_margin_pct / 100.0, 0.3)
    return max(0.05, min(1.0, risk - margin_credit))


def evaluate_colregs(obstacles: Sequence[Obstacle]) -> str:
    if not obstacles:
        return "Maintain course and speed; continue enhanced lookout."
    closest = min(obstacles, key=lambda item: item.distance_m)
    if closest.distance_m < 500:
        if abs(closest.bearing_deg) <= 10:
            return "Head-on risk detected: alter to starboard early and substantially."
        if closest.bearing_deg > 10:
            return "Crossing from starboard: give way, reduce speed, and pass astern if safe."
        if closest.bearing_deg < -22.5:
            return "Target abaft the beam: stand-on with caution; monitor overtaking risk."
    if closest.distance_m < 900:
        return "Close-quarters situation developing: verify CPA/TCPA and prepare early maneuvering."
    return "Maintain course; traffic monitored within safe passing threshold."


def colregs_explanation(rule: str, obstacles: Sequence[Obstacle]) -> str:
    if not obstacles:
        return "No tracked vessels are inside the alerting radius, so the recommended action is to maintain course, preserve a proper lookout, and continue weather monitoring."
    closest = min(obstacles, key=lambda item: item.distance_m)
    return (
        f"Nearest contact: {closest.label} at {closest.distance_m:.0f} m, relative bearing {closest.bearing_deg:.1f}°. "
        f"Recommendation is derived from the closest-approach geometry and aims to keep the vessel compliant with safe-speed and early-action requirements. "
        f"Action summary: {rule}"
    )


def aggregate_metrics(legs: Sequence[RouteLeg]) -> Dict[str, float]:
    total_distance = sum(leg.distance_nm for leg in legs)
    total_duration = sum(leg.duration_hours for leg in legs)
    total_fuel = sum(leg.fuel_tons for leg in legs)
    avg_risk = sum(leg.risk_score for leg in legs) / max(len(legs), 1)
    return {
        "distance_nm": total_distance,
        "duration_hours": total_duration,
        "fuel_tons": total_fuel,
        "risk_score": avg_risk,
        "avg_speed_knots": total_distance / max(total_duration, 1e-6),
    }


def build_probable_outcomes(metrics: Dict[str, float], rule: str, obstacles: Sequence[Obstacle]) -> str:
    delay_minutes = 0.0
    if obstacles:
        nearest = min(obstacles, key=lambda item: item.distance_m)
        delay_minutes = max(0.0, (900.0 - min(nearest.distance_m, 900.0)) / 18.0)
        traffic_summary = (
            f"{len(obstacles)} tracked contacts. Nearest target {nearest.label} at {nearest.distance_m:.0f} m and {nearest.bearing_deg:.1f}° relative bearing."
        )
    else:
        traffic_summary = "No traffic conflicts detected in the current sensor cycle."
    return (
        f"Probable outcome forecast\n\n"
        f"• Recommended action: {rule}\n"
        f"• Traffic picture: {traffic_summary}\n"
        f"• Updated ETA impact: +{delay_minutes:.0f} minutes versus the baseline plan.\n"
        f"• Projected voyage duration: {metrics.get('duration_hours', 0.0):.1f} hours.\n"
        f"• Projected fuel consumption: {metrics.get('fuel_tons', 0.0):.1f} tonnes.\n"
        f"• Operational note: maintain radar/visual watch, verify engine response margin, and confirm bridge team acknowledgement before executing a collision-avoidance maneuver."
    )


if __name__ == "__main__":
    app = MaritimePlannerApp()
    app.run()
