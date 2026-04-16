from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PANEL_DIR = PROJECT_ROOT / "panel"
MEDIA_DIR = PROJECT_ROOT / "media"

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
