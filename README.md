# Cerea GIS Project

Streamlit app to import Cerea field data, edit track order and names, preview on map, and export shapefiles as zip.

## Local run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud deploy

1. Push this repository to GitHub.
2. In Streamlit Community Cloud, create a new app from the repo.
3. Set the main file path to `app.py`.
4. Keep dependencies in `requirements.txt`.

## Project structure

- `app.py`: Streamlit entrypoint and UI
- `requirements.txt`: Python dependencies
- `.streamlit/config.toml`: Streamlit config/theme
- `src/cerea_gis/contour.py`: contour parser
- `src/cerea_gis/patterns.py`: track/pattern parser
- `src/cerea_gis/universe.py`: universe center reader
- `src/cerea_gis/io_helpers.py`: import/export and filesystem helpers
- `src/cerea_gis/state_helpers.py`: Streamlit session state and field lifecycle
- `src/cerea_gis/ui_helpers.py`: map rendering and UI helper utilities

## Notes

- Input data is uploaded as zip in the UI. Runtime does not require bundled sample data.
- Export is generated in temporary folders and provided as zip download.
