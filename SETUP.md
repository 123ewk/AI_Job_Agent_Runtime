# Python 项目开发环境配置

## 已配置的工具

### 1. Ruff (v0.15.17+)
- **用途**: 超快速的 Python linter 和 formatter（替代 flake8、isort、black、autopep8 等）
- **功能**:
  - 代码风格检查 (pycodestyle, pyflakes)
  - 导入排序 (isort)
  - 命名规范检查 (pep8-naming)
  - 代码升级建议 (pyupgrade)
  - 安全检查 (flake8-bandit)
  - 代码简化建议 (flake8-simplify)
  - 性能检查 (perflint)
  - 类型注解检查 (flake8-annotations)
  - 以及更多规则集...

### 2. mypy (v2.1.0+)
- **用途**: Python 静态类型检查器
- **配置**: Strict 模式，强制执行严格的类型检查

### 3. pre-commit (v4.6.0+)
- **用途**: Git hooks 管理工具，在提交前自动运行代码检查
- **已配置的 hooks**:
  - trailing-whitespace: 删除行尾空格
  - end-of-file-fixer: 确保文件以换行结尾
  - check-yaml/check-json/check-toml: 配置文件语法检查
  - check-added-large-files: 检查大文件
  - check-merge-conflict: 检查合并冲突标记
  - ruff: 代码 lint 和 format
  - mypy: 类型检查
  - typos: 拼写检查

## 安装和使用

### 1. 安装依赖
```bash
pip install ruff mypy pre-commit pytest pytest-cov
```

或者使用 poetry/pipenv/uv:
```bash
# 使用 uv (推荐)
uv add --dev ruff mypy pre-commit pytest pytest-cov

# 使用 poetry
poetry add --dev ruff mypy pre-commit pytest pytest-cov
```

### 2. 安装 pre-commit hooks
```bash
pre-commit install
```

### 3. 手动运行检查

**运行 ruff 检查:**
```bash
ruff check .
ruff check --fix .  # 自动修复可修复的问题
```

**运行 ruff 格式化:**
```bash
ruff format .
```

**运行 mypy 类型检查:**
```bash
mypy .
```

**运行所有 pre-commit hooks:**
```bash
pre-commit run --all-files
```

**运行测试:**
```bash
pytest
pytest --cov=ai_job_agent_runtime  # 带覆盖率
```

## 项目结构建议

```
ai-job-agent-runtime/
├── ai_job_agent_runtime/       # 主源码目录
│   ├── __init__.py
│   └── ...
├── tests/                      # 测试目录
│   ├── __init__.py
│   └── test_*.py
├── pyproject.toml             # 项目配置
├── .pre-commit-config.yaml    # pre-commit 配置
├── .gitignore                 # Git 忽略文件
└── SETUP.md                   # 本文档
```

## VS Code 集成建议

在 `.vscode/settings.json` 中添加:

```json
{
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },
  "python.linting.ruffEnabled": true,
  "python.linting.mypyEnabled": true,
  "python.analysis.typeCheckingMode": "strict"
}
```
