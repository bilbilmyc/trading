# Contributing

本项目以个人使用为主，但欢迎外部贡献。

## 开发环境

```bash
git clone <repo>
cd trading
uv sync --all-extras --dev
cd frontend && npm install && cd ..

# 装 pre-commit hooks（可选）
uv run pip install pre-commit
uv run pre-commit install
```

## 工作流

1. **从 main 拉新分支**：`git checkout -b feature/xxx`
2. **小步提交**：每个 commit 一个逻辑变更
3. **commit message 用中文**（项目惯例），格式 `type(scope): 中文标题`
4. **跑测试**：`uv run pytest`（目标 0 失败 + 0 回归）
5. **跑 lint**：`uv run ruff check app/ config/`
6. **TypeCheck**（可选）：`uv run mypy app/`
7. **push 后开 PR**

## 代码风格

- **Python**：用 ruff 自动修复（`uv run ruff check --fix app/`），所有新代码必须 `ruff check` 干净
- **TypeScript**：用 `tsc -b` 严格类型
- **命名**：snake_case for Python, camelCase for TS
- **注释**：中文优先（项目惯例），但公开 API docstring 英文

## 架构原则

- **薄路由**：路由处理器只做参数校验和委托，业务逻辑放 `app/engine/`
- **Protocol 抽象**：依赖抽象（`LLMContextProvider`），不依赖具体类
- **分层清晰**：`api / engine / exchanges / strategies / models / data_sources / core`
- **TDD**：测试覆盖核心业务逻辑；新功能先写测试再实现

## 测试

- 单元测试：核心算法、状态机、helper 函数
- 集成测试：FastAPI TestClient 端到端
- 端到端：手动跑 dev server

不要为了覆盖率而写测试。覆盖核心不变量，不是覆盖行数。

## 提交 PR

- 一个 PR 一个主题
- 描述里说明：动机、改了什么、如何测试
- 关联 issue（如果有）

## 行为准则

- 尊重他人时间
- 直接、不情绪化
- 在不同意时用技术论据，不用人身攻击
