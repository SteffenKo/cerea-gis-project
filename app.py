import folium
from streamlit_folium import st_folium
import streamlit as st
from pathlib import Path
import geopandas as gpd
from streamlit_sortables import sort_items

from src.cerea_gis.universe import read_center
from src.cerea_gis.contour import parse_contour
from src.cerea_gis.patterns import parse_patterns

st.set_page_config(layout="wide")
st.title("Cerea GIS Converter")

# -----------------------------
# Helper Functions
# -----------------------------

def get_farms(cerea_root: Path):
    return [d for d in cerea_root.iterdir() if d.is_dir()]


def get_fields(farm_path: Path):
    return [d for d in farm_path.iterdir() if d.is_dir()]


def export_field(
    polygon,
    ordered_line_items,
    output_dir: Path,
    farm_name: str,
    field_name: str
):
    """
    Export field + tracks as Shapefile in WGS84
    """

    target_dir = output_dir / farm_name / field_name
    target_dir.mkdir(parents=True, exist_ok=True)

    # -------------------
    # Polygon export
    # -------------------
    gdf_poly = gpd.GeoDataFrame(
        [{"geometry": polygon}],
        crs="EPSG:25832"
    )

    gdf_poly = gdf_poly.to_crs(epsg=4326)

    gdf_poly.to_file(target_dir / f"{field_name}_contour.shp")

    # -------------------
    # Reorder lines
    # -------------------
    gdf_lines = gpd.GeoDataFrame(
        [{"id": item["id"], "name": item["name"], "geometry": item["geometry"]} for item in ordered_line_items],
        crs="EPSG:25832"
    )

    gdf_lines = gdf_lines.to_crs(epsg=4326)

    gdf_lines.reset_index(drop=True, inplace=True)

    gdf_lines.to_file(target_dir / f"{field_name}_patterns.shp")

def create_map(polygon, ordered_line_items):
    """
    Create interactive Folium map with numbered tracks
    ordered_line_items = [{"id": int, "name": str, "geometry": geom}, ...] in user-defined order
    """

    gdf_poly = gpd.GeoDataFrame(
        [{"geometry": polygon}],
        crs="EPSG:25832"
    ).to_crs(epsg=4326)

    gdf_lines = gpd.GeoDataFrame(
        [{"order": i + 1, "id": item["id"], "name": item["name"], "geometry": item["geometry"]}
         for i, item in enumerate(ordered_line_items)],
        crs="EPSG:25832"
    ).to_crs(epsg=4326)

    center = gdf_poly.geometry.centroid.iloc[0]
    m = folium.Map(location=[center.y, center.x], zoom_start=16)

    # Feldpolygon
    folium.GeoJson(
        gdf_poly,
        name="Feld",
        style_function=lambda x: {
            "color": "green",
            "weight": 2,
            "fillOpacity": 0.2,
        },
    ).add_to(m)

    # Linien + Nummerierung
    for _, row in gdf_lines.iterrows():

        # Linie
        folium.GeoJson(
            row["geometry"],
            tooltip=f"{row['order']} – {row['name']}",
            style_function=lambda x: {
                "color": "blue",
                "weight": 3,
            },
        ).add_to(m)

        # Mittelpunkt der Linie
        midpoint = row["geometry"].interpolate(0.5, normalized=True)

        # Nummer als DivIcon
        folium.Marker(
            location=[midpoint.y, midpoint.x],
            icon=folium.DivIcon(
                html=f"""
                <div style="
                    font-size: 14px;
                    font-weight: bold;
                    color: black;
                    background-color: white;
                    border: 2px solid black;
                    border-radius: 12px;
                    text-align: center;
                    width: 24px;
                    height: 24px;
                    line-height: 20px;
                ">
                    {row['order']}
                </div>
                """
            )
        ).add_to(m)

    folium.LayerControl().add_to(m)

    return m


@st.cache_data
def load_field_data(contour_file, patterns_file, center_x, center_y):
    polygon = parse_contour(contour_file, center_x, center_y)

    line_items = []
    if patterns_file.exists():
        raw_lines = parse_patterns(patterns_file, center_x, center_y)
        line_items = [
            {"id": idx, "name": name, "geometry": geom}
            for idx, (name, geom) in enumerate(raw_lines)
        ]

    return polygon, line_items



# -----------------------------
# UI
# -----------------------------

col_a, col_b = st.columns(2)

with col_a:
    cerea_root_input = st.text_input(
        "Pfad zum Cerea Root Ordner",
        value=""
    )
    

with col_b:
    output_root_input = st.text_input(
        "Pfad zum Output Ordner",
        value=""
    )

if cerea_root_input and output_root_input:

    cerea_root = Path(cerea_root_input)
    output_root = Path(output_root_input)

    if not cerea_root.exists():
        st.error("Cerea Root existiert nicht.")
        st.stop()

    universe_path = cerea_root / "universe.txt"

    if not universe_path.exists():
        st.error("universe.txt nicht gefunden.")
        st.stop()

    center_x, center_y = read_center(universe_path)

    farms = get_farms(cerea_root)

    farm_names = [f.name for f in farms]

    selected_farm = st.selectbox("Betrieb auswählen", farm_names)

    farm_path = cerea_root / selected_farm

    fields = get_fields(farm_path)
    field_names = [f.name for f in fields]

    selected_field = st.selectbox("Feld auswählen", field_names)

    field_path = farm_path / selected_field

    contour_file = field_path / "contour.txt"
    patterns_file = field_path / "patterns.txt"

    if contour_file.exists():

        polygon, line_items = load_field_data(
            contour_file,
            patterns_file,
            center_x,
            center_y
        )


        # ---- MAP PREVIEW ----

        col1, col2 = st.columns(2)
        # Sortieurtung der Spuren per Drag & Drop
        with col1:
            st.subheader("Spuren-Reihenfolge")
            if line_items:
                sortable_labels = [f"[{item['id']}] {item['name']}" for item in line_items]
                ordered_labels = sort_items(sortable_labels, direction="vertical")
                item_by_id = {item["id"]: item for item in line_items}
                ordered_line_items = [
                    item_by_id[int(label.split("]", 1)[0][1:])]
                    for label in ordered_labels
                ]

            else:
                ordered_line_items = []
        
        # Kartenansicht mit nummerierten Spuren
        with col2:
            st.subheader("Kartenansicht")
            if line_items:
                folium_map = create_map(polygon, ordered_line_items)
                st_folium(folium_map, width=600, height=600)
            else:
                st.info("Keine patterns.txt gefunden.")

        if st.button("Exportieren für Cerea"):

            export_field(
                polygon,
                ordered_line_items,
                output_root,
                selected_farm,
                selected_field
            )

            st.success("Export erfolgreich abgeschlossen!")
