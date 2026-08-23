"""pytest 配置：把 skills/boss_extract_jobs 注入 sys.path，使测试可独立运行。

无论从仓库根（`python -m pytest skills/boss_extract_jobs/tests`）还是进目录
（`cd skills/boss_extract_jobs && python -m pytest tests`）执行，都能 import
到 job_fit / service（service.py 内部先试包内相对导入，失败回退到顶层导入）。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent.parent  # .../skills/boss_extract_jobs

if str(_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_DIR))
