from pathlib import Path
from src.cerea_gis.core import process_cerea_root

CEREA_ROOT = Path(r"C:\Users\steff\Documents\CereaTestBackup")
OUTPUT_ROOT = Path(r"C:\Users\steff\Documents\CereaTestOutput")

process_cerea_root(CEREA_ROOT, OUTPUT_ROOT)

print("Fertig.")
