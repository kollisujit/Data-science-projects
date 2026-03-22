# Maritime Route Planner and Ship Environment Simulator

This repository now contains a standalone realtime maritime route-planning desktop application built with Python's standard-library GUI stack. The application combines end-to-end voyage planning with dynamic obstacle awareness, weather-aware performance estimation, COLREG-style decision support, radar simulation, and voyage logging.

## Key capabilities

- Accepts operator inputs for:
  - ship parameters,
  - port of departure and arrival,
  - cargo type and cargo load,
  - draft, beam, deadweight, fuel burn, and safety margin.
- Plans routes across a graph of major international ports.
- Estimates voyage duration, adjusted speed, route risk, and fuel consumption.
- Uses live marine weather when available via the Open-Meteo marine API, with a deterministic fallback when offline.
- Simulates realtime ship-environment contacts and supports dynamic route updates.
- Generates COLREG-oriented guidance for head-on, crossing, overtaking, and close-quarters situations.
- Visualizes the voyage on a route canvas, provides a radar display, and keeps a rolling monitoring log.
- Shows a right-side dialogue panel with probable outcomes and ETA/fuel implications of the current decision.

## Files

- `maritime_route_planner.py` – main application.
- `logs/navigation_log.csv` – generated at runtime after the realtime simulation starts.

## How to run

```bash
python maritime_route_planner.py
```

## Optional enhancements

If you install `opencv-python` and `ultralytics`, the `SensorFusionEngine` class is structured so the fallback sensor simulation can be replaced by actual video/object-detection ingestion based on the YOLO/OpenCV pipeline you supplied.
