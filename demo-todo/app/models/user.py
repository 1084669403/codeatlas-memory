"""用户数据模型。"""


class User:
    """用户实体：仅保留最小字段。"""

    def __init__(self, user_id: int, name: str) -> None:
        self.user_id = user_id
        self.name = name
