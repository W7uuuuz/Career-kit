"""用户资产目录——调研报告、差距分析、路线图、仪表盘的落位与总入口。

与程序数据（~/.career-kit）彻底分离：档案、知识库、缓存属于程序；
调研报告 / 差距分析 / 路线图 / 仪表盘属于用户资产，放 ~/CareerKit
（CAREER_KIT_ASSETS_DIR 可覆盖），全部按「用户查看优先」设计：

- 根目录显眼（无点前缀），资源管理器直接可见
- index.html 是唯一入口：所有产出按档案分组展示、点卡片直达
- 目录与文件用中文命名，报告文件名带日期，多次生成各自留档
- 路线图/仪表盘用固定文件名：file:// 下 localStorage 按路径续上打卡状态
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

# kind → 中文子目录名（契约：改这里必须同步迁移旧文件与测试）
ASSETS_KIND_DIRS: dict[str, str] = {
    "research": "调研报告",
    "analysis": "差距分析",
    "roadmap": "路线图",
    "progress": "进度",
}

# 固定文件名（保 localStorage 打卡状态与「永远是最新」语义）
ROADMAP_FILENAME = "路线图.html"
PROGRESS_FILENAME = "进度仪表盘.html"

# kind → 固定文件名（路线图/进度使用；调研/差距按日期留档）
ASSETS_FILENAME_BY_KIND: dict[str, str] = {
    "roadmap": ROADMAP_FILENAME,
    "progress": PROGRESS_FILENAME,
}

INDEX_FILENAME = "index.html"
README_FILENAME = "说明.md"

DEFAULT_SANITIZED = "默认档案"

# Windows 保留设备名（档案/方向名撞上时加后缀防御）
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_KIND_LABELS: dict[str, str] = {
    "research": "调研报告",
    "analysis": "差距分析",
    "roadmap": "路线图",
    "progress": "进度",
}


def get_assets_root() -> Path:
    """用户资产根目录：环境变量优先，否则 ~/CareerKit。"""
    env = os.environ.get("CAREER_KIT_ASSETS_DIR", "").strip()
    if env:
        return Path(env)
    return Path.home() / "CareerKit"


def sanitize_name(raw: str | None) -> str:
    """把档案名/方向名转成跨平台安全的目录与文件名片段。

    规则：Windows 非法字符与控制符 → 下划线；去首尾空白与点；
    超长截断 40 字符；撞 Windows 保留名加后缀；空/default 归「默认档案」。
    """
    if not raw or not raw.strip() or raw.strip().lower() == "default":
        return DEFAULT_SANITIZED
    cleaned = []
    for ch in raw.strip():
        if ch in '<>:"/\\|?*' or ord(ch) < 0x20:
            cleaned.append("_")
        else:
            cleaned.append(ch)
    name = "".join(cleaned).strip(" .")
    name = name[:40].strip(" .")
    if not name:
        return DEFAULT_SANITIZED
    stem = name.split(".")[0].upper() if "." in name else name.upper()
    if stem in _WINDOWS_RESERVED:
        name = f"{name}_"
    return name


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
    """生成留档文件名主干：日期_方向；同日同目录撞名时自动降级到 时分/序号。"""
    now = now or datetime.now()
    base = f"{now:%Y-%m-%d}_{sanitize_name(direction)}"
    if not (kind and profile_name):
        return base
    directory = kind_assets_dir(kind, profile_name)
    candidates = [
        base,
        f"{now:%Y-%m-%d_%H%M}_{sanitize_name(direction)}",
        *(f"{now:%Y-%m-%d_%H%M}_{sanitize_name(direction)}_{i:02d}" for i in range(1, 100)),
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
    target = kind_assets_dir(kind, profile_name) / sanitize_name(filename)
    target.write_text(text, encoding=encoding)
    return target


def write_asset_bytes(kind: str, profile_name: str, filename: str, data: bytes) -> Path:
    """写一个资产二进制文件（自动建目录），返回路径。"""
    target = kind_assets_dir(kind, profile_name) / sanitize_name(filename)
    target.write_bytes(data)
    return target


@dataclass
class AssetItem:
    """index 页面上的一张产出卡片。"""

    kind: str
    title: str  # 卡片标题（方向或默认名）
    when: str  # 展示时间
    sort_key: str  # 排序键（文件名内日期或 mtime）
    rel_href: str
    counts_text: str = ""
    extras: dict[str, str] = field(default_factory=dict)  # 附属文件 {标签: 相对链接}


def _parse_when(stem: str) -> tuple[str, str]:
    """从文件名主干解析 (展示时间, 排序键)；解析不了回退低优先。"""
    parts = stem.split("_")
    if len(parts) >= 2 and len(parts[0]) == 10 and parts[0][:4].isdigit():
        date = parts[0]
        time_part = ""
        if len(parts) >= 3 and len(parts[1]) == 4 and parts[1].isdigit():
            time_part = f" {parts[1][:2]}:{parts[1][2:4]}"
            sort_key = f"{date}_{parts[1]}"
        else:
            sort_key = f"{date}_0000"
        return f"{date}{time_part}", sort_key
    return "", f"~{stem}"


def _counts_text(meta: dict[str, Any]) -> str:
    counts = meta.get("counts") or {}
    if not isinstance(counts, dict):
        return ""
    parts = []
    jd = counts.get("jd_samples") or counts.get("jd")
    cases = counts.get("cases")
    success = counts.get("success")
    failed = counts.get("source_fail")
    if jd:
        parts.append(f"{jd} 条岗位")
    if cases:
        parts.append(f"{cases} 条案例")
    if success is not None:
        parts.append(f"{success} 个来源可用")
    if failed:
        parts.append(f"{failed} 个源失败")
    return " · ".join(str(p) for p in parts)


def _rel_href(target: Path, root: Path) -> str:
    rel = target.relative_to(root).as_posix()
    return urllib.parse.quote(rel, safe="/")


def collect_profile_assets(profile_dir: Path, root: Path) -> list[AssetItem]:
    """扫描一个档案的资产目录，产出卡片列表（含伴生 json 的 meta 数字）。"""
    items: list[AssetItem] = []
    for kind, dirname in ASSETS_KIND_DIRS.items():
        sub_dir = profile_dir / dirname
        if not sub_dir.is_dir():
            continue
        for path in sorted(sub_dir.iterdir()):
            if path.suffix.lower() not in (".html", ".md"):
                continue
            meta: dict[str, Any] = {}
            json_path = path.with_suffix(".json")
            if json_path.exists():
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        meta = data
                except (OSError, ValueError):
                    meta = {}
            display_time, sort_key = _parse_when(path.stem)
            if not display_time:
                stat = path.stat()
                display_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                sort_key = "~" + str(int(stat.st_mtime))
            extras: dict[str, str] = {}
            title = meta.get("direction") or path.stem
            for suffix, label in ((".md", "md"), (".json", "json")):
                sibling = path.with_suffix(suffix)
                if sibling.exists() and sibling != path:
                    extras[label] = _rel_href(sibling, root)
            items.append(
                AssetItem(
                    kind=kind,
                    title=str(title),
                    when=display_time,
                    sort_key=sort_key,
                    rel_href=_rel_href(path, root),
                    counts_text=_counts_text(meta),
                    extras=extras,
                )
            )
    items.sort(key=lambda it: it.sort_key, reverse=True)
    return items


_INDEX_CSS = """
:root { --ink:#1f2430; --muted:#6b7280; --line:#e5e7eb; --bg:#f6f7fb; --card:#ffffff;
        --accent:#2563eb; }
* { box-sizing:border-box; }
body { margin:0; font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
       color:var(--ink); background:var(--bg); }
header { padding:28px 20px 8px; max-width:960px; margin:0 auto; }
header h1 { margin:0 0 6px; font-size:24px; }
header .sub { margin:0; color:var(--muted); font-size:13px; }
main { max-width:960px; margin:12px auto 40px; padding:0 20px; }
section.profile { margin:22px 0; }
section.profile > h2 { font-size:16px; margin:18px 0 10px; color:var(--muted); }
.cards { display:grid; gap:12px; }
a.card { display:block; background:var(--card); border:1px solid var(--line);
         border-radius:10px; padding:14px 16px; text-decoration:none; color:inherit;
         transition:border-color .15s, transform .15s; }
a.card:hover { border-color:var(--accent); transform:translateY(-1px); }
.card .badge { display:inline-block; font-size:12px; color:#fff; background:var(--accent);
               border-radius:6px; padding:2px 8px; margin-right:8px; }
.card.kind-analysis .badge { background:#7c3aed; }
.card.kind-roadmap .badge { background:#0891b2; }
.card.kind-progress .badge { background:#65a30d; }
.card .title { font-weight:600; font-size:15px; }
.card .meta { display:block; margin-top:6px; font-size:12.5px; color:var(--muted); }
.card .extras { display:block; margin-top:4px; font-size:12px; color:var(--accent); }
.empty { padding:40px 0; color:var(--muted); font-size:14px; text-align:center; }
footer { max-width:960px; margin:0 auto 30px; padding:0 20px; color:var(--muted);
         font-size:12px; }
"""

_INDEX_EMPTY = (
    "还没有产出。在下一次对话里发起调研或规划，报告、路线图、仪表盘会出现在这里。"
)


def render_index(groups: list[tuple[str, list[AssetItem]]], generated_at: str) -> str:
    """渲染资产中心 HTML（groups：按档案分组的卡片）。"""
    if not any(items for _, items in groups):
        body = f'<p class="empty">{escape(_INDEX_EMPTY)}</p>'
    else:
        sections = []
        for profile_label, items in groups:
            if not items:
                continue
            cards = []
            for it in items:
                extras = ""
                if it.extras:
                    links = " · ".join(
                        f'<a href="{escape(href)}">{escape(label)}</a>'
                        for label, href in it.extras.items()
                    )
                    extras = f'<span class="extras">就地查看：{links}</span>'
                meta_line = f" {escape(it.when)}" + (f" · {escape(it.counts_text)}" if it.counts_text else "")
                cards.append(
                    f'<a class="card kind-{escape(it.kind)}" href="{escape(it.rel_href)}">'
                    f'<span class="badge">{escape(_KIND_LABELS.get(it.kind, it.kind))}</span>'
                    f'<span class="title">{escape(it.title)}</span>'
                    f'<span class="meta">{meta_line}</span>'
                    f"{extras}"
                    f"</a>"
                )
            sections.append(
                f'<section class="profile"><h2>{escape(profile_label)}</h2>'
                f'<div class="cards">{"".join(cards)}</div></section>'
            )
        body = "".join(sections)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>Career Kit 资产中心</title>"
        f"<style>{_INDEX_CSS}</style></head><body>"
        "<header><h1>Career Kit 资产中心</h1>"
        '<p class="sub">全部产出由真实抓取数据生成，每条附来源链接，可逐条验证'
        f" · 更新于 {escape(generated_at)}</p></header>"
        f"<main>{body}</main>"
        "<footer>程序数据与缓存位于 ~/.career-kit；本目录全部为查看用资产，"
        "可随时移动或删除，未来的产出会自动回到这里。</footer>"
        "</body></html>"
    )


def rebuild_index() -> Path:
    """扫描资产根，重建 index.html（幂等）。"""
    root = ensure_assets_root()
    groups: list[tuple[str, list[AssetItem]]] = []
    for profile_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        items = collect_profile_assets(profile_dir, root)
        if items:
            groups.append((profile_dir.name, items))
    html = render_index(groups, datetime.now().strftime("%Y-%m-%d %H:%M"))
    index_path = root / INDEX_FILENAME
    index_path.write_text(html, encoding="utf-8")
    return index_path


def _readme_text() -> str:
    kind_lines = "\n".join(
        f"- {dirname}/：{_KIND_DESC[kind]}"
        for kind, dirname in ASSETS_KIND_DIRS.items()
    )
    return f"""# Career Kit 资产目录

这里是 Career Kit 为你生成的全部可查看产出，与程序数据（~/.career-kit）相互独立。

## 怎么用

- **双击 index.html 是总入口**：调研报告、差距分析、路线图、进度仪表盘全在卡片里，点开直达
- 每个子目录按你的档案分文件夹；报告文件名带日期，多次生成各自留档，不互相覆盖
- 「路线图.html」「进度仪表盘.html」固定文件名，重新生成即更新为最新版
  （交互地图的打卡记录存在浏览器本地，按文件路径续上，升级/重生成不丢）

## 每个目录装什么

{kind_lines}

## 来源声明

Career Kit 的报告数据全部来自实时抓取与本地知识库，每条附来源链接；
未获取到的内容会明确标注「未获取」，不用 AI 记忆编造。

本目录可随时移动或删除，不影响档案数据；后续产出会自动回到这里。
"""

_KIND_DESC: dict[str, str] = {
    "research": "真实岗位 JD + 同学历成功经历（md 可读全文，html 好看，json 是原始数据）",
    "analysis": "差距分析结论（带依据与来源）",
    "roadmap": "可交互打卡的职业地图（固定名，永远是最新版）",
    "progress": "进度仪表盘快照（固定名，永远是最新版）",
}
