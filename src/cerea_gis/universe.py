from pathlib import Path


def read_center(universe_path: Path) -> tuple[float, float]:
    """
    Reads the last line of universe.txt
    Returns center coordinates in EPSG:25832
    """
    with universe_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    last_line = lines[-1].strip()
    x_str, y_str = last_line.split(",")

    return float(x_str), float(y_str)
