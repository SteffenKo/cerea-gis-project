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

