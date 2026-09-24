"""Folder layout. Import from here instead of computing paths from __file__."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT, "config")
DATA_DIR = os.path.join(ROOT, "data")
DASHBOARD_DIR = os.path.join(ROOT, "dashboards")

for _d in (DATA_DIR, DASHBOARD_DIR):     # ignored by git, so a fresh clone lacks them
    os.makedirs(_d, exist_ok=True)