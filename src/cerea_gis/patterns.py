from pathlib import Path
from shapely.geometry import LineString
from collections import defaultdict


def parse_patterns(pattern_path: Path, center_x: float, center_y: float):
    """
    Parses patterns.txt and returns list of (name, LineString)

    Handles:
    - AB lines (single segment)
    - Curves (multiple segments with same name)
    """

    # name → list of points
    pattern_points = defaultdict(list)

    with pattern_path.open("r", encoding="utf-8") as f:
        for row in f:
            parts = row.strip().split(",")

            if len(parts) < 8:
                continue

            name = parts[2]

            dx1, dy1 = float(parts[3]), float(parts[4])
            dx2, dy2 = float(parts[6]), float(parts[7])

            p1 = (center_x + dx1, center_y + dy1)
            p2 = (center_x + dx2, center_y + dy2)

            if not pattern_points[name]:
                # first segment → add both points
                pattern_points[name].append(p1)
                pattern_points[name].append(p2)
            else:
                # subsequent segments → add only end point
                pattern_points[name].append(p2)

    # Convert to LineStrings
    result = []

    for name, points in pattern_points.items():
        if len(points) >= 2:
            result.append((name, LineString(points)))

    return result
