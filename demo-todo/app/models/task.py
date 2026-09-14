"""任务数据模型。"""


class Task:
    """任务实体：包含标题、优先级与完成状态。"""

    def __init__(self, task_id: int, title: str, priority: int = 1) -> None:
        self.task_id = task_id
        self.title = title
        self.priority = priority
        self.done = False

    def mark_done(self) -> bool:
        """标记完成，返回最新状态。"""
        self.done = True
        return self.done
