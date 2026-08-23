"""pytest 配置：把 skills/boss_chat 注入 sys.path，使测试可独立运行。

无论从仓库根还是进目录执行，都能 import 到 service（service 内用点号相对导入 .service，
本 conftest 把包目录置于 sys.path 使 `from .service import ...` 形态的 __init__ 可解析）。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent.parent  # .../skills/boss_chat

if str(_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_DIR))
