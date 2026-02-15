import json
from pathlib import Path
from shapely.geometry import Polygon


def parse_contour(contour_path: Path, center_x: float, center_y: float) -> Polygon:
    """
    Parses contour.txt and returns a Shapely Polygon
    """

    with contour_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    coord_string = data["contourTrueStr"]
    coords = coord_string.split(",")

    points = []

    for i in range(0, len(coords), 3):
        dx = float(coords[i])
        dy = float(coords[i + 1])

        x = center_x + dx
        y = center_y + dy

        points.append((x, y))

    return Polygon(points)
