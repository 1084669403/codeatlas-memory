# 任务管理示例（demo-todo）

一个贴近真实架构的小项目，用于演示 CodeAtlas 效果：

- `app/controllers/` 接口层
- `app/services/` 业务层
- `app/models/` 数据模型
- `app/utils/` 工具
- `static/` 前端 TypeScript 组件

运行方式（在仓库根目录）：

```bash
uv run codeatlas scan demo-todo --lang zh
uv run codeatlas query "任务" demo-todo
```
