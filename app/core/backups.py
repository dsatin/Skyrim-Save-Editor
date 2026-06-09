from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil


def make_backup(path: Path, backup_dir: Path | None = None) -> Path:
    """Create a timestamped backup next to the save unless backup_dir is supplied."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = backup_dir if backup_dir is not None else path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = target_dir / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, backup)
    return backup
