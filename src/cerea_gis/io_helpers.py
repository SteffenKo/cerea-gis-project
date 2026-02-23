import io
import zipfile
from pathlib import Path

import geopandas as gpd


def get_farms(cerea_root: Path):
    return [d for d in cerea_root.iterdir() if d.is_dir()]


def get_fields(farm_path: Path):
    return [d for d in farm_path.iterdir() if d.is_dir()]


def get_exported_fields(farm_path: Path):
    patterns_dir = farm_path / "patterns"
    contours_dir = farm_path / "contours"

    field_names = set()
    if patterns_dir.exists():
        for patterns_file in patterns_dir.glob("*_patterns.shp"):
            field_name = patterns_file.stem.removesuffix("_patterns")
            field_names.add(field_name)

    if contours_dir.exists():
        for contour_file in contours_dir.glob("*_contour.shp"):
            field_name = contour_file.stem.removesuffix("_contour")
            field_names.add(field_name)

    return sorted(field_names)


def get_missing_shapefile_sidecars(shp_path: Path):
    sidecar_exts = [".shx", ".dbf", ".prj"]
    return [ext for ext in sidecar_exts if not shp_path.with_suffix(ext).exists()]


def _looks_like_cerea_field_dir(field_dir: Path):
    if not field_dir.is_dir():
        return False

    # A real Cerea field folder can contain contour/pattern files, but we also
    # tolerate empty field folders. Wrapper directories usually contain further
    # subfolders and should not be treated as fields.
    has_known_files = (field_dir / "contour.txt").exists() or (
        field_dir / "patterns.txt"
    ).exists()
    if has_known_files:
        return True

    has_subdirs = any(child.is_dir() for child in field_dir.iterdir())
    return not has_subdirs


def _has_cerea_txt_farms(root_dir: Path):
    for farm_dir in root_dir.iterdir():
        if not farm_dir.is_dir():
            continue
        for field_dir in farm_dir.iterdir():
            if _looks_like_cerea_field_dir(field_dir):
                return True
    return False


def resolve_universe_path(root_path: Path):
    direct_path = root_path / "universe.txt"
    if direct_path.exists():
        return direct_path

    parent_path = root_path.parent / "universe.txt"
    if parent_path.exists():
        return parent_path

    return None


def resolve_import_root(extract_dir: Path, import_mode: str):
    candidates = [extract_dir] + [d for d in extract_dir.iterdir() if d.is_dir()]

    if import_mode == "Cerea txt":
        for candidate in candidates:
            if not (candidate / "universe.txt").exists():
                continue

            if _has_cerea_txt_farms(candidate):
                return candidate

            nested_farm_roots = [
                sub_dir
                for sub_dir in candidate.iterdir()
                if sub_dir.is_dir() and _has_cerea_txt_farms(sub_dir)
            ]
            if nested_farm_roots:
                return sorted(nested_farm_roots, key=lambda p: p.name)[0]
    else:
        for candidate in candidates:
            farm_dirs = [d for d in candidate.iterdir() if d.is_dir()]
            for farm_dir in farm_dirs:
                if (farm_dir / "patterns").exists() or (farm_dir / "contours").exists():
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
        if resolve_universe_path(root_path) is None:
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
                    warnings.append(
                        f"Missing optional contour.txt: {farm_dir.name}/{field_dir.name}"
                    )
                if not patterns_file.exists():
                    warnings.append(
                        f"Missing optional patterns.txt: {farm_dir.name}/{field_dir.name}"
                    )
                if not contour_file.exists() and not patterns_file.exists():
                    warnings.append(
                        "No source files in field folder: "
                        f"{farm_dir.name}/{field_dir.name} "
                        "(needs contour.txt and/or patterns.txt)"
                    )
    else:
        for farm_dir in farms:
            patterns_dir = farm_dir / "patterns"
            contours_dir = farm_dir / "contours"
            if not patterns_dir.exists():
                warnings.append(f"Missing optional folder: {farm_dir.name}/patterns")
            if not contours_dir.exists():
                warnings.append(f"Missing optional folder: {farm_dir.name}/contours")

            field_names = get_exported_fields(farm_dir)
            if not field_names:
                warnings.append(
                    "No field shapefiles found in farm: "
                    f"{farm_dir.name} (expected *_patterns.shp and/or *_contour.shp)"
                )
                continue

            for field_name in field_names:
                stats["fields"] += 1
                patterns_shp = patterns_dir / f"{field_name}_patterns.shp"
                if not patterns_shp.exists():
                    warnings.append(
                        f"Missing optional patterns shapefile: {farm_dir.name}/patterns/{patterns_shp.name}"
                    )
                else:
                    missing_patterns_sidecars = get_missing_shapefile_sidecars(patterns_shp)
                    if missing_patterns_sidecars:
                        sidecars_text = ", ".join(missing_patterns_sidecars)
                        warnings.append(
                            "Missing sidecar(s) for patterns shapefile: "
                            f"{farm_dir.name}/patterns/{patterns_shp.name} -> {sidecars_text}"
                        )

                contour_shp = contours_dir / f"{field_name}_contour.shp"
                if not contour_shp.exists():
                    warnings.append(
                        f"Missing optional contour shapefile: {farm_dir.name}/contours/{field_name}_contour.shp"
                    )
                else:
                    missing_contour_sidecars = get_missing_shapefile_sidecars(contour_shp)
                    if missing_contour_sidecars:
                        sidecars_text = ", ".join(missing_contour_sidecars)
                        warnings.append(
                            "Missing sidecar(s) for optional contour shapefile: "
                            f"{farm_dir.name}/contours/{contour_shp.name} -> {sidecars_text}"
                        )

    return {"issues": issues, "warnings": warnings, "stats": stats}


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

    if ordered_line_items:
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
