"""任务接口层。"""

from app.services.task_service import TaskService


class TaskController:
    """处理任务相关请求，转发给业务层。"""

    def __init__(self) -> None:
        self.service = TaskService()

    def handle_create(self, title: str) -> int:
        """创建任务并返回新任务 ID。"""
        task = self.service.create(title)
        return task.task_id

    def handle_complete(self, task_id: int) -> bool:
        """完成任务请求的入口。"""
        return self.service.complete(task_id)
