import folium
import geopandas as gpd
import streamlit as st
from pathlib import Path
from streamlit_folium import st_folium
from streamlit_sortables import sort_items

from src.cerea_gis.contour import parse_contour
from src.cerea_gis.patterns import parse_patterns
from src.cerea_gis.universe import read_center

st.set_page_config(layout="wide")
st.title("Cerea GIS Converter")


def get_farms(cerea_root: Path):
    return [d for d in cerea_root.iterdir() if d.is_dir()]


def get_fields(farm_path: Path):
    return [d for d in farm_path.iterdir() if d.is_dir()]


def export_field(
    polygon,
    ordered_line_items,
    output_dir: Path,
    farm_name: str,
    field_name: str,
):
    target_dir = output_dir / farm_name / field_name
    target_dir.mkdir(parents=True, exist_ok=True)

    gdf_poly = gpd.GeoDataFrame([{"geometry": polygon}], crs="EPSG:25832")
    gdf_poly = gdf_poly.to_crs(epsg=4326)
    gdf_poly.to_file(target_dir / f"{field_name}_contour.shp")

    gdf_lines = gpd.GeoDataFrame(
        [
            {"id": item["id"], "name": item["name"], "geometry": item["geometry"]}
            for item in ordered_line_items
        ],
        crs="EPSG:25832",
    )
    gdf_lines = gdf_lines.to_crs(epsg=4326)
    gdf_lines.reset_index(drop=True, inplace=True)
    gdf_lines.to_file(target_dir / f"{field_name}_patterns.shp")


def create_map(polygon, ordered_line_items):
    gdf_poly = gpd.GeoDataFrame([{"geometry": polygon}], crs="EPSG:25832").to_crs(
        epsg=4326
    )
    gdf_lines = gpd.GeoDataFrame(
        [
            {
                "order": i + 1,
                "id": item["id"],
                "name": item["name"],
                "geometry": item["geometry"],
            }
            for i, item in enumerate(ordered_line_items)
        ],
        crs="EPSG:25832",
    ).to_crs(epsg=4326)

    center = gdf_poly.geometry.centroid.iloc[0]
    m = folium.Map(location=[center.y, center.x], zoom_start=16)

    folium.GeoJson(
        gdf_poly,
        name="Field",
        style_function=lambda _: {
            "color": "green",
            "weight": 2,
            "fillOpacity": 0.2,
        },
    ).add_to(m)

    for _, row in gdf_lines.iterrows():
        folium.GeoJson(
            row["geometry"],
            tooltip=f"{row['order']} - {row['name']}",
            style_function=lambda _: {
                "color": "blue",
                "weight": 3,
            },
        ).add_to(m)

        midpoint = row["geometry"].interpolate(0.5, normalized=True)
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
            ),
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


def field_key(farm_name: str, field_name: str):
    return f"{farm_name}::{field_name}"


def parse_field_key(key: str):
    return key.split("::", 1)


def ensure_field_state(key, contour_file, patterns_file, center_x, center_y):
    if "field_edits" not in st.session_state:
        st.session_state.field_edits = {}

    if key not in st.session_state.field_edits:
        polygon, line_items = load_field_data(
            contour_file, patterns_file, center_x, center_y
        )
        st.session_state.field_edits[key] = {
            "polygon": polygon,
            "line_items": line_items,
            "dirty": False,
        }

    return st.session_state.field_edits[key]


def sort_label(item):
    return f"{item['id']}|{item['name']}"


def sort_id(label: str):
    return int(label.split("|", 1)[0])


col_a, col_b = st.columns(2)

with col_a:
    cerea_root_input = st.text_input("Path to Cerea root folder", value="")

with col_b:
    output_root_input = st.text_input("Path to output folder", value="")

if cerea_root_input and output_root_input:
    cerea_root = Path(cerea_root_input)
    output_root = Path(output_root_input)

    if not cerea_root.exists():
        st.error("Cerea root does not exist.")
        st.stop()

    universe_path = cerea_root / "universe.txt"
    if not universe_path.exists():
        st.error("universe.txt not found.")
        st.stop()

    center_x, center_y = read_center(universe_path)

    farms = get_farms(cerea_root)
    farm_names = [f.name for f in farms]
    if not farm_names:
        st.warning("No farms found in Cerea root.")
        st.stop()

    selected_farm = st.selectbox("Select farm", farm_names)
    farm_path = cerea_root / selected_farm

    fields = get_fields(farm_path)
    field_names = [f.name for f in fields]
    if not field_names:
        st.warning("No fields found in selected farm.")
        st.stop()

    selected_field = st.selectbox("Select field", field_names)
    field_path = farm_path / selected_field

    contour_file = field_path / "contour.txt"
    patterns_file = field_path / "patterns.txt"

    if not contour_file.exists():
        st.warning("contour.txt not found.")
        st.stop()

    current_key = field_key(selected_farm, selected_field)
    current_state = ensure_field_state(
        current_key, contour_file, patterns_file, center_x, center_y
    )
    polygon = current_state["polygon"]
    line_items = current_state["line_items"]

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Track order")
        if line_items:
            sortable_labels = [sort_label(item) for item in line_items]
            ordered_labels = sort_items(sortable_labels, direction="vertical")
            item_by_id = {item["id"]: item for item in line_items}
            ordered_line_items = [item_by_id[sort_id(label)] for label in ordered_labels]

            if [i["id"] for i in ordered_line_items] != [i["id"] for i in line_items]:
                current_state["line_items"] = ordered_line_items
                current_state["dirty"] = True
                line_items = ordered_line_items

        st.subheader("Edit track")
        if line_items:
            line_ids = [item["id"] for item in line_items]
            select_key = f"line_select_{current_key}"

            if (
                select_key in st.session_state
                and st.session_state[select_key] not in line_ids
            ):
                del st.session_state[select_key]

            selected_id = st.selectbox(
                "Select track",
                options=line_ids,
                format_func=lambda line_id: f"[{line_id}] {next(item['name'] for item in line_items if item['id'] == line_id)}",
                key=select_key,
            )

            rename_value = st.text_input(
                "New name",
                value="",
                key=f"rename_value_{current_key}",
            )

            if st.button("Rename track", key=f"rename_btn_{current_key}"):
                new_name = rename_value.strip()
                if not new_name:
                    st.warning("Please enter a non-empty name.")
                else:
                    current_state["line_items"] = [
                        {**item, "name": new_name}
                        if item["id"] == selected_id
                        else item
                        for item in line_items
                    ]
                    current_state["dirty"] = True
                    st.success("Track renamed.")

            if st.button("Delete track", key=f"delete_btn_{current_key}"):
                current_state["line_items"] = [
                    item for item in line_items if item["id"] != selected_id
                ]
                current_state["dirty"] = True
                st.success("Track deleted.")
        else:
            st.info("No tracks available for editing.")

    with col2:
        st.subheader("Map")
        if current_state["line_items"]:
            folium_map = create_map(polygon, current_state["line_items"])
            st_folium(folium_map, width=600, height=600)
        else:
            st.info("No patterns available for this field.")

    if st.button("Export current field"):
        export_field(
            polygon,
            current_state["line_items"],
            output_root,
            selected_farm,
            selected_field,
        )
        current_state["dirty"] = False
        st.success("Current field exported.")

    if st.button("Export all changes"):
        changed_keys = [
            key
            for key, state in st.session_state.field_edits.items()
            if state["dirty"]
        ]
        if not changed_keys:
            st.info("No changed fields to export.")
        else:
            for key in changed_keys:
                farm_name, field_name = parse_field_key(key)
                state = st.session_state.field_edits[key]
                export_field(
                    state["polygon"],
                    state["line_items"],
                    output_root,
                    farm_name,
                    field_name,
                )
                state["dirty"] = False

            st.success(f"Exported {len(changed_keys)} changed field(s).")
