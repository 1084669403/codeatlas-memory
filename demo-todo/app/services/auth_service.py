"""认证业务逻辑。"""

from app.models.user import User


class AuthService:
    """注册与登录的最小实现。"""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def register(self, name: str, password: str) -> bool:
        """注册新用户，重名返回 False。"""
        if name in self._users:
            return False
        self._users[name] = User(len(self._users) + 1, name)
        return True
