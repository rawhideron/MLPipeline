import sys
from pathlib import Path

# Allow `from inference_handler import ...` bare imports in serving/app.py
# to resolve when pytest imports it as `serving.app` from the repo root.
sys.path.insert(0, str(Path(__file__).parent / "serving"))
