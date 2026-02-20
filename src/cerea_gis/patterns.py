from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString


def parse_patterns(pattern_path: Path, center_x: float, center_y: float):
    """
    Parses patterns.txt and returns list of (name, LineString).

    Supported row layouts:
    - one segment: id,mode,name,x1,y1,z1,x2,y2,z2
    - polyline row: id,mode,name,x1,y1,z1,x2,y2,z2,...,xn,yn,zn
    - multi-row polyline with repeated name (rows are merged in file order)
    """

    pattern_points = defaultdict(list)

    with pattern_path.open("r", encoding="utf-8") as f:
        for row in f:
            parts = [p.strip() for p in row.strip().split(",")]
            if len(parts) < 9:
                continue

            name = parts[2]
            row_points = []

            # Coordinates start at index 3 and are encoded as repeating x,y,z triplets.
            for i in range(3, len(parts) - 2, 3):
                try:
                    dx = float(parts[i])
                    dy = float(parts[i + 1])
                except (ValueError, IndexError):
                    continue
                row_points.append((center_x + dx, center_y + dy))

            if len(row_points) < 2:
                continue

            if not pattern_points[name]:
                pattern_points[name].extend(row_points)
                continue

            # Avoid duplicate connecting point when rows are split into segments.
            if pattern_points[name][-1] == row_points[0]:
                pattern_points[name].extend(row_points[1:])
            else:
                pattern_points[name].extend(row_points)

    result = []
    for name, points in pattern_points.items():
        if len(points) >= 2:
            result.append((name, LineString(points)))

    return result
