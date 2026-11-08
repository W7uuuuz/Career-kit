"""旧档案适配器——把 `CareerProfile` 转成 Core v2 的 artifact 输入。"""

from .legacy_profile import profile_snapshot, target_spec

__all__ = ["profile_snapshot", "target_spec"]
