"""用户资产目录：报告数据的落位与命名。

与程序数据（~/.career-kit）分开：调研报告、证据池、投递清单等查看用资产
放在 ~/CareerKit（CAREER_KIT_ASSETS_DIR 可覆盖）。新版本不再生成静态 HTML，
统一通过桌面上的「Career Kit」快捷方式打开本地控制台查看。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

# kind → 中文子目录名
ASSETS_KIND_DIRS: dict[str, str] = {
    "research": "调研报告",
    "evidence": "证据池",
    "applications": "投递清单",
}

README_FILENAME = "说明.md"

DEFAULT_SANITIZED = "默认档案"

# 文件名主干的长度上限；扩展名永远单独保留，不参与截断。
ASSET_STEM_LIMIT = 80

# Windows 保留设备名（档案/方向名撞上时加后缀防御）
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def get_assets_root() -> Path:
    """用户资产根目录：环境变量优先，否则 ~/CareerKit。"""
    env = os.environ.get("CAREER_KIT_ASSETS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / "CareerKit"


def _sanitize_chars(raw: str) -> str:
    """替换跨平台非法字符，去掉首尾空格与点。"""
    cleaned = []
    for ch in raw:
        if ch in '<>:"/\\|?*' or ord(ch) < 0x20:
            cleaned.append("_")
        else:
            cleaned.append(ch)
    return "".join(cleaned).strip(" .")


def sanitize_name(raw: str | None) -> str:
    """把档案名/方向名转成跨平台安全的目录与文件名片段。"""
    if not raw or not raw.strip() or raw.strip().lower() == "default":
        return DEFAULT_SANITIZED
    name = _sanitize_chars(raw.strip())[:40].strip(" .")
    if not name:
        return DEFAULT_SANITIZED
    stem = name.split(".")[0].upper() if "." in name else name.upper()
    if stem in _WINDOWS_RESERVED:
        name = f"{name}_"
    return name


def asset_filename(raw: str | None, *, limit: int = ASSET_STEM_LIMIT) -> str:
    """把完整文件名转成安全文件名：只截断主干，扩展名永远完整保留。

    报告/证据池的文件名可能很长（日期 + 方向名），截断时必须保住 `.md`
    与 `.json`，否则双击打不开、扩展名筛选也会漏掉。
    """
    text = str(raw or "").strip()
    if not text:
        return "未命名.md"
    suffix = ""
    candidate = Path(text).suffix
    if candidate and 1 < len(candidate) <= 11 and candidate[1:].isalnum():
        suffix = candidate
        text = text[: -len(suffix)]
    body = _sanitize_chars(text)
    room = max(1, limit - len(suffix))
    if len(body) > room:
        body = body[:room].strip(" .")
    if not body:
        body = "未命名"
    stem = body.split(".")[0].upper() if "." in body else body.upper()
    if stem in _WINDOWS_RESERVED:
        body = f"{body}_"
    return body + suffix


def profile_display_name(name: str | None) -> str:
    """档案显示名：default/空 → 默认档案，与资产目录命名保持一致。"""
    raw = str(name or "").strip()
    if not raw or raw.lower() == "default":
        return DEFAULT_SANITIZED
    return raw


def ensure_assets_root() -> Path:
    """确保资产根目录存在；首次创建时写说明.md。"""
    root = get_assets_root()
    root.mkdir(parents=True, exist_ok=True)
    readme = root / README_FILENAME
    if not readme.exists():
        readme.write_text(_readme_text(), encoding="utf-8-sig")
    return root


def profile_assets_dir(profile_name: str) -> Path:
    """当前档案的资产目录：root/<档案名>/。"""
    ensure_assets_root()
    return get_assets_root() / sanitize_name(profile_name)


def kind_assets_dir(kind: str, profile_name: str) -> Path:
    """某一类产出的目录：root/<档案名>/<中文子目录>/。"""
    if kind not in ASSETS_KIND_DIRS:
        raise ValueError(f"未知资产类型：{kind}，可选 {sorted(ASSETS_KIND_DIRS)}")
    path = profile_assets_dir(profile_name) / ASSETS_KIND_DIRS[kind]
    path.mkdir(parents=True, exist_ok=True)
    return path


def next_asset_stem(
    direction: str,
    *,
    kind: str | None = None,
    profile_name: str | None = None,
    now: datetime | None = None,
) -> str:
    """生成留档文件名主干：日期_时分_方向；同分钟撞名时自动降级到序号。"""
    now = now or datetime.now()
    base = f"{now:%Y-%m-%d_%H%M}_{sanitize_name(direction)}"
    if not (kind and profile_name):
        return base
    directory = kind_assets_dir(kind, profile_name)
    candidates = [
        base,
        *(f"{base}_{i:02d}" for i in range(1, 100)),
    ]
    for candidate in candidates:
        if not (directory / f"{candidate}.md").exists():
            return candidate
    return candidates[0] + "_x"


def write_asset_text(
    kind: str,
    profile_name: str,
    filename: str,
    text: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """写一个资产文本文件（自动建目录），返回路径。"""
    target = kind_assets_dir(kind, profile_name) / asset_filename(filename)
    target.write_text(text, encoding=encoding)
    return target


def write_asset_bytes(kind: str, profile_name: str, filename: str, data: bytes) -> Path:
    """写一个资产二进制文件（自动建目录），返回路径。"""
    target = kind_assets_dir(kind, profile_name) / asset_filename(filename)
    target.write_bytes(data)
    return target


def _readme_text() -> str:
    return """# Career Kit 资产目录

这里是 Career Kit 为你生成的查看用数据，与程序数据（~/.career-kit）相互独立。

## 怎么用

- 双击桌面上的「Career Kit」快捷方式，在控制台里查看路线图、报告与投递清单。
- 每个子目录按你的档案分文件夹；报告文件名带日期，多次生成各自留档，不互相覆盖。
- 本目录中的 md / json 是报告原文与原始数据，控制台会直接读取；请不要手动改名。

## 来源声明

Career Kit 的报告数据全部来自实时抓取与本地知识库，每条附来源链接；
未获取到的内容会明确标注「未获取」，不用 AI 记忆编造。

本目录可随时移动或删除，不影响档案数据；后续产出会自动回到这里。
"""

