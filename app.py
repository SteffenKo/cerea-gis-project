import folium
import geopandas as gpd
import streamlit as st
import hashlib
import io
import shutil
import tempfile
import zipfile
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
        margin-top: -0.75rem;
        margin-bottom: 0.0rem;
    }
    div[data-testid="stButton"] > button {
        padding-top: 0.21rem;
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


def get_exported_fields(farm_path: Path):
    patterns_dir = farm_path / "patterns"
    if not patterns_dir.exists():
        return []

    field_names = []
    for patterns_file in patterns_dir.glob("*_patterns.shp"):
        field_name = patterns_file.stem.removesuffix("_patterns")
        field_names.append(field_name)

    return sorted(field_names)


def prepare_uploaded_root(uploaded_zip):
    zip_bytes = uploaded_zip.getvalue()
    zip_hash = hashlib.sha256(zip_bytes).hexdigest()
    zip_sig = f"{uploaded_zip.name}:{uploaded_zip.size}:{zip_hash}"

    previous_sig = st.session_state.get("input_zip_sig")
    if previous_sig != zip_sig:
        previous_dir = st.session_state.get("input_extract_dir")
        if previous_dir:
            shutil.rmtree(previous_dir, ignore_errors=True)

        extract_dir = Path(tempfile.mkdtemp(prefix="cerea_input_"))
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(extract_dir)

        st.session_state.input_zip_sig = zip_sig
        st.session_state.input_extract_dir = str(extract_dir)
        st.session_state.field_edits = {}
        st.session_state.selected_field_by_farm = {}
        st.session_state.pop("reset_field_target", None)
        st.session_state.pop("reset_all_target", None)
        if "export_bundle" in st.session_state:
            del st.session_state["export_bundle"]
        clear_all_track_input_state()

    return Path(st.session_state.input_extract_dir)


def resolve_import_root(extract_dir: Path, import_mode: str):
    candidates = [extract_dir] + [d for d in extract_dir.iterdir() if d.is_dir()]

    if import_mode == "Cerea txt":
        for candidate in candidates:
            if (candidate / "universe.txt").exists():
                return candidate
    else:
        for candidate in candidates:
            farm_dirs = [d for d in candidate.iterdir() if d.is_dir()]
            for farm_dir in farm_dirs:
                if (farm_dir / "patterns").exists():
                    return candidate

    return extract_dir


def create_export_zip_bytes(export_root: Path):
    mem_file = io.BytesIO()
    with zipfile.ZipFile(mem_file, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in export_root.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(export_root)
                zf.write(file_path, arcname=str(rel_path))
    mem_file.seek(0)
    return mem_file.read()


def validate_import_structure(import_mode: str, root_path: Path):
    issues = []
    warnings = []
    stats = {"farms": 0, "fields": 0}

    farms = get_farms(root_path)
    stats["farms"] = len(farms)
    if not farms:
        issues.append("No farm folders found in import root.")
        return {"issues": issues, "warnings": warnings, "stats": stats}

    if import_mode == "Cerea txt":
        if not (root_path / "universe.txt").exists():
            issues.append("Missing required file: universe.txt")

        for farm_dir in farms:
            fields = get_fields(farm_dir)
            if not fields:
                warnings.append(f"No field folders in farm: {farm_dir.name}")
                continue
            for field_dir in fields:
                stats["fields"] += 1
                contour_file = field_dir / "contour.txt"
                patterns_file = field_dir / "patterns.txt"
                if not contour_file.exists():
                    issues.append(f"Missing contour.txt: {farm_dir.name}/{field_dir.name}")
                if not patterns_file.exists():
                    warnings.append(
                        f"Missing optional patterns.txt: {farm_dir.name}/{field_dir.name}"
                    )
    else:
        for farm_dir in farms:
            patterns_dir = farm_dir / "patterns"
            contours_dir = farm_dir / "contours"
            if not patterns_dir.exists():
                issues.append(f"Missing required patterns folder: {farm_dir.name}/patterns")
                continue

            field_names = get_exported_fields(farm_dir)
            if not field_names:
                issues.append(
                    f"No *_patterns.shp files found in: {farm_dir.name}/patterns"
                )
                continue

            for field_name in field_names:
                stats["fields"] += 1
                contour_shp = contours_dir / f"{field_name}_contour.shp"
                if not contour_shp.exists():
                    warnings.append(
                        f"Missing optional contour shapefile: {farm_dir.name}/contours/{field_name}_contour.shp"
                    )

    return {"issues": issues, "warnings": warnings, "stats": stats}


def safe_widget_suffix(value: str):
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)


if hasattr(st, "dialog"):
    @st.dialog("Rename track")
    def show_rename_dialog(field_state_key: str, track_id: int):
        state = st.session_state.get("field_edits", {}).get(field_state_key)
        if not state:
            st.warning("Field state not available.")
            if st.button("Close", use_container_width=True):
                st.session_state.pop("rename_target", None)
                st.rerun()
            return

        track = next(
            (item for item in state["line_items"] if item["id"] == track_id),
            None,
        )
        if not track:
            st.warning("Track not found.")
            if st.button("Close", use_container_width=True):
                st.session_state.pop("rename_target", None)
                st.rerun()
            return

        input_key = f"rename_dialog_{safe_widget_suffix(field_state_key)}_{track_id}"
        new_name = st.text_input("New name", value=track["name"], key=input_key)

        apply_col, cancel_col = st.columns(2)
        with apply_col:
            if st.button("Apply", use_container_width=True):
                cleaned_name = new_name.strip()
                if not cleaned_name:
                    st.warning("Please enter a non-empty name.")
                else:
                    state["line_items"] = [
                        {**item, "name": cleaned_name}
                        if item["id"] == track_id
                        else item
                        for item in state["line_items"]
                    ]
                    state["dirty"] = True
                    st.session_state.pop("rename_target", None)
                    st.rerun()
        with cancel_col:
            if st.button("Cancel", use_container_width=True):
                st.session_state.pop("rename_target", None)
                st.rerun()

    @st.dialog("Confirm field reset")
    def show_reset_field_dialog(
        field_state_key: str,
        import_mode: str,
        contour_source: str,
        patterns_source: str,
        center_x,
        center_y,
    ):
        st.warning("Do you really want to reset changes for this field?")
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            if st.button("Reset field", use_container_width=True):
                reset_field_state(
                    field_state_key,
                    import_mode,
                    Path(contour_source),
                    Path(patterns_source),
                    center_x,
                    center_y,
                )
                clear_track_input_state(field_state_key)
                st.session_state.pop("reset_field_target", None)
                st.success("Field changes reset to imported data.")
                st.rerun()
        with cancel_col:
            if st.button("Cancel", use_container_width=True):
                st.session_state.pop("reset_field_target", None)
                st.rerun()

    @st.dialog("Confirm reset all")
    def show_reset_all_dialog(import_mode: str, root_path: str, center_x, center_y):
        st.warning("Do you really want to reset changes for all fields?")
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            if st.button("Reset all", use_container_width=True):
                reset_count = reset_all_field_states(
                    import_mode, Path(root_path), center_x, center_y
                )
                clear_all_track_input_state()
                st.session_state.pop("reset_all_target", None)
                if reset_count:
                    st.success(f"Reset all changes in {reset_count} field(s).")
                else:
                    st.info("No field state to reset.")
                st.rerun()
        with cancel_col:
            if st.button("Cancel", use_container_width=True):
                st.session_state.pop("reset_all_target", None)
                st.rerun()


def export_field(
    polygon,
    ordered_line_items,
    output_dir: Path,
    farm_name: str,
    field_name: str,
):
    farm_dir = output_dir / farm_name
    contours_dir = farm_dir / "contours"
    patterns_dir = farm_dir / "patterns"
    contours_dir.mkdir(parents=True, exist_ok=True)
    patterns_dir.mkdir(parents=True, exist_ok=True)

    if polygon is not None:
        gdf_poly = gpd.GeoDataFrame([{"geometry": polygon}], crs="EPSG:25832")
        gdf_poly = gdf_poly.to_crs(epsg=4326)
        gdf_poly.to_file(contours_dir / f"{field_name}_contour.shp")

    gdf_lines = gpd.GeoDataFrame(
        [
            {"id": item["id"], "name": item["name"], "geometry": item["geometry"]}
            for item in ordered_line_items
        ],
        crs="EPSG:25832",
    )
    gdf_lines = gdf_lines.to_crs(epsg=4326)
    gdf_lines.reset_index(drop=True, inplace=True)
    gdf_lines.to_file(patterns_dir / f"{field_name}_patterns.shp")


def create_map(polygon, ordered_line_items):
    gdf_poly = None
    if polygon is not None:
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

    if gdf_poly is not None:
        center = gdf_poly.geometry.centroid.iloc[0]
    else:
        center = gdf_lines.geometry.unary_union.centroid
    m = folium.Map(location=[center.y, center.x], zoom_start=16)

    if gdf_poly is not None:
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


@st.cache_data
def load_field_data_from_shapefiles(contour_shp, patterns_shp):
    if not patterns_shp.exists():
        raise ValueError(f"Patterns shapefile not found: {patterns_shp}")

    polygon = None
    if contour_shp.exists():
        gdf_contour = gpd.read_file(contour_shp)
        if not gdf_contour.empty:
            if gdf_contour.crs is None:
                gdf_contour = gdf_contour.set_crs(epsg=4326)
            gdf_contour = gdf_contour.to_crs(epsg=25832)
            polygon = gdf_contour.geometry.unary_union

    line_items = []
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


def get_field_sources(import_mode, root_path, farm_name, field_name):
    if import_mode == "Cerea txt":
        field_path = root_path / farm_name / field_name
        contour_source = field_path / "contour.txt"
        patterns_source = field_path / "patterns.txt"
    else:
        farm_path = root_path / farm_name
        contour_source = farm_path / "contours" / f"{field_name}_contour.shp"
        patterns_source = farm_path / "patterns" / f"{field_name}_patterns.shp"
    return contour_source, patterns_source


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
        source_exists = contour_source.exists() if import_mode == "Cerea txt" else patterns_source.exists()
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
            required_source = contour_source if import_mode == "Cerea txt" else patterns_source
            if not required_source.exists():
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


mode_col, input_col, check_col = st.columns([1, 2, 2])

with mode_col:
    import_mode = st.selectbox("Import mode", ["Cerea txt", "Exported shp"])

with input_col:
    uploaded_input_zip = st.file_uploader(
        "Import data zip",
        type=["zip"],
        accept_multiple_files=False,
    )

with check_col:
    st.caption("Input structure check appears after upload.")

st.divider()

if uploaded_input_zip is not None:
    extracted_root = prepare_uploaded_root(uploaded_input_zip)
    cerea_root = resolve_import_root(extracted_root, import_mode)

    validation = validate_import_structure(import_mode, cerea_root)
    stats = validation["stats"]
    with check_col:
        with st.expander("Input structure check", expanded=False):
            st.write(f"Root: `{cerea_root}`")
            st.write(f"Farms found: `{stats['farms']}`")
            st.write(f"Fields found: `{stats['fields']}`")
            if validation["issues"]:
                st.error("Blocking issues found:")
                for issue in validation["issues"]:
                    st.write(f"- {issue}")
            else:
                st.success("Required structure looks valid.")
            if validation["warnings"]:
                st.warning("Optional items missing:")
                for warn in validation["warnings"]:
                    st.write(f"- {warn}")

    if validation["issues"]:
        st.stop()

    center_x = None
    center_y = None
    if import_mode == "Cerea txt":
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

    field_panel_col, editor_col = st.columns([1, 3])

    with field_panel_col:
        st.subheader("Farm")
        selected_farm = st.selectbox("Farm", farm_names, label_visibility="collapsed")
        farm_path = cerea_root / selected_farm
        st.divider()

    if import_mode == "Cerea txt":
        fields = get_fields(farm_path)
        field_names = [f.name for f in fields]
    else:
        field_names = get_exported_fields(farm_path)
    if not field_names:
        st.warning("No fields found in selected farm.")
        st.stop()

    if "selected_field_by_farm" not in st.session_state:
        st.session_state.selected_field_by_farm = {}
    farm_session_key = f"{import_mode}::{selected_farm}"

    if (
        farm_session_key not in st.session_state.selected_field_by_farm
        or st.session_state.selected_field_by_farm[farm_session_key] not in field_names
    ):
        st.session_state.selected_field_by_farm[farm_session_key] = field_names[0]

    with field_panel_col:
        st.subheader("Fields")
        st.caption("Edited fields are highlighted in light green.")

        selected_field = st.session_state.selected_field_by_farm[farm_session_key]
        highlighted_button_keys = []
        for field_name in field_names:
            key = field_key(import_mode, selected_farm, field_name)
            is_dirty = (
                "field_edits" in st.session_state
                and key in st.session_state.field_edits
                and st.session_state.field_edits[key]["dirty"]
            )
            btn_key_suffix = safe_widget_suffix(
                f"{import_mode}_{selected_farm}_{field_name}"
            )
            btn_key = f"field_btn_{btn_key_suffix}"
            is_selected = field_name == selected_field

            if is_dirty and not is_selected:
                highlighted_button_keys.append(btn_key)

            if st.button(
                field_name,
                key=btn_key,
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            ):
                st.session_state.selected_field_by_farm[farm_session_key] = field_name
                selected_field = field_name

        if highlighted_button_keys:
            style_rules = []
            for btn_key in highlighted_button_keys:
                style_rules.append(
                    f"""
                    div.st-key-{btn_key} button {{
                        background-color: #D6F2CE !important;
                        color: #1f1f1f !important;
                        border-color: #D6F2CE !important;
                    }}
                    div.st-key-{btn_key} button:hover {{
                        background-color: #D6F2CE !important;
                        border-color: #D6F2CE !important;
                    }}
                    """
                )
            st.markdown(
                f"<style>{''.join(style_rules)}</style>",
                unsafe_allow_html=True,
            )

    contour_file, patterns_file = get_field_sources(
        import_mode, cerea_root, selected_farm, selected_field
    )
    current_key = field_key(import_mode, selected_farm, selected_field)

    with field_panel_col:
        st.divider()
        if st.button("Reset field changes", use_container_width=True):
            if hasattr(st, "dialog"):
                st.session_state["reset_field_target"] = {
                    "field_key": current_key,
                    "import_mode": import_mode,
                    "contour_source": str(contour_file),
                    "patterns_source": str(patterns_file),
                    "center_x": center_x,
                    "center_y": center_y,
                }
                st.rerun()
            else:
                reset_field_state(
                    current_key,
                    import_mode,
                    contour_file,
                    patterns_file,
                    center_x,
                    center_y,
                )
                clear_track_input_state(current_key)
                st.success("Field changes reset to imported data.")
                st.rerun()

        if st.button("Reset all changes", use_container_width=True):
            if hasattr(st, "dialog"):
                st.session_state["reset_all_target"] = {
                    "import_mode": import_mode,
                    "root_path": str(cerea_root),
                    "center_x": center_x,
                    "center_y": center_y,
                }
                st.rerun()
            else:
                reset_count = reset_all_field_states(
                    import_mode, cerea_root, center_x, center_y
                )
                clear_all_track_input_state()
                if reset_count:
                    st.success(f"Reset all changes in {reset_count} field(s).")
                else:
                    st.info("No field state to reset.")
                st.rerun()

    if hasattr(st, "dialog"):
        reset_field_target = st.session_state.get("reset_field_target")
        if reset_field_target:
            show_reset_field_dialog(
                reset_field_target["field_key"],
                reset_field_target["import_mode"],
                reset_field_target["contour_source"],
                reset_field_target["patterns_source"],
                reset_field_target["center_x"],
                reset_field_target["center_y"],
            )

        reset_all_target = st.session_state.get("reset_all_target")
        if reset_all_target:
            show_reset_all_dialog(
                reset_all_target["import_mode"],
                reset_all_target["root_path"],
                reset_all_target["center_x"],
                reset_all_target["center_y"],
            )

    with editor_col:
        source_ok = contour_file.exists() if import_mode == "Cerea txt" else patterns_file.exists()
        if not source_ok:
            missing_msg = "contour.txt not found."
            if import_mode == "Exported shp":
                missing_msg = f"Patterns shapefile not found: {patterns_file.name}"
            st.warning(missing_msg)
            st.stop()

        current_state = ensure_field_state(
            current_key,
            import_mode,
            contour_file,
            patterns_file,
            center_x,
            center_y,
        )
        polygon = current_state["polygon"]
        line_items = current_state["line_items"]

        st.subheader(f"Field: {selected_field}")
        if not line_items:
            st.info("No tracks available for editing.")
        else:
            # streamlit_sortables frontend metrics (v0.3.1):
            # container padding: 10px, body padding: 3px, item margin: 5px,
            # item inner height: ~32px
            sortable_container_padding_px = 10
            sortable_body_padding_px = 3
            sortable_item_margin_px = 5
            row_height_px = 32
            row_stride_px = row_height_px + (2 * sortable_item_margin_px)
            number_font_px = 16
            list_block_height = int(
                sortable_container_padding_px
                + (2 * sortable_body_padding_px)
                + (row_stride_px * len(line_items))
            )
            map_height = max(430, min(900, int(list_block_height + 170)))

            deleted_track_id = None
            original_line_items = list(line_items)
            ordered_line_items = list(line_items)
            current_key_safe = safe_widget_suffix(current_key)
            controls_row_key = f"track_controls_row_{current_key_safe}"
            dnd_col_key = f"track_dnd_col_{current_key_safe}"
            map_col_key = f"track_map_col_{current_key_safe}"

            controls_row = st.container(horizontal=True, gap=None, key=controls_row_key)
            with controls_row:
                num_col = st.container(width=40)
                del_col = st.container(width=40)
                rename_col = st.container(width=40)
                dnd_col = st.container(width="stretch", key=dnd_col_key)
                map_col = st.container(width="stretch", key=map_col_key)

            st.markdown(
                f"""
                <style>
                div.st-key-{controls_row_key} [data-testid="stHorizontalBlock"] {{
                    width: 100% !important;
                    flex-wrap: nowrap !important;
                    align-items: flex-start !important;
                }}
                div.st-key-{controls_row_key} [data-testid="stHorizontalBlock"] > div:nth-last-child(2),
                div.st-key-{controls_row_key} [data-testid="stHorizontalBlock"] > div:last-child {{
                    flex: 1 1 0 !important;
                    min-width: 0 !important;
                    max-width: none !important;
                }}
                div.st-key-{map_col_key} [data-testid="stCustomComponentV1"],
                div.st-key-{map_col_key} iframe {{
                    width: 100% !important;
                    max-width: 100% !important;
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )

            with dnd_col:
                st.markdown(
                    '<div style="font-size:0.78rem;font-weight:600;white-space:nowrap;">Order</div>',
                    unsafe_allow_html=True,
                )
                sortable_names = [item["name"] for item in line_items]
                ordered_names = sort_items(
                    sortable_names,
                    direction="vertical",
                    custom_style="""
                    .sortable-component.vertical {
                        width: 100%;
                    }
                    .sortable-component.vertical .sortable-container {
                        width: 100%;
                        min-width: 0;
                    }
                    .sortable-component.vertical .sortable-container-body {
                        width: 100%;
                        box-sizing: border-box;
                    }
                    """,
                )

                name_buckets = {}
                for item in line_items:
                    name_buckets.setdefault(item["name"], []).append(item)

                resolved_items = []
                for name in ordered_names:
                    bucket = name_buckets.get(name, [])
                    if bucket:
                        resolved_items.append(bucket.pop(0))

                if len(resolved_items) == len(line_items):
                    ordered_line_items = resolved_items

            display_items = ordered_line_items
            folium_map = create_map(polygon, display_items) if display_items else None

            style_rules = []
            for item in display_items:
                delete_btn_key = f"delete_track_{current_key_safe}_{item['id']}"
                rename_btn_key = f"rename_open_{current_key_safe}_{item['id']}"
                style_rules.append(
                    f"""
                    div.st-key-{delete_btn_key},
                    div.st-key-{rename_btn_key} {{
                        margin: 0 0 -11px 0 !important;
                        padding: 0 !important;
                    }}
                    div.st-key-{delete_btn_key} div[data-testid="stButton"],
                    div.st-key-{rename_btn_key} div[data-testid="stButton"] {{
                        margin: 0 !important;
                        padding: 0 !important;
                    }}
                    div.st-key-{delete_btn_key} button,
                    div.st-key-{rename_btn_key} button {{
                        height: {row_height_px}px !important;
                        min-height: {row_height_px}px !important;
                        width: {row_height_px}px !important;
                        min-width: {row_height_px}px !important;
                        max-width: {row_height_px}px !important;
                        margin: 0 !important;
                        padding: 0 !important;
                    }}
                    div.st-key-{delete_btn_key} button {{
                        margin-left: auto !important;
                        margin-right: auto !important;
                        display: block !important;
                    }}
                    div.st-key-{rename_btn_key} button {{
                        margin-left: auto !important;
                        margin-right: auto !important;
                        display: block !important;
                    }}
                    """
                )
            if style_rules:
                st.markdown(f"<style>{''.join(style_rules)}</style>", unsafe_allow_html=True)

            with num_col:
                st.markdown(
                    '<div style="font-size:0.78rem;font-weight:600;white-space:nowrap;">#</div>',
                    unsafe_allow_html=True,
                )
                number_rows = "".join(
                        [
                        (
                            f'<div style="height:{row_height_px}px;width:{row_height_px}px;margin:{sortable_item_margin_px}px auto;display:flex;align-items:center;'
                            f"justify-content:center;font-weight:600;font-size:{number_font_px}px;border:1px solid #e8e8e8;"
                            f'box-sizing:border-box;">{idx}</div>'
                        )
                        for idx in range(1, len(display_items) + 1)
                    ]
                )
                st.markdown(
                    (
                        f' <div style="margin-top:{sortable_container_padding_px}px;padding:{sortable_body_padding_px}px;'
                        'border-radius:3px;overflow:hidden;background:var(--secondary-background-color);">'
                        f"{number_rows}</div>"
                    ),
                    unsafe_allow_html=True,
                )

            with del_col:
                st.markdown(
                    '<div style="font-size:0.78rem;font-weight:600;white-space:nowrap;">Delete</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="height:{sortable_container_padding_px + sortable_body_padding_px + 5}px;"></div>',
                    unsafe_allow_html=True,
                )
                for item in display_items:
                    delete_btn_key = f"delete_track_{current_key_safe}_{item['id']}"
                    if st.button(
                        "x",
                        key=delete_btn_key,
                        use_container_width=True,
                    ):
                        deleted_track_id = item["id"]

            with rename_col:
                st.markdown(
                    '<div style="font-size:0.78rem;font-weight:600;white-space:nowrap;">Edit</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="height:{sortable_container_padding_px + sortable_body_padding_px + 6}px;"></div>',
                    unsafe_allow_html=True,
                )
                for item in display_items:
                    rename_btn_key = f"rename_open_{current_key_safe}_{item['id']}"
                    if st.button(
                        "✎",
                        key=rename_btn_key,
                        use_container_width=True,
                    ):
                        st.session_state["rename_target"] = {
                            "field_key": current_key,
                            "track_id": item["id"],
                        }

            with map_col:
                st.markdown(
                    '<div style="font-size:0.78rem;font-weight:600;white-space:nowrap;">Map</div>',
                    unsafe_allow_html=True,
                )
                if folium_map is not None:
                    st_folium(
                        folium_map,
                        key=f"track_map_{current_key_safe}",
                        height=map_height,
                        use_container_width=True,
                    )

            if deleted_track_id is not None:
                current_state["line_items"] = [
                    item for item in display_items if item["id"] != deleted_track_id
                ]
                current_state["dirty"] = True
                line_items = current_state["line_items"]
                clear_track_input_state(current_key)
                st.success("Track deleted.")
            else:
                if [i["id"] for i in display_items] != [i["id"] for i in original_line_items]:
                    current_state["line_items"] = display_items
                    current_state["dirty"] = True
                    line_items = current_state["line_items"]

            rename_target = st.session_state.get("rename_target")
            if (
                rename_target
                and rename_target.get("field_key") == current_key
                and hasattr(st, "dialog")
            ):
                show_rename_dialog(current_key, int(rename_target["track_id"]))

        export_col_1, export_col_2, export_col_3 = st.columns(3)

        with export_col_1:
            if st.button("Prepare current field export", use_container_width=True):
                export_root = Path(tempfile.mkdtemp(prefix="cerea_export_"))
                export_field(
                    polygon,
                    current_state["line_items"],
                    export_root,
                    selected_farm,
                    selected_field,
                )
                zip_bytes = create_export_zip_bytes(export_root)
                shutil.rmtree(export_root, ignore_errors=True)
                st.session_state.export_bundle = {
                    "bytes": zip_bytes,
                    "label": "current field",
                }
                current_state["dirty"] = False
                st.success("Current field export prepared.")

        with export_col_2:
            if st.button("Prepare all fields export", use_container_width=True):
                export_root = Path(tempfile.mkdtemp(prefix="cerea_export_"))
                exported_count = export_all_fields(
                    import_mode, cerea_root, export_root, center_x, center_y
                )
                zip_bytes = create_export_zip_bytes(export_root)
                shutil.rmtree(export_root, ignore_errors=True)
                st.session_state.export_bundle = {
                    "bytes": zip_bytes,
                    "label": "all fields",
                }
                st.success(f"Prepared export for {exported_count} field(s).")

        with export_col_3:
            if st.button("Prepare all changes export", use_container_width=True):
                changed_keys = [
                    key
                    for key, state in st.session_state.field_edits.items()
                    if state["dirty"]
                ]
                if not changed_keys:
                    st.info("No changed fields to export.")
                else:
                    export_root = Path(tempfile.mkdtemp(prefix="cerea_export_"))
                    exported_changes = 0
                    for key in changed_keys:
                        key_mode, farm_name, field_name = parse_field_key(key)
                        if key_mode != import_mode:
                            continue
                        state = st.session_state.field_edits[key]
                        export_field(
                            state["polygon"],
                            state["line_items"],
                            export_root,
                            farm_name,
                            field_name,
                        )
                        state["dirty"] = False
                        exported_changes += 1

                    if exported_changes:
                        zip_bytes = create_export_zip_bytes(export_root)
                        shutil.rmtree(export_root, ignore_errors=True)
                        st.session_state.export_bundle = {
                            "bytes": zip_bytes,
                            "label": "all changes",
                        }
                        st.success(f"Prepared export for {exported_changes} changed field(s).")
                    else:
                        shutil.rmtree(export_root, ignore_errors=True)
                        st.info("No changed fields for current import mode.")

        bundle = st.session_state.get("export_bundle")
        if bundle:
            st.caption(
                "Edit the export zip name below. Press Enter to apply the name for download/export."
            )
            download_col, name_col = st.columns([2, 1])
            with download_col:
                export_zip_name = st.text_input(
                    "Export zip name",
                    value=st.session_state.get("export_zip_name", "cerea_export.zip"),
                    key="export_zip_name",
                    label_visibility="collapsed",
                    placeholder="Export zip name",
                )
            with name_col:
                download_name = export_zip_name or "cerea_export.zip"
                if not download_name.lower().endswith(".zip"):
                    download_name = f"{download_name}.zip"
                st.download_button(
                    label=f"Download {bundle['label']} zip",
                    data=bundle["bytes"],
                    file_name=download_name,
                    mime="application/zip",
                    use_container_width=True,
                )
else:
    st.info("Upload a zip file to start.")
