"""任务业务逻辑。"""

from app.models.task import Task


class TaskService:
    """任务的增删改查与统计。"""

    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._next_id = 1

    def create(self, title: str, priority: int = 1) -> Task:
        """创建新任务并分配自增 ID。"""
        task = Task(self._next_id, title, priority)
        self._tasks[task.task_id] = task
        self._next_id += 1
        return task

    def complete(self, task_id: int) -> bool:
        """完成任务，不存在时返回 False。"""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        return task.mark_done()

    def filter_by_priority(self, min_priority: int) -> list[Task]:
        """按最低优先级过滤任务。"""
        return [t for t in self._tasks.values() if t.priority >= min_priority]

    def stats(self, include_done: bool = True) -> dict[str, int]:
        """统计任务总数；include_done 为 False 时只统计未完成。"""
        pool = self._tasks.values() if include_done else (t for t in self._tasks.values() if not t.done)
        total = sum(1 for _ in pool)
        done = sum(1 for t in self._tasks.values() if t.done)
        return {"total": total, "done": done}
