# 目录名含连字符（boss-extract-jobs）为刻意设计，见 README「接线路径」
"""boss-extract-jobs：Boss 直聘岗位提取垂直工具（提取 → 筛选 → 落库）。

技能目录说明：skills/ 集中存放未来 agent（doc 06 LangGraph skill_router）可编排的
垂直领域工具；本目录自包含，不与 backend 耦合，依赖经 service.BossExtractService
构造参数注入。

注意：目录名含连字符（boss-extract-jobs），因此不能作为合法 Python 包名直接
`import skills.boss_extract_jobs`。仓库内独立运行走顶层导入（tests/conftest.py
注入 sys.path 后 `from service import ...` / `from job_fit import ...`）；
未来 agent 接线时建议打包重命名为合法包名（如 boss_extract_jobs），或用
`importlib.import_module("skills.boss-extract-jobs.service")`。详见 SKILL.md。
"""

# 本文件仅作包标记与说明，不做导入（避免连字符目录被 pytest/importlib 以包方式
# 加载时触发相对导入失败）。用法入口见 README.md / SKILL.md「接线说明」。
