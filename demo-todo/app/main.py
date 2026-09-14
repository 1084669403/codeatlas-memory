"""任务管理示例应用入口。

EN: Demo entry point wiring controller -> service -> model.
ZH: 示例入口，演示 controller -> service -> model 分层。
"""

from app.controllers.task_controller import TaskController


def main() -> None:
    """启动示例流程：创建并完成一个任务。"""
    controller = TaskController()
    task_id = controller.handle_create("编写周报")
    controller.handle_complete(task_id)


if __name__ == "__main__":
    main()
