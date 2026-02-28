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


def load_field_data(contour_file, patterns_file, center_x, center_y, return_report=False):
    polygon = None
    notes = []
    if contour_file.exists():
        try:
            polygon = parse_contour(contour_file, center_x, center_y)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            polygon = None
            notes.append(f"Unreadable contour source: {contour_file.name}")

    line_items = []
    if patterns_file.exists():
        try:
            raw_lines = parse_patterns(patterns_file, center_x, center_y)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            raw_lines = []
            notes.append(f"Unreadable patterns source: {patterns_file.name}")
        line_items = [
            {"id": idx, "name": name, "geometry": geom}
            for idx, (name, geom) in enumerate(raw_lines)
        ]

    if return_report:
        return polygon, line_items, notes
    return polygon, line_items


def load_field_data_from_shapefiles(contour_shp, patterns_shp, return_report=False):
    polygon = None
    notes = []
    contour_usable = contour_shp.exists() and not get_missing_shapefile_sidecars(contour_shp)
    if contour_usable:
        try:
            gdf_contour = gpd.read_file(contour_shp)
            if not gdf_contour.empty:
                if gdf_contour.crs is None:
                    gdf_contour = gdf_contour.set_crs(epsg=4326)
                gdf_contour = gdf_contour.to_crs(epsg=25832)
                polygon = gdf_contour.geometry.unary_union
        except (OSError, ValueError, TypeError):
            notes.append(f"Unreadable contour source: {contour_shp.name}")
    elif contour_shp.exists():
        missing = ", ".join(get_missing_shapefile_sidecars(contour_shp))
        notes.append(f"Contour sidecars missing ({contour_shp.name}): {missing}")

    line_items = []
    patterns_usable = patterns_shp.exists() and not get_missing_shapefile_sidecars(
        patterns_shp
    )
    if patterns_usable:
        try:
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
        except (OSError, ValueError, TypeError):
            notes.append(f"Unreadable patterns source: {patterns_shp.name}")
    elif patterns_shp.exists():
        missing = ", ".join(get_missing_shapefile_sidecars(patterns_shp))
        notes.append(f"Patterns sidecars missing ({patterns_shp.name}): {missing}")

    if return_report:
        return polygon, line_items, notes
    return polygon, line_items


def _get_field_edits():
    if "field_edits" not in st.session_state:
        st.session_state.field_edits = {}
    return st.session_state.field_edits


def _normalize_edit_state(raw_state):
    state = raw_state if isinstance(raw_state, dict) else {}
    # Drop legacy heavy keys if they are still present in an old session.
    state.pop("polygon", None)
    state.pop("line_items", None)

    order = state.get("order")
    if order is not None:
        normalized_order = []
        for track_id in order:
            try:
                normalized_order.append(int(track_id))
            except (TypeError, ValueError):
                continue
        state["order"] = normalized_order
    else:
        state["order"] = None

    renamed = state.get("renamed")
    if isinstance(renamed, dict):
        normalized_renamed = {}
        for track_id, name in renamed.items():
            try:
                normalized_renamed[int(track_id)] = str(name)
            except (TypeError, ValueError):
                continue
        state["renamed"] = normalized_renamed
    else:
        state["renamed"] = {}

    deleted_ids = state.get("deleted_ids")
    if isinstance(deleted_ids, (list, tuple, set)):
        normalized_deleted = []
        seen = set()
        for track_id in deleted_ids:
            try:
                track_id_int = int(track_id)
            except (TypeError, ValueError):
                continue
            if track_id_int not in seen:
                seen.add(track_id_int)
                normalized_deleted.append(track_id_int)
        state["deleted_ids"] = normalized_deleted
    else:
        state["deleted_ids"] = []

    state["dirty"] = bool(state.get("dirty", False))
    return state


def _empty_edit_state():
    return {"order": None, "renamed": {}, "deleted_ids": [], "dirty": False}


def _get_or_create_edit_state(key: str):
    field_edits = _get_field_edits()
    state = _normalize_edit_state(field_edits.get(key, {}))
    field_edits[key] = state
    return state


def _apply_line_item_edits(line_items, edit_state):
    if not line_items:
        return []

    deleted_ids = set(edit_state.get("deleted_ids", []))
    renamed = edit_state.get("renamed", {})
    requested_order = edit_state.get("order")

    items_by_id = {int(item["id"]): item for item in line_items}
    base_ids = [int(item["id"]) for item in line_items]

    ordered_ids = []
    seen = set()

    if requested_order:
        for track_id in requested_order:
            if track_id in seen:
                continue
            if track_id in items_by_id:
                ordered_ids.append(track_id)
                seen.add(track_id)

    for track_id in base_ids:
        if track_id in seen:
            continue
        ordered_ids.append(track_id)
        seen.add(track_id)

    edited_items = []
    for track_id in ordered_ids:
        if track_id in deleted_ids:
            continue
        item = items_by_id.get(track_id)
        if item is None:
            continue
        edited_items.append(
            {
                "id": track_id,
                "name": renamed.get(track_id, item["name"]),
                "geometry": item["geometry"],
            }
        )
    return edited_items


def delete_track_edit(key: str, track_id: int):
    state = _get_or_create_edit_state(key)
    track_id = int(track_id)

    if track_id in state["deleted_ids"]:
        return False

    state["deleted_ids"].append(track_id)
    state["renamed"].pop(track_id, None)
    if state["order"] is not None:
        state["order"] = [tid for tid in state["order"] if tid != track_id]
    state["dirty"] = True
    return True


def rename_track_edit(key: str, track_id: int, new_name: str):
    state = _get_or_create_edit_state(key)
    track_id = int(track_id)
    state["renamed"][track_id] = str(new_name)
    state["dirty"] = True


def set_track_order_edit(key: str, ordered_track_ids):
    state = _get_or_create_edit_state(key)
    normalized = []
    seen = set()
    for track_id in ordered_track_ids:
        try:
            track_id_int = int(track_id)
        except (TypeError, ValueError):
            continue
        if track_id_int in seen:
            continue
        seen.add(track_id_int)
        normalized.append(track_id_int)

    state["order"] = normalized
    state["dirty"] = True


def mark_field_edit_clean(key: str):
    field_edits = _get_field_edits()
    state = field_edits.get(key)
    if not isinstance(state, dict):
        return
    state["dirty"] = False


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
    if import_mode == "Cerea txt":
        polygon, line_items = load_field_data(
            contour_source, patterns_source, center_x, center_y
        )
    else:
        polygon, line_items = load_field_data_from_shapefiles(
            contour_source, patterns_source
        )

    field_edits = _get_field_edits()
    raw_state = field_edits.get(key)
    if isinstance(raw_state, dict):
        edit_state = _normalize_edit_state(raw_state)
        field_edits[key] = edit_state
    else:
        edit_state = _empty_edit_state()
    edited_line_items = _apply_line_item_edits(line_items, edit_state)
    return {
        "polygon": polygon,
        "line_items": edited_line_items,
        "dirty": edit_state.get("dirty", False),
    }


def reset_field_state(
    key, import_mode, contour_source, patterns_source, center_x=None, center_y=None
):
    if "field_edits" not in st.session_state:
        st.session_state.field_edits = {}
    st.session_state.field_edits.pop(key, None)


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
            st.session_state.field_edits.pop(key, None)
            reset_count += 1

    return reset_count


def export_all_fields(
    import_mode, root_path, output_root, center_x=None, center_y=None, with_report=False
):
    exported_count = 0
    report_lines = []
    for farm_dir in get_farms(root_path):
        if import_mode == "Cerea txt":
            field_names = [field_dir.name for field_dir in get_fields(farm_dir)]
        else:
            field_names = get_exported_fields(farm_dir)

        for field_name in field_names:
            contour_source, patterns_source = get_field_sources(
                import_mode, root_path, farm_dir.name, field_name
            )
            has_contour_source = contour_source.exists()
            has_patterns_source = patterns_source.exists()
            source_exists = has_contour_source or has_patterns_source
            field_label = f"{farm_dir.name}/{field_name}"
            if not source_exists:
                report_lines.append(f"- Skipped {field_label}: no source files found.")
                continue

            key = field_key(import_mode, farm_dir.name, field_name)
            field_notes = []
            if import_mode == "Cerea txt":
                polygon, line_items, field_notes = load_field_data(
                    contour_source,
                    patterns_source,
                    center_x,
                    center_y,
                    return_report=True,
                )
            else:
                polygon, line_items, field_notes = load_field_data_from_shapefiles(
                    contour_source,
                    patterns_source,
                    return_report=True,
                )

            if not has_contour_source or not has_patterns_source:
                missing_parts = []
                if not has_contour_source:
                    missing_parts.append("contour")
                if not has_patterns_source:
                    missing_parts.append("patterns")
                report_lines.append(
                    f"- Partial {field_label}: missing {' and '.join(missing_parts)} source file(s)."
                )

            for note in field_notes:
                report_lines.append(f"- Partial {field_label}: {note}")

            if "field_edits" in st.session_state and key in st.session_state.field_edits:
                edit_state = _normalize_edit_state(st.session_state.field_edits[key])
                st.session_state.field_edits[key] = edit_state
                line_items = _apply_line_item_edits(line_items, edit_state)

            if polygon is None and not line_items:
                report_lines.append(
                    f"- Skipped {field_label}: no usable contour or patterns data."
                )
                continue

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

    if with_report:
        return exported_count, report_lines
    return exported_count
