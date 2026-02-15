from pathlib import Path
from .universe import read_center
from .contour import parse_contour
from .patterns import parse_patterns
from .exporter import export_polygon, export_lines


def process_cerea_root(cerea_root: Path, output_root: Path):
    """
    Processes complete Cerea directory structure.
    Mirrors structure into output directory.
    """

    universe_path = cerea_root / "universe.txt"

    if not universe_path.exists():
        raise FileNotFoundError("universe.txt not found in Cerea root.")

    center_x, center_y = read_center(universe_path)

    # Iterate over farm directories
    for farm_dir in cerea_root.iterdir():
        if not farm_dir.is_dir():
            continue

        if farm_dir.name == "__pycache__":
            continue

        print(f"Processing farm: {farm_dir.name}")

        # Iterate over field directories
        for field_dir in farm_dir.iterdir():
            if not field_dir.is_dir():
                continue

            contour_file = field_dir / "contour.txt"
            patterns_file = field_dir / "patterns.txt"

            if not contour_file.exists():
                continue

            print(f"  Processing field: {field_dir.name}")

            polygon = parse_contour(contour_file, center_x, center_y)

            lines = []
            if patterns_file.exists():
                lines = parse_patterns(patterns_file, center_x, center_y)

            # Create mirrored output path
            target_dir = output_root / farm_dir.name / field_dir.name
            target_dir.mkdir(parents=True, exist_ok=True)

            export_polygon(polygon, target_dir / f"{field_dir.name}_contour.shp")

            if lines:
                export_lines(lines, target_dir / f"{field_dir.name}_pattern.shp")
