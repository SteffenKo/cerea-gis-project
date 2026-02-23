import geopandas as gpd
import streamlit as st

from src.cerea_gis.contour import parse_contour
from src.cerea_gis.io_helpers import (
    export_field,
    get_exported_fields,
    get_farms,
    get_field_sources,
    get_fields,
    get_missing_shapefile_sidecars,
)
from src.cerea_gis.patterns import parse_patterns


@st.cache_data
def load_field_data(contour_file, patterns_file, center_x, center_y):
    polygon = None
    if contour_file.exists():
        polygon = parse_contour(contour_file, center_x, center_y)

    line_items = []
    if patterns_file.exists():
        raw_lines = parse_patterns(patterns_file, center_x, center_y)
        line_items = [
            {"id": idx, "name": name, "geometry": geom}
            for idx, (name, geom) in enumerate(raw_lines)
        ]

    return polygon, line_items


@st.cache_data
def load_field_data_from_shapefiles(contour_shp, patterns_shp):
    polygon = None
    contour_usable = contour_shp.exists() and not get_missing_shapefile_sidecars(contour_shp)
    if contour_usable:
        gdf_contour = gpd.read_file(contour_shp)
        if not gdf_contour.empty:
            if gdf_contour.crs is None:
                gdf_contour = gdf_contour.set_crs(epsg=4326)
            gdf_contour = gdf_contour.to_crs(epsg=25832)
            polygon = gdf_contour.geometry.unary_union

    line_items = []
    patterns_usable = patterns_shp.exists() and not get_missing_shapefile_sidecars(
        patterns_shp
    )
    if patterns_usable:
        gdf_lines = gpd.read_file(patterns_shp)
        if not gdf_lines.empty:
            if gdf_lines.crs is None:
                gdf_lines = gdf_lines.set_crs(epsg=4326)
            gdf_lines = gdf_lines.to_crs(epsg=25832)

            has_name_col = "name" in gdf_lines.columns
            for idx, row in gdf_lines.reset_index(drop=True).iterrows():
                name = f"Track {idx + 1}"
                if has_name_col and row["name"] is not None and str(row["name"]).strip():
                    name = str(row["name"])
                line_items.append({"id": idx, "name": name, "geometry": row.geometry})

    return polygon, line_items


def field_key(import_mode: str, farm_name: str, field_name: str):
    return f"{import_mode}::{farm_name}::{field_name}"


def parse_field_key(key: str):
    parts = key.split("::", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        # Backward compatibility for keys created before import modes existed.
        return "Cerea txt", parts[0], parts[1]
    raise ValueError(f"Invalid field key format: {key}")


def get_track_input_versions():
    if "track_input_versions" not in st.session_state:
        st.session_state.track_input_versions = {}
    return st.session_state.track_input_versions


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


def ensure_field_state(
    key, import_mode, contour_source, patterns_source, center_x=None, center_y=None
):
    if "field_edits" not in st.session_state:
        st.session_state.field_edits = {}

    if key not in st.session_state.field_edits:
        if import_mode == "Cerea txt":
            polygon, line_items = load_field_data(
                contour_source, patterns_source, center_x, center_y
            )
        else:
            polygon, line_items = load_field_data_from_shapefiles(
                contour_source, patterns_source
            )
        st.session_state.field_edits[key] = {
            "polygon": polygon,
            "line_items": line_items,
            "dirty": False,
        }

    return st.session_state.field_edits[key]


def reset_field_state(
    key, import_mode, contour_source, patterns_source, center_x=None, center_y=None
):
    if import_mode == "Cerea txt":
        polygon, line_items = load_field_data(
            contour_source, patterns_source, center_x, center_y
        )
    else:
        polygon, line_items = load_field_data_from_shapefiles(
            contour_source, patterns_source
        )
    st.session_state.field_edits[key] = {
        "polygon": polygon,
        "line_items": line_items,
        "dirty": False,
    }


def reset_all_field_states(import_mode, root_path, center_x=None, center_y=None):
    if "field_edits" not in st.session_state:
        st.session_state.field_edits = {}
        return 0

    reset_count = 0
    for key in list(st.session_state.field_edits.keys()):
        key_mode, farm_name, field_name = parse_field_key(key)
        if key_mode != import_mode:
            continue

        contour_source, patterns_source = get_field_sources(
            import_mode, root_path, farm_name, field_name
        )
        source_exists = contour_source.exists() or patterns_source.exists()
        if source_exists:
            reset_field_state(
                key, import_mode, contour_source, patterns_source, center_x, center_y
            )
            reset_count += 1

    return reset_count


def export_all_fields(import_mode, root_path, output_root, center_x=None, center_y=None):
    exported_count = 0
    for farm_dir in get_farms(root_path):
        if import_mode == "Cerea txt":
            field_names = [field_dir.name for field_dir in get_fields(farm_dir)]
        else:
            field_names = get_exported_fields(farm_dir)

        for field_name in field_names:
            contour_source, patterns_source = get_field_sources(
                import_mode, root_path, farm_dir.name, field_name
            )
            source_exists = contour_source.exists() or patterns_source.exists()
            if not source_exists:
                continue

            key = field_key(import_mode, farm_dir.name, field_name)

            if "field_edits" in st.session_state and key in st.session_state.field_edits:
                state = st.session_state.field_edits[key]
                polygon = state["polygon"]
                line_items = state["line_items"]
            else:
                if import_mode == "Cerea txt":
                    polygon, line_items = load_field_data(
                        contour_source, patterns_source, center_x, center_y
                    )
                else:
                    polygon, line_items = load_field_data_from_shapefiles(
                        contour_source, patterns_source
                    )

            export_field(
                polygon,
                line_items,
                output_root,
                farm_dir.name,
                field_name,
            )

            if "field_edits" in st.session_state and key in st.session_state.field_edits:
                st.session_state.field_edits[key]["dirty"] = False

            exported_count += 1

    return exported_count
