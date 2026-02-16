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
st.markdown(
    """
    <style>
    div[data-testid="stButton"] {
        margin-top: 0.0rem;
        margin-bottom: 0.0rem;
    }
    div[data-testid="stButton"] > button {
        padding-top: 0.15rem;
        padding-bottom: 0.15rem;
        min-height: 1.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def get_track_input_versions():
    if "track_input_versions" not in st.session_state:
        st.session_state.track_input_versions = {}
    return st.session_state.track_input_versions


def get_track_input_version(key: str):
    versions = get_track_input_versions()
    return versions.get(key, 0)


def bump_track_input_version(key: str):
    versions = get_track_input_versions()
    versions[key] = versions.get(key, 0) + 1


def clear_track_input_state(key: str):
    prefix = f"track_name_{key}_"
    for session_key in list(st.session_state.keys()):
        if session_key.startswith(prefix):
            del st.session_state[session_key]
    bump_track_input_version(key)


def clear_all_track_input_state():
    prefix = "track_name_"
    for session_key in list(st.session_state.keys()):
        if session_key.startswith(prefix):
            del st.session_state[session_key]
    versions = get_track_input_versions()
    for key in list(versions.keys()):
        versions[key] = versions.get(key, 0) + 1


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


def reset_field_state(key, contour_file, patterns_file, center_x, center_y):
    polygon, line_items = load_field_data(contour_file, patterns_file, center_x, center_y)
    st.session_state.field_edits[key] = {
        "polygon": polygon,
        "line_items": line_items,
        "dirty": False,
    }


def reset_all_field_states(cerea_root, center_x, center_y):
    if "field_edits" not in st.session_state:
        st.session_state.field_edits = {}
        return 0

    reset_count = 0
    for key in list(st.session_state.field_edits.keys()):
        farm_name, field_name = parse_field_key(key)
        field_path = cerea_root / farm_name / field_name
        contour_file = field_path / "contour.txt"
        patterns_file = field_path / "patterns.txt"

        if contour_file.exists():
            reset_field_state(key, contour_file, patterns_file, center_x, center_y)
            reset_count += 1

    return reset_count


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

    if "selected_field_by_farm" not in st.session_state:
        st.session_state.selected_field_by_farm = {}

    if (
        selected_farm not in st.session_state.selected_field_by_farm
        or st.session_state.selected_field_by_farm[selected_farm] not in field_names
    ):
        st.session_state.selected_field_by_farm[selected_farm] = field_names[0]

    field_panel_col, editor_col = st.columns([1, 3])

    with field_panel_col:
        st.subheader("Fields")
        st.caption("Yellow dot = edited field")

        selected_field = st.session_state.selected_field_by_farm[selected_farm]
        for field_name in field_names:
            key = field_key(selected_farm, field_name)
            is_dirty = (
                "field_edits" in st.session_state
                and key in st.session_state.field_edits
                and st.session_state.field_edits[key]["dirty"]
            )
            dot_col, btn_col = st.columns([1, 8], gap="small")
            with dot_col:
                if is_dirty:
                    st.markdown(
                        '<div style="text-align:center;font-size:18px;color:#f9a825;line-height:28px;">&#9679;</div>',
                        unsafe_allow_html=True,
                    )
            with btn_col:
                if st.button(
                    field_name,
                    key=f"field_btn_{selected_farm}_{field_name}",
                    use_container_width=True,
                    type="primary" if field_name == selected_field else "secondary",
                ):
                    st.session_state.selected_field_by_farm[selected_farm] = field_name
                    selected_field = field_name

    with editor_col:
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

        st.subheader("Rename / Delete tracks")
        if line_items:
            current_input_version = get_track_input_version(current_key)
            updated_items = []
            has_rename_changes = False
            deleted_track_id = None

            for item in line_items:
                name_col, delete_col = st.columns([10, 1])
                with name_col:
                    new_name = st.text_input(
                        f"Track {item['id']}",
                        value=item["name"],
                        key=f"track_name_{current_key}_{current_input_version}_{item['id']}",
                        label_visibility="collapsed",
                    )
                with delete_col:
                    delete_clicked = st.button(
                        "x",
                        key=f"delete_track_{current_key}_{item['id']}",
                    )

                if delete_clicked:
                    deleted_track_id = item["id"]
                    continue

                cleaned_name = new_name.strip()
                if not cleaned_name:
                    cleaned_name = item["name"]
                if cleaned_name != item["name"]:
                    has_rename_changes = True
                updated_items.append({**item, "name": cleaned_name})

            if deleted_track_id is not None:
                current_state["line_items"] = updated_items
                current_state["dirty"] = True
                line_items = updated_items
                clear_track_input_state(current_key)
                st.success("Track deleted.")
            elif has_rename_changes:
                current_state["line_items"] = updated_items
                current_state["dirty"] = True
                line_items = updated_items
        else:
            st.info("No tracks available for editing.")

        reorder_col, map_col = st.columns(2)

        with reorder_col:
            st.subheader("Track order")
            if line_items:
                position_col, dnd_col = st.columns([1, 8])

                with position_col:
                    # Tune these values to match streamlit-sortables row spacing.
                    row_height_px = 36.33
                    top_offset_px = 17
                    number_font_px = 16
                    number_rows = "".join(
                        [
                            (
                                f'<div style="height:{row_height_px}px;display:flex;align-items:center;'
                                f"justify-content:center;font-weight:600;font-size:{number_font_px}px;border-bottom:1px solid #e8e8e8;"
                                f'box-sizing:border-box;">{idx}</div>'
                            )
                            for idx in range(1, len(line_items) + 1)
                        ]
                    )
                    st.markdown(
                        (
                            f'<div style="margin-top:{top_offset_px}px;border:1px solid #e8e8e8;'
                            'border-radius:6px;overflow:hidden;background:#ffffff;">'
                            f"{number_rows}</div>"
                        ),
                        unsafe_allow_html=True,
                    )

                with dnd_col:
                    sortable_names = [item["name"] for item in line_items]
                    ordered_names = sort_items(sortable_names, direction="vertical")

                name_buckets = {}
                for item in line_items:
                    name_buckets.setdefault(item["name"], []).append(item)

                ordered_line_items = []
                for name in ordered_names:
                    bucket = name_buckets.get(name, [])
                    if bucket:
                        ordered_line_items.append(bucket.pop(0))

                if len(ordered_line_items) == len(line_items):
                    if [i["id"] for i in ordered_line_items] != [i["id"] for i in line_items]:
                        current_state["line_items"] = ordered_line_items
                        current_state["dirty"] = True
                        line_items = ordered_line_items
            else:
                st.info("No tracks available for ordering.")

        with map_col:
            st.subheader("Map")
            if current_state["line_items"]:
                folium_map = create_map(polygon, current_state["line_items"])
                st_folium(folium_map, width=600, height=600)
            else:
                st.info("No patterns available for this field.")

        if st.button("Reset all changes"):
            reset_count = reset_all_field_states(cerea_root, center_x, center_y)
            clear_all_track_input_state()
            if reset_count:
                st.success(f"Reset all changes in {reset_count} field(s).")
            else:
                st.info("No field state to reset.")
            st.rerun()

        if st.button("Reset field changes"):
            reset_field_state(current_key, contour_file, patterns_file, center_x, center_y)
            clear_track_input_state(current_key)
            st.success("Field changes reset to imported data.")
            st.rerun()

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
