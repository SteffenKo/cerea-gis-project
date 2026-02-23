import hashlib
import io
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import streamlit as st
from streamlit_folium import st_folium
from streamlit_sortables import sort_items

from src.cerea_gis.io_helpers import (
    create_export_zip_bytes,
    export_field,
    get_exported_fields,
    get_farms,
    get_fields,
    get_missing_shapefile_sidecars,
    get_field_sources,
    resolve_import_root,
    resolve_universe_path,
    validate_import_structure,
)
from src.cerea_gis.state_helpers import (
    clear_all_track_input_state,
    clear_track_input_state,
    ensure_field_state,
    export_all_fields,
    field_key,
    parse_field_key,
    reset_all_field_states,
    reset_field_state,
)
from src.cerea_gis.ui_helpers import create_map, safe_widget_suffix
from src.cerea_gis.universe import read_center

st.set_page_config(layout="wide")
st.title("Cerea 300 GIS")

BACKUP_REMINDER_AFTER_SECONDS = 15 * 60
BACKUP_REMINDER_DIRTY_THRESHOLD = 5

if "show_intro_info" not in st.session_state:
    st.session_state.show_intro_info = True
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
        st.session_state.pop("last_full_backup_export_ts", None)
        st.session_state.pop("backup_reminder_last_field_key", None)
        st.session_state.pop("backup_reminder_last_shown_signature", None)
        st.session_state.pop("backup_reminder_visible_field_key", None)
        if "export_bundle" in st.session_state:
            del st.session_state["export_bundle"]
        clear_all_track_input_state()

    return Path(st.session_state.input_extract_dir)


def clear_uploaded_root_state():
    previous_dir = st.session_state.get("input_extract_dir")
    if previous_dir:
        shutil.rmtree(previous_dir, ignore_errors=True)

    st.session_state.pop("input_zip_sig", None)
    st.session_state.pop("input_extract_dir", None)
    st.session_state.field_edits = {}
    st.session_state.selected_field_by_farm = {}
    st.session_state.pop("reset_field_target", None)
    st.session_state.pop("reset_all_target", None)
    st.session_state.pop("last_full_backup_export_ts", None)
    st.session_state.pop("backup_reminder_last_field_key", None)
    st.session_state.pop("backup_reminder_last_shown_signature", None)
    st.session_state.pop("backup_reminder_visible_field_key", None)
    st.session_state.pop("export_bundle", None)
    clear_all_track_input_state()


def delete_track_from_field_state(field_state_key: str, track_id: int):
    field_edits = st.session_state.get("field_edits", {})
    state = field_edits.get(field_state_key)
    if not state:
        return

    original_len = len(state.get("line_items", []))
    state["line_items"] = [
        item for item in state.get("line_items", []) if item.get("id") != track_id
    ]
    if len(state["line_items"]) == original_len:
        return

    state["dirty"] = True
    clear_track_input_state(field_state_key)
    st.session_state["track_delete_notice"] = "Track deleted."


def build_field_export_report_lines(
    import_mode: str,
    farm_name: str,
    field_name: str,
    contour_source: Path,
    patterns_source: Path,
    state: dict | None = None,
):
    lines = []
    field_label = f"{farm_name}/{field_name}"

    has_contour_source = contour_source.exists()
    has_patterns_source = patterns_source.exists()

    if not has_contour_source and not has_patterns_source:
        lines.append(f"- Partial {field_label}: no source files found.")
    else:
        missing_parts = []
        if not has_contour_source:
            missing_parts.append("contour")
        if not has_patterns_source:
            missing_parts.append("patterns")
        if missing_parts:
            lines.append(
                f"- Partial {field_label}: missing {' and '.join(missing_parts)} source file(s)."
            )

    if import_mode == "Exported shp":
        if has_patterns_source:
            missing_patterns_sidecars = get_missing_shapefile_sidecars(patterns_source)
            if missing_patterns_sidecars:
                sidecars_text = ", ".join(missing_patterns_sidecars)
                lines.append(
                    f"- Partial {field_label}: patterns sidecar file(s) missing ({patterns_source.name}): {sidecars_text}"
                )
        if has_contour_source:
            missing_contour_sidecars = get_missing_shapefile_sidecars(contour_source)
            if missing_contour_sidecars:
                sidecars_text = ", ".join(missing_contour_sidecars)
                lines.append(
                    f"- Partial {field_label}: contour sidecar file(s) missing ({contour_source.name}): {sidecars_text}"
                )

    if state is not None and state.get("polygon") is None and not state.get("line_items", []):
        lines.append(
            f"- Partial {field_label}: current field state has no contour geometry and no tracks."
        )

    return lines


def get_dirty_field_count_for_mode(import_mode: str):
    count = 0
    for key, state in st.session_state.get("field_edits", {}).items():
        if not state.get("dirty"):
            continue
        key_mode, _, _ = parse_field_key(key)
        if key_mode == import_mode:
            count += 1
    return count


def get_backup_reminder_signature(
    dirty_count: int, last_backup_ts, seconds_since_backup: float | None
):
    if dirty_count <= 0:
        return None

    parts = []

    if last_backup_ts is None:
        # Re-trigger every threshold block while no full backup exists.
        no_backup_bucket = dirty_count // BACKUP_REMINDER_DIRTY_THRESHOLD
        parts.append(f"no_backup:{no_backup_bucket}")
    elif dirty_count >= BACKUP_REMINDER_DIRTY_THRESHOLD:
        dirty_bucket = dirty_count // BACKUP_REMINDER_DIRTY_THRESHOLD
        parts.append(f"dirty:{dirty_bucket}")

    if (
        seconds_since_backup is not None
        and seconds_since_backup >= BACKUP_REMINDER_AFTER_SECONDS
    ):
        age_bucket = int(seconds_since_backup // BACKUP_REMINDER_AFTER_SECONDS)
        parts.append(f"age:{age_bucket}")

    if not parts:
        return None
    return "|".join(parts)


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


if st.session_state.get("show_intro_info", True):
    st.info(
    """
    Upload one `.zip` and select import mode.

    **Cerea txt**
    - Required: `universe.txt`
    - Field folders: `patterns.txt` (optional), `contour.txt` (optional)
    - Farms can be:
      1. directly next to `universe.txt`, or
      2. inside one intermediate folder (for example `data/`)
    ```
    zip
    ├─ universe.txt
    └─ data/ (name can vary)
       └─ Farm/Field/{contour.txt, patterns.txt}
    ```

    **Exported shp**
    - Field name is taken from filename before `_patterns` or `_contour`
      (examples: `Field1_patterns.shp`, `Field1_contour.shp`)
    - Include full shapefile sidecar files (`.shp`, `.shx`, `.dbf`, `.prj`)
    ```
    zip
    ├─ contours
    |  └─ Field1_contour.shp
    └─ patterns
        └─ Field1_patterns.shp
    ```
    """
    )

mode_col, input_col, check_col = st.columns([1, 2, 2])

with mode_col:
    import_mode = st.selectbox("Import mode", ["Cerea txt", "Exported shp"])

with input_col:
    uploaded_input_zip = st.file_uploader(
        "Import data zip",
        type=["zip"],
        accept_multiple_files=False,
    )

if uploaded_input_zip is None:
    intro_was_hidden = not st.session_state.get("show_intro_info", True)
    if st.session_state.get("input_extract_dir"):
        clear_uploaded_root_state()
    st.session_state.show_intro_info = True
    if intro_was_hidden:
        st.rerun()

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
        if not st.session_state.get("show_intro_info", True):
            st.session_state.show_intro_info = True
            st.rerun()
        st.stop()

    if st.session_state.get("show_intro_info", True):
        st.session_state.show_intro_info = False
        st.rerun()

    center_x = None
    center_y = None
    if import_mode == "Cerea txt":
        universe_path = resolve_universe_path(cerea_root)
        if universe_path is None:
            st.error("universe.txt not found.")
            st.stop()
        center_x, center_y = read_center(universe_path)

    farms = get_farms(cerea_root)
    farm_names = [f.name for f in farms]
    if not farm_names:
        st.warning("No farms found in Cerea root.")
        st.stop()

    field_panel_col, editor_col = st.columns([1, 3])
    left_panel = field_panel_col.container(key="left_panel_container")

    st.markdown(
        """
        <style>
        div.st-key-left_panel_container {
            background-color: #ffffff;
            border-right: 1px solid #d6d6c8;
            border-radius: 0.35rem;
            padding: 0.45rem 0.65rem 0.65rem 0.45rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with left_panel:
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

    with left_panel:
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

    with left_panel:
        st.divider()
        st.markdown(
            """
            <style>
            div.st-key-reset_field_changes_btn button,
            div.st-key-reset_all_changes_btn button {
                background-color: #FFFFE7 !important;
                color: #8C5E07 !important;
                border-color: #E6C98B !important;
            }
            div.st-key-reset_field_changes_btn button:hover,
            div.st-key-reset_all_changes_btn button:hover,
            div.st-key-reset_field_changes_btn button:active,
            div.st-key-reset_all_changes_btn button:active {
                background-color: #FFF8CC !important;
                color: #8C5E07 !important;
                border-color: #D2AF6B !important;
            }
            div.st-key-reset_field_changes_btn button:focus,
            div.st-key-reset_all_changes_btn button:focus,
            div.st-key-reset_field_changes_btn button:focus-visible,
            div.st-key-reset_all_changes_btn button:focus-visible {
                background-color: #FFFFE7 !important;
                color: #8C5E07 !important;
                border-color: #E6C98B !important;
                box-shadow: none !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Reset field changes",
            key="reset_field_changes_btn",
            use_container_width=True,
        ):
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

        if st.button(
            "Reset all changes",
            key="reset_all_changes_btn",
            use_container_width=True,
        ):
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
        has_contour_source = contour_file.exists()
        has_patterns_source = patterns_file.exists()
        missing_patterns_sidecars = []
        missing_contour_sidecars = []

        if import_mode == "Exported shp":
            if has_patterns_source:
                missing_patterns_sidecars = get_missing_shapefile_sidecars(patterns_file)
            if has_contour_source:
                missing_contour_sidecars = get_missing_shapefile_sidecars(contour_file)

            sidecar_infos = []
            if missing_patterns_sidecars:
                sidecars_text = ", ".join(missing_patterns_sidecars)
                sidecar_infos.append(
                    f"- Patterns sidecar file(s) missing: {sidecars_text}"
                )
            if missing_contour_sidecars:
                sidecars_text = ", ".join(missing_contour_sidecars)
                sidecar_infos.append(
                    f"- Contour sidecar file(s) missing: {sidecars_text}"
                )
            if sidecar_infos:
                st.info("\n".join(["Shapefile sidecar check:"] + sidecar_infos))

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
        # Keep widget layout visible in empty state.
        show_widgets_when_empty = True
        if not line_items and not show_widgets_when_empty:
            pass
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
                    st.button(
                        "x",
                        key=delete_btn_key,
                        use_container_width=True,
                        on_click=delete_track_from_field_state,
                        args=(current_key, int(item["id"])),
                    )

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

            delete_notice = st.session_state.pop("track_delete_notice", None)
            if delete_notice:
                st.success(delete_notice)

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

        dirty_count = get_dirty_field_count_for_mode(import_mode)
        last_backup_ts = st.session_state.get("last_full_backup_export_ts")
        seconds_since_backup = None
        if last_backup_ts is not None:
            seconds_since_backup = max(0.0, time.time() - float(last_backup_ts))
        reminder_signature = get_backup_reminder_signature(
            dirty_count, last_backup_ts, seconds_since_backup
        )
        if reminder_signature is None:
            st.session_state.pop("backup_reminder_last_shown_signature", None)
            st.session_state.pop("backup_reminder_visible_field_key", None)

        last_reminder_field_key = st.session_state.get("backup_reminder_last_field_key")
        field_changed = (
            last_reminder_field_key is not None and last_reminder_field_key != current_key
        )
        if field_changed:
            st.session_state["backup_reminder_visible_field_key"] = None
        last_shown_signature = st.session_state.get("backup_reminder_last_shown_signature")
        show_backup_reminder = (
            reminder_signature is not None
            and reminder_signature != last_shown_signature
            and field_changed
        )
        if show_backup_reminder:
            st.session_state["backup_reminder_last_shown_signature"] = reminder_signature
            st.session_state["backup_reminder_visible_field_key"] = current_key
        if st.session_state.get("backup_reminder_visible_field_key") == current_key:
            st.info(
                'Reminder: You can use "Prepare all fields export" to download a backup. '
                'You can re-import the backup via "Exported shp" mode in case of a server error.'
            )
        st.session_state["backup_reminder_last_field_key"] = current_key

        export_col_1, export_col_2, export_col_3 = st.columns(3)

        with export_col_1:
            if st.button("Prepare current field export", use_container_width=True):
                current_export_report_lines = build_field_export_report_lines(
                    import_mode,
                    selected_farm,
                    selected_field,
                    contour_file,
                    patterns_file,
                    current_state,
                )
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
                if current_export_report_lines:
                    st.info(
                        "\n".join(
                            ["Export report (current field):"]
                            + current_export_report_lines
                        )
                    )

        with export_col_2:
            if st.button("Prepare all fields export", use_container_width=True):
                export_root = Path(tempfile.mkdtemp(prefix="cerea_export_"))
                exported_count, export_report_lines = export_all_fields(
                    import_mode,
                    cerea_root,
                    export_root,
                    center_x,
                    center_y,
                    with_report=True,
                )
                zip_bytes = create_export_zip_bytes(export_root)
                shutil.rmtree(export_root, ignore_errors=True)
                st.session_state.export_bundle = {
                    "bytes": zip_bytes,
                    "label": "all fields",
                }
                st.session_state["last_full_backup_export_ts"] = time.time()
                st.success(f"Prepared export for {exported_count} field(s).")
                if export_report_lines:
                    st.info(
                        "\n".join(
                            ["Export report (skipped/partial fields):"]
                            + export_report_lines
                        )
                    )

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
                    changes_export_report_lines = []
                    for key in changed_keys:
                        key_mode, farm_name, field_name = parse_field_key(key)
                        if key_mode != import_mode:
                            continue
                        state = st.session_state.field_edits[key]
                        contour_source, patterns_source = get_field_sources(
                            import_mode, cerea_root, farm_name, field_name
                        )
                        changes_export_report_lines.extend(
                            build_field_export_report_lines(
                                import_mode,
                                farm_name,
                                field_name,
                                contour_source,
                                patterns_source,
                                state,
                            )
                        )
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
                        if changes_export_report_lines:
                            st.info(
                                "\n".join(
                                    ["Export report (all changes):"]
                                    + changes_export_report_lines
                                )
                            )
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
