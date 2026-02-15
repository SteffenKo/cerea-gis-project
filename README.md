# Cerea GIS Project

Dieses Projekt verarbeitet Cerea-Daten und exportiert sie als Shapefiles für GIS-Anwendungen.

## Installation

1. Installiere die Abhängigkeiten:
   ```
   pip install -r requirements.txt
   ```

## Verwendung

Führe die Streamlit-App aus:
```
streamlit run app.py
```

## Struktur

- `data/raw/`: Originale Cerea-Ordner
- `data/processed/`: Erzeugte GeoData
- `src/`: Quellcode
  - `parser.py`: Cerea Parser
  - `exporter.py`: Shapefile Export
  - `visualization.py`: Karten / Streamlit App
- `tests/`: Tests
- `app.py`: Streamlit Einstiegspunkt