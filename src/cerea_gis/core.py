from pathlib import Path
from .universe import read_center
from .contour import parse_contour
from .patterns import parse_patterns
from .exporter import export_field_geometries


def process_cerea_root(cerea_root: Path, output_root: Path):
    """
    Processes complete Cerea directory structure.
    Exports to farm-level folders in output directory.
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

            export_field_geometries(
                polygon=polygon,
                lines=lines,
                output_root=output_root,
                farm_name=farm_dir.name,
                field_name=field_dir.name,
            )
