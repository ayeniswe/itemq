from pathlib import Path
import os

# Centralized media root for the application.
MEDIA_ROOT = Path(os.getenv("ITEMQ_MEDIA_PATH", "data/media")).resolve()