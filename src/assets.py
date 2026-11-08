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
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from html import escape, unescape
from pathlib import Path
from typing import Any

# kind → 中文子目录名（契约：改这里必须同步迁移旧文件与测试）
ASSETS_KIND_DIRS: dict[str, str] = {
    "research": "调研报告",
    "analysis": "差距分析",
    "roadmap": "路线图",
    "progress": "进度",
    "evidence": "证据池",
    "applications": "投递清单",
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
    "evidence": "证据池",
    "applications": "投递清单",
}

# 固定名资产没有文件名主题，用可读标题替代主干
_KIND_FIXED_TITLES: dict[str, str] = {
    "roadmap": "职业地图",
    "progress": "进度仪表盘",
}

# 子页面自带的摘要（<meta name="career-kit-summary" content="...">）
_SUMMARY_RE = re.compile(
    r'<meta\s+name="career-kit-summary"\s+content="([^"]*)"', re.IGNORECASE
)

# 职业地图的版本标记：baseline=基线方案，execution=已按企业需求校准的执行版
_PLAN_MODE_RE = re.compile(
    r'<meta\s+name="career-kit-plan-mode"\s+content="([^"]*)"', re.IGNORECASE
)

# 规划链路：顺序即产品链路，缺哪一步就提示下一步做什么，不生成空文件
PLAN_CHAIN_LABELS: tuple[str, ...] = (
    "基线方案",
    "目标企业",
    "证据池",
    "企业需求",
    "执行版",
    "投递清单",
)
PLAN_CHAIN_STEPS: tuple[tuple[str, str], ...] = (
    ("baseline", "基线方案"),
    ("companies", "目标企业"),
    ("evidence", "证据池"),
    ("requirement", "企业需求"),
    ("execution", "执行版"),
    ("applications", "投递清单"),
)


def get_assets_root() -> Path:
    """用户资产根目录：环境变量优先，否则 ~/CareerKit。"""
    env = os.environ.get("CAREER_KIT_ASSETS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
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
    """生成留档文件名主干：日期_方向；同日同目录撞名时自动降级到 时分/序号。"""
    now = now or datetime.now()
    # 统一带 HHMM：同一天重跑不会出现「无时间 / 有时分」两套命名（P2-3）；
    # 同一分钟重跑用序号区分，旧报告仍保留可追溯。
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
    sort_key: float  # 排序时间戳（文件名内日期或 mtime）
    rel_href: str
    counts_text: str = ""
    extras: dict[str, str] = field(default_factory=dict)  # 附属文件 {标签: 相对链接}
    counts: dict[str, Any] = field(default_factory=dict)  # 报告 counts（链路展示用）
    plan_mode: str = ""  # roadmap: baseline / execution


def _parse_when(stem: str) -> tuple[str, float | None]:
    """从文件名主干解析 (展示时间, 排序时间戳)；解析不了返回空值与 None。"""
    parts = stem.split("_")
    if len(parts) >= 2 and len(parts[0]) == 10 and parts[0][:4].isdigit():
        date = parts[0]
        hhmm = "0000"
        time_part = ""
        if len(parts) >= 3 and len(parts[1]) == 4 and parts[1].isdigit():
            hhmm = parts[1]
            time_part = f" {hhmm[:2]}:{hhmm[2:4]}"
        try:
            ts = datetime.strptime(date + hhmm, "%Y-%m-%d%H%M").timestamp()
        except ValueError:
            ts = None
        return f"{date}{time_part}", ts
    return "", None


def _read_html_summary(path: Path | None) -> str:
    """读取生成页内嵌的摘要 meta（无则返回空串）。"""
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    match = _SUMMARY_RE.search(text[:4096])
    return unescape(match.group(1)).strip() if match else ""


def _read_plan_mode(path: Path | None) -> str:
    """读取职业地图的版本标记（无标记的旧文件按基线方案处理）。"""
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    match = _PLAN_MODE_RE.search(text[:4096])
    return match.group(1).strip().lower() if match else ""


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
    """扫描一个档案的资产目录，按文件主干聚合为卡片。

    同一份产出通常有 html / md / json 三个文件：只出一张卡（html 优先，
    md 兜底），其余作为附件链接，避免重复卡片。
    """
    items: list[AssetItem] = []
    for kind, dirname in ASSETS_KIND_DIRS.items():
        sub_dir = profile_dir / dirname
        if not sub_dir.is_dir():
            continue
        grouped: dict[str, dict[str, Path]] = {}
        for path in sub_dir.iterdir():
            suffix = path.suffix.lower()
            if suffix not in (".html", ".md", ".json"):
                continue
            grouped.setdefault(path.stem, {})[suffix] = path
        for stem, files in grouped.items():
            primary = files.get(".html") or files.get(".md")
            if primary is None:
                continue
            meta: dict[str, Any] = {}
            json_path = files.get(".json")
            if json_path is not None:
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        meta = data
                except (OSError, ValueError):
                    meta = {}
            display_time, sort_ts = _parse_when(stem)
            if not display_time or sort_ts is None:
                stat = primary.stat()
                display_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                sort_ts = stat.st_mtime
            extras: dict[str, str] = {}
            title = meta.get("direction") or _KIND_FIXED_TITLES.get(kind) or stem
            for suffix, label in ((".md", "md"), (".json", "json")):
                sibling = files.get(suffix)
                if sibling is not None and sibling != primary:
                    extras[label] = _rel_href(sibling, root)
            counts_text = _counts_text(meta) or _read_html_summary(files.get(".html"))
            counts = meta.get("counts") if isinstance(meta.get("counts"), dict) else {}
            plan_mode = _read_plan_mode(files.get(".html")) if kind == "roadmap" else ""
            items.append(
                AssetItem(
                    kind=kind,
                    title=str(title),
                    when=display_time,
                    sort_key=sort_ts,
                    rel_href=_rel_href(primary, root),
                    counts_text=counts_text,
                    extras=extras,
                    counts=dict(counts),
                    plan_mode=plan_mode,
                )
            )
    items.sort(key=lambda it: float(it.sort_key), reverse=True)
    return items


def _latest_asset(items: list[AssetItem], kind: str) -> AssetItem | None:
    matches = [item for item in items if item.kind == kind]
    return max(matches, key=lambda item: float(item.sort_key), default=None)


def _int_count(counts: dict[str, Any], *keys: str) -> int:
    for key in keys:
        try:
            value = int(counts.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return value
    return 0


def _plan_chain_rows(items: list[AssetItem]) -> list[dict[str, Any]]:
    """按文件事实推导规划链路状态；没有对应文件时只给下一步，不造链接。"""
    roadmap = _latest_asset(items, "roadmap")
    evidence = _latest_asset(items, "evidence")
    applications = _latest_asset(items, "applications")
    analysis = _latest_asset(items, "analysis")
    execution = roadmap is not None and roadmap.plan_mode == "execution"
    companies = (
        _int_count(evidence.counts, "companies_requested", "companies_fetched")
        if evidence
        else 0
    )

    rows: list[dict[str, Any]] = []

    def add(key: str, status: str, detail: str, asset: AssetItem | None = None) -> None:
        rows.append(
            {
                "key": key,
                "label": dict(PLAN_CHAIN_STEPS)[key],
                "status": status,
                "detail": detail,
                "asset": asset,
            }
        )

    if roadmap:
        add("baseline", "done", f"路线图已生成（{roadmap.when}）", roadmap)
    elif analysis:
        add("baseline", "next", "差距分析已完成，下一步生成基线路线图")
    else:
        add("baseline", "todo", "先完成建档与差距分析，再生成基线路线图")

    if evidence:
        detail = (
            f"证据池覆盖目标企业 {companies} 家"
            if companies
            else "已确认目标企业并进入证据采集"
        )
        add("companies", "done", detail)
    elif roadmap:
        add("companies", "next", "先做企业适配：筛选并确认目标企业池")
    else:
        add("companies", "todo", "基线方案就绪后，再筛选目标企业")

    if evidence:
        jd = _int_count(evidence.counts, "jd_samples", "kept_jobs", "jd")
        cases = _int_count(evidence.counts, "cases", "interviews")
        detail = f"已采集 JD {jd} 条 · 面经 {cases} 条"
        add("evidence", "done", detail, evidence)
    elif roadmap:
        add("evidence", "next", "先采集目标企业的岗位 JD 与面经证据")
    else:
        add("evidence", "todo", "目标企业确认后，再采集证据")

    if execution:
        add("requirement", "done", "需求画像已用于执行版校准（数据保存在档案）")
    elif evidence:
        add("requirement", "next", "先做企业需求分析并保存需求画像")
    else:
        add("requirement", "todo", "证据池完成后，再分析企业需求")

    if execution:
        add("execution", "done", "执行版路线图：已按确认企业与 JD 需求校准", roadmap)
    elif roadmap:
        add("execution", "next", "当前是基线方案，下一步按企业需求校准执行版")
    else:
        add("execution", "todo", "基线方案完成后，才能生成执行版")

    if applications:
        add("applications", "done", f"投递清单已生成（{applications.when}）", applications)
    elif execution:
        add("applications", "next", "先做企业适配并生成投递清单")
    else:
        add("applications", "todo", "执行版就绪后，再生成投递清单")

    return rows


def _render_plan_chain(items: list[AssetItem]) -> str:
    rows = []
    for index, row in enumerate(_plan_chain_rows(items), start=1):
        asset = row["asset"]
        link = (
            f'<a href="{escape(asset.rel_href)}">打开</a>' if asset is not None else ""
        )
        rows.append(
            f'<li class="chain-step {escape(row["status"])}">'
            f'<span class="chain-no">{index}</span>'
            f'<span class="chain-label">{escape(row["label"])}</span>'
            f'<span class="chain-detail">{escape(row["detail"])}</span>'
            f"{link}</li>"
        )
    return (
        '<div class="chain"><div class="chain-title">规划链路'
        '<span class="chain-sub">基线方案 → 目标企业 → 证据池 → 企业需求 → '
        '执行版 → 投递清单</span></div>'
        f'<ol class="chain-steps">{"".join(rows)}</ol></div>'
    )


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
.chain { background:var(--card); border:1px solid var(--line); border-radius:10px;
         padding:12px 16px; margin-bottom:12px; }
.chain-title { font-weight:600; font-size:14px; }
.chain-sub { display:block; margin-top:4px; color:var(--muted); font-size:12px; }
.chain-steps { list-style:none; margin:10px 0 0; padding:0; display:grid; gap:6px; }
.chain-step { display:flex; align-items:baseline; gap:10px; font-size:13px;
              padding:6px 8px; border-radius:8px; background:#fafbfe; }
.chain-no { width:20px; height:20px; border-radius:50%; flex:0 0 20px;
            display:inline-grid; place-items:center; font-size:11px;
            color:var(--muted); background:var(--line); }
.chain-label { font-weight:600; min-width:64px; }
.chain-detail { flex:1; color:var(--muted); }
.chain-step.done .chain-no { background:#dcfce7; color:#15803d; }
.chain-step.done .chain-label { color:#15803d; }
.chain-step.next { background:#eff6ff; }
.chain-step.next .chain-no { background:var(--accent); color:#fff; }
.chain-step.next .chain-label { color:var(--accent); }
.chain-step.todo .chain-label { color:var(--muted); }
.chain-step a { color:var(--accent); text-decoration:none; flex:0 0 auto; }
.chain-step a:hover { text-decoration:underline; }
.cards { display:grid; gap:12px;
         grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); }
.card { display:flex; flex-direction:column; background:var(--card);
        border:1px solid var(--line); border-radius:10px; overflow:hidden;
        transition:border-color .15s, transform .15s; }
.card:hover { border-color:var(--accent); transform:translateY(-1px); }
.card .badge { display:inline-block; font-size:12px; color:#fff; background:var(--accent);
               border-radius:6px; padding:2px 8px; margin-right:8px; }
.card.kind-research .badge { background:#0d9488; }
.card.kind-analysis .badge { background:#7c3aed; }
.card.kind-roadmap .badge { background:#0891b2; }
.card.kind-progress .badge { background:#65a30d; }
.card.kind-evidence .badge { background:#b45309; }
a.card-main { display:block; flex:1; padding:14px 16px 8px; text-decoration:none;
              color:inherit; border-radius:10px; }
a.card-main:focus-visible, .card .extras a:focus-visible {
  outline:2px solid var(--accent); outline-offset:2px; }
.card .title { display:block; font-weight:600; font-size:15px; }
.card .meta { display:block; margin-top:6px; font-size:12.5px; color:var(--muted); }
.card .extras { display:flex; align-items:center; flex-wrap:wrap; gap:10px;
                padding:0 16px 12px; font-size:12px; color:var(--muted); }
.card .extras a { color:var(--accent); text-decoration:none; }
.card .extras a:hover { text-decoration:underline; }
.empty { padding:40px 0; color:var(--muted); font-size:14px; text-align:center; }
footer { max-width:960px; margin:0 auto 30px; padding:0 20px; color:var(--muted);
         font-size:12px; }
@media (max-width:640px) {
  header { padding:20px 14px 6px; }
  main { padding:0 14px; }
  .cards { grid-template-columns:1fr; }
}
"""

_INDEX_EMPTY = (
    "还没有产出。在下一次对话里发起调研或规划，报告、路线图、仪表盘会出现在这里；"
    "规划链路（基线方案 → 目标企业 → 证据池 → 企业需求 → 执行版 → 投递清单）"
    "会随产出逐步点亮。"
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
                    links = "".join(
                        f'<a href="{escape(href)}">{escape(label)}</a>'
                        for label, href in it.extras.items()
                    )
                    extras = f'<div class="extras"><span>附件</span>{links}</div>'
                meta_line = escape(it.when) + (
                    f" · {escape(it.counts_text)}" if it.counts_text else ""
                )
                cards.append(
                    f'<div class="card kind-{escape(it.kind)}">'
                    f'<a class="card-main" href="{escape(it.rel_href)}">'
                    f'<span class="badge">{escape(_KIND_LABELS.get(it.kind, it.kind))}</span>'
                    f'<span class="title">{escape(it.title)}</span>'
                    f'<span class="meta">{meta_line}</span>'
                    f"</a>{extras}</div>"
                )
            sections.append(
                f'<section class="profile"><h2>{escape(profile_label)}</h2>'
                f'{_render_plan_chain(items)}'
                f'<div class="cards">{"".join(cards)}</div></section>'
            )
        body = "".join(sections)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Career Kit 资产中心</title>"
        f"<style>{_INDEX_CSS}</style></head><body>"
        "<header><h1>Career Kit 资产中心</h1>"
        '<p class="sub">全部产出由真实抓取数据生成，每条附来源链接，可逐条验证'
        " · 规划链路：基线方案 → 目标企业 → 证据池 → 企业需求 → 执行版 → 投递清单"
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

## 规划链路

资产不是一堆散文件，而是沿着一条链路逐步产生的（index.html 顶部会显示每一步的状态）：

1. **基线方案**：差距分析后生成的职业路线图（先有阶段，再按真实需求校准）
2. **目标企业**：筛选并确认的目标企业池（证据池报告会记录抓取范围）
3. **证据池**：目标企业的真实岗位 JD 与面经
4. **企业需求**：从证据池统计出的需求画像（保存于档案，用于校准执行版，不单独落文件）
5. **执行版**：按确认企业/JD 需求校准后的路线图（覆盖同名「路线图.html」，地图会标注「执行版」）
6. **投递清单**：按城市硬筛、方向与技能打分的投递候选

缺失的环节不会生成空文件；index.html 会直接显示下一步该做什么。

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
    "evidence": "目标企业 JD 与面经证据池（带来源、样本量与置信度）",
    "applications": "按城市硬筛、按方向与技能打分的投递候选清单（带匹配分与缺口）",
}
