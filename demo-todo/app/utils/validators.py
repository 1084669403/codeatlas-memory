"""校验工具。"""


def validate_title(title: str) -> bool:
    """标题非空且长度不超过 50。"""
    return bool(title.strip()) and len(title) <= 50
