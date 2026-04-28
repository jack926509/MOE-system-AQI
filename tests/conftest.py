import os
import sys
from pathlib import Path

# 確保 import root packages 可用
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MOENV_API_KEY", "test-key")
