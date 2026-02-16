import geopandas as gpd
from pathlib import Path

def export_polygon(polygon, output_path: Path):
    # Ordner sicherstellen
    output_path.parent.mkdir(parents=True, exist_ok=True)

    gdf = gpd.GeoDataFrame(
        [{"geometry": polygon}],
        crs="EPSG:25832"
    )

    gdf.to_file(output_path)


def export_lines(lines, output_path: Path, order=None):
    """
    lines: list of (name, LineString)
    order: list of names in desired order
    """

    if order:
        ordered_lines = []
        for name in order:
            for n, geom in lines:
                if n == name:
                    ordered_lines.append((n, geom))
        lines = ordered_lines

    output_path.parent.mkdir(parents=True, exist_ok=True)

    gdf = gpd.GeoDataFrame(
        [{"name": name, "geometry": geom} for name, geom in lines],
        crs="EPSG:25832"
    )

    gdf.reset_index(drop=True, inplace=True)

    gdf.to_file(output_path)


def export_field_geometries(
    polygon,
    lines,
    output_root: Path,
    farm_name: str,
    field_name: str,
):
    """
    Exports one field into farm-level folders:
    - {output_root}/{farm_name}/contours/{field_name}_contour.shp
    - {output_root}/{farm_name}/patterns/{field_name}_patterns.shp
    """
    farm_dir = output_root / farm_name
    contours_dir = farm_dir / "contours"
    patterns_dir = farm_dir / "patterns"

    contours_dir.mkdir(parents=True, exist_ok=True)
    patterns_dir.mkdir(parents=True, exist_ok=True)

    export_polygon(polygon, contours_dir / f"{field_name}_contour.shp")

    if lines:
        export_lines(lines, patterns_dir / f"{field_name}_patterns.shp")

