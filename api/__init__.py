"""
RecoverAI API package.
"""

from api.config import settings

__all__ = ["create_app", "app", "settings"]


def __getattr__(name: str):
    if name in ("create_app", "app"):
        from api.app import create_app, app
        return {"create_app": create_app, "app": app}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
