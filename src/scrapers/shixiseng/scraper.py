"""实习僧（shixiseng.com）实习岗位 Scraper。

数据源：第三方实习聚合平台，匿名访问公开列表与详情页。
列表页与详情页均为 SSR，直接解析公开 HTML，不登录、不绕过验证码。

返回字段按 Career Kit 的 JD 规范：
- search: title / url / company / location / salary / summary / department / job_type
- get_detail: title / company / location / salary / description / requirements / benefits
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any
from urllib.parse import urlsplit

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client
from .font_map import PUA_MAP

BASE_URL = "https://www.shixiseng.com"
SEARCH_URL = f"{BASE_URL}/interns"
REFERER = f"{BASE_URL}/interns?type=intern"

# 站点用 iconfont 私有区字符渲染部分汉字与数字；只剥离，不解析字体映射。
_PUA_RE = re.compile(r"[\ue000-\uf8ff\ufffd]")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")

_TITLE_RE = re.compile(
    r'<a[^>]+class="[^"]*\btitle\b[^"]*\bfont\b[^"]*"[^>]*>(.*?)</a>', re.S
)
_COMPANY_RE = re.compile(
    r'<a\s+title="([^"]*)"\s+href="javascript:;"\s+class="title ellipsis"', re.S
)
_CITY_RE = re.compile(r'<span class="city ellipsis"[^>]*>(.*?)</span>', re.S)
_SALARY_RE = re.compile(r'<span class="day font"[^>]*>(.*?)</span>', re.S)
_INDUSTRY_RE = re.compile(
    r'<p class="tip"[^>]*>\s*<span class="ellipsis"[^>]*>(.*?)</span>', re.S
)

_DETAIL_TITLE_RE = re.compile(
    r'<div class="new_job_name"[^>]*>\s*<span[^>]*>(.*?)</span>', re.S
)
_DETAIL_COMPANY_RE = re.compile(
    r'<a[^>]+class="[^"]*\bcom-name\b[^"]*"[^>]*>(.*?)</a>', re.S
)
_DETAIL_REFRESH_RE = re.compile(
    r'<div class="job_date"[^>]*>\s*<span[^>]*>(.*?)</span>', re.S
)
_DETAIL_SALARY_RE = re.compile(r'<span class="job_money[^"]*"[^>]*>(.*?)</span>', re.S)
_DETAIL_CITY_RE = re.compile(
    r'<span title="[^"]*" class="job_position"[^>]*>(.*?)</span>', re.S
)
_DETAIL_DEGREE_RE = re.compile(
    r'<span class="job_academic"[^>]*>(.*?)</span>', re.S
)
_DETAIL_ADDRESS_RE = re.compile(
    r'<span class="com_position"[^>]*>(.*?)</span>', re.S
)
_DETAIL_DESCRIPTION_RE = re.compile(
    r'<div class="job_detail"[^>]*>(.*?)</div>', re.S
)
_DETAIL_BENEFITS_RE = re.compile(
    r'<div class="job_good_list"[^>]*>(.*?)</div>', re.S
)
_DEADLINE_RE = re.compile(r"截止日期[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """实习僧 Scraper。"""

    COMPANY_SLUG = "shixiseng"
    DATA_TYPE = "jds"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": True, "description": "搜索关键词，如 \"量化\"、\"投行\"、\"中金\""},
        "city": {"required": False, "description": "城市名，如 \"北京\"、\"上海\"；默认全国"},
        "page": {"required": False, "description": "页码，默认 1"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    search_cache_ttl = 3600
    detail_cache_ttl = 86400

    def supports_url(self, url: str) -> bool:
        return "shixiseng.com" in url and "/intern/" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = str(kwargs.get("keyword") or "").strip()
        city = str(kwargs.get("city") or "").strip() or "全国"
        page = max(1, int(kwargs.get("page") or 1))
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        if not keyword:
            return [{"error": "实习僧搜索需要提供 keyword（如 \"量化\"、\"投行\"）"}]

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, page=page)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._fetch_jobs(keyword, city, page, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"不是实习僧岗位 URL：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        result = self._fetch_detail(url)
        if result.get("error") and url in _FALLBACK:
            result = dict(_FALLBACK[url])
            result["url"] = url
            result["_note"] = "详情页暂不可用，以下信息来自列表页快照"
        if not result.get("error"):
            cache.set(key, result)
        return result

    def _fetch_jobs(
        self, keyword: str, city: str, page: int, limit: int
    ) -> list[dict[str, Any]]:
        params = {
            "type": "intern",
            "keyword": keyword,
            "publishTime": "mon",
            "city": city,
            "page": str(page),
        }
        try:
            page_html = _fetch_html(SEARCH_URL, params)
        except ScraperHttpError as exc:
            return [{"error": f"实习僧搜索页抓取失败：{exc}"}]

        results = _parse_nuxt_jobs(page_html)
        if not results:
            for chunk in page_html.split('data-intern-id="')[1:]:
                item = _parse_card(chunk)
                if item:
                    results.append(item)
        results = _dedupe(results)[:limit]
        for item in results:
            _remember(item)

        if not results:
            return [
                {
                    "error": (
                        f"未找到与「{keyword}」相关的实习岗位"
                        "（实习僧只展示近一月刷新的实习；可换关键词或城市重试）"
                    ),
                    "keyword": keyword,
                    "city": city,
                }
            ]
        return results

    def _fetch_detail(self, url: str) -> dict[str, Any]:
        clean_url = _strip_query(url)
        try:
            page_html = _fetch_html(clean_url, None)
        except ScraperHttpError as exc:
            return {"error": f"实习僧详情页抓取失败：{exc}", "url": url}

        nuxt_detail = _parse_nuxt_detail(page_html)
        if nuxt_detail:
            nuxt_detail["url"] = url
            return nuxt_detail

        title = _clean_text(_first(_DETAIL_TITLE_RE, page_html))
        company = _clean_text(_first(_DETAIL_COMPANY_RE, page_html))
        if not company:
            company = str((_FALLBACK.get(url) or {}).get("company") or "")
        if not title and not company:
            return {"error": "详情页结构已变化，未解析到岗位信息", "url": url}

        description = _block_text(_first(_DETAIL_DESCRIPTION_RE, page_html))
        requirements = _requirements_text(page_html)
        benefits = _span_texts(_first(_DETAIL_BENEFITS_RE, page_html))
        salary = _clean_salary(_first(_DETAIL_SALARY_RE, page_html))
        city = _clean_text(_first(_DETAIL_CITY_RE, page_html))
        address = _clean_text(_first(_DETAIL_ADDRESS_RE, page_html))
        degree = _clean_text(_first(_DETAIL_DEGREE_RE, page_html))
        refresh = _clean_text(_first(_DETAIL_REFRESH_RE, page_html))

        if not description and not requirements:
            return {
                "error": "详情页未解析到岗位描述（可能需登录或页面改版）",
                "url": url,
            }

        detail = {
            "title": title,
            "company": company,
            "location": city,
            "address": address,
            "salary": salary,
            "degree": degree,
            "description": description,
            "requirements": requirements,
            "benefits": benefits,
            "job_type": "实习",
            "source": "shixiseng",
            "url": url,
            "updated_at": refresh,
        }
        return {key: value for key, value in detail.items() if value}


def _fetch_html(url: str, params: dict[str, str] | None) -> str:
    with make_client(timeout=30.0) as client:
        response = client.get(url, params=params, headers={"Referer": REFERER})
    if response.status_code >= 400:
        raise ScraperHttpError(f"HTTP {response.status_code}: {url}")
    response.encoding = "utf-8"
    return response.text


def _parse_card(chunk: str) -> dict[str, Any] | None:
    job_id = chunk.split('"', 1)[0].strip()
    if not job_id.startswith("inn_"):
        return None

    title = _clean_text(_first(_TITLE_RE, chunk))
    company = _clean_text(_first(_COMPANY_RE, chunk))
    if not title or not company:
        return None

    city = _clean_text(_first(_CITY_RE, chunk))
    salary = _clean_salary(_first(_SALARY_RE, chunk))
    industry = _clean_text(_first(_INDUSTRY_RE, chunk))
    url = f"{BASE_URL}/intern/{job_id}"

    summary_parts = [part for part in (industry, salary) if part]
    return {
        "title": title,
        "url": url,
        "company": company,
        "location": city,
        "salary": salary,
        "department": industry,
        "summary": " · ".join(summary_parts),
        "job_type": "实习",
        "job_id": job_id,
        "source": "shixiseng",
    }


def _parse_nuxt_jobs(page_html: str) -> list[dict[str, Any]]:
    """解析列表页 SSR 内嵌的 __NUXT__ 数据。

    列表卡片里的薪资、周天、月数被自定义字体转成私有区字符，但 Nuxt 数据里
    保留了明文 minsalary / maxsalary 与技能标签 i_tags，可直接复用。
    解析失败时返回空列表，回退 HTML 卡片。
    """
    context = _nuxt_context(page_html)
    if context is None:
        return []
    var_map, body, _ = context
    data_at = body.find("interns:{data:[")
    if data_at < 0:
        return []
    array_open = body.find("[", data_at)
    array_close = _matching(body, array_open, "[", "]")
    if array_open < 0 or array_close < 0:
        return []

    jobs: list[dict[str, Any]] = []
    for chunk in _split_objects(body[array_open + 1 : array_close]):
        job = _nuxt_job(chunk, var_map)
        if job:
            jobs.append(job)
    return jobs


def _parse_nuxt_detail(page_html: str) -> dict[str, Any] | None:
    """解析详情页 __NUXT__ 的 internInfo，优先于 HTML 正则。"""
    context = _nuxt_context(page_html)
    if context is None:
        return None
    var_map, body, inner = context
    chunk = _nuxt_detail_chunk(body, inner)
    if not chunk:
        return None

    title = _clean_text(str(_resolve(_raw_field(chunk, "iname"), var_map) or ""))
    company = _clean_text(str(_resolve(_raw_field(chunk, "cname"), var_map) or ""))
    description = _block_text(str(_resolve(_raw_field(chunk, "info"), var_map) or ""))
    if not title or not description:
        return None

    requirements = _block_text(
        str(_resolve(_raw_field(chunk, "job_requirements"), var_map) or "")
    )
    if not requirements:
        requirements = _requirement_section(description)

    detail = {
        "title": title,
        "company": company,
        "location": _clean_text(str(_resolve(_raw_field(chunk, "city"), var_map) or "")),
        "address": _clean_text(str(_resolve(_raw_field(chunk, "address"), var_map) or "")),
        "salary": _clean_text(str(_resolve(_raw_field(chunk, "salary_desc"), var_map) or "")),
        "degree": _clean_text(str(_resolve(_raw_field(chunk, "degree"), var_map) or "")),
        "education": _clean_text(str(_resolve(_raw_field(chunk, "degree"), var_map) or "")),
        "industry": _clean_text(str(_resolve(_raw_field(chunk, "industry"), var_map) or "")),
        "weekly_days": _to_int(_resolve(_raw_field(chunk, "day"), var_map)),
        "duration_months": _to_int(_resolve(_raw_field(chunk, "month"), var_map)),
        "deadline": _clean_text(str(_resolve(_raw_field(chunk, "endtime"), var_map) or "")),
        "chance": _clean_text(str(_resolve(_raw_field(chunk, "chance"), var_map) or "")),
        "description": description,
        "requirements": requirements,
        "skills": _tag_values(chunk, "skills"),
        "tags": _tag_values(chunk, "attraction"),
        "job_type": "实习",
        "source": "shixiseng",
        "updated_at": _clean_text(str(_resolve(_raw_field(chunk, "refresh"), var_map) or "")),
    }
    return {key: value for key, value in detail.items() if value}


def _nuxt_detail_chunk(body: str, inner: str) -> str:
    """取出详情页 internInfo 对象；兼容内联对象与 `internInfo:g` 引用两种写法。"""
    info_at = body.find("internInfo:{")
    if info_at >= 0:
        object_start = body.find("{", info_at)
        object_end = _matching(body, object_start, "{", "}")
        if object_start >= 0 and object_end >= 0:
            return body[object_start : object_end + 1]

    match = re.search(r"\binternInfo:(\w+)", body)
    if not match:
        return ""
    fields = _assignment_fields(inner, match.group(1))
    if not fields:
        return ""
    return "{" + ",".join(f"{key}:{value}" for key, value in fields.items()) + "}"


def _assignment_fields(inner: str, var: str) -> dict[str, str]:
    """解析 `g.field=value;` 形式的变量赋值，返回字段 -> 原始 JS 值。"""
    fields: dict[str, str] = {}
    for match in re.finditer(rf"\b{re.escape(var)}\.(\w+)=", inner):
        value_start = match.end()
        end = _statement_end(inner, value_start)
        if end < 0:
            continue
        fields[match.group(1)] = inner[value_start:end].strip()
    return fields


def _statement_end(text: str, start: int) -> int:
    """从 start 找到顶层分号，跳过字符串与括号内部分号。"""
    depth = 0
    quote = ""
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue
        if char in ('"', "'"):
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == ";" and depth == 0:
            return index
    return -1


def _nuxt_context(page_html: str) -> tuple[dict[str, Any], str, str] | None:
    """提取 __NUXT__ 的变量映射、返回对象文本与函数体内部文本。"""
    nuxt = page_html.find("__NUXT__=")
    if nuxt < 0:
        return None
    params_start = page_html.find("(function(", nuxt)
    if params_start < 0:
        return None
    params_start += len("(function(")
    params_end = page_html.find(")", params_start)
    if params_end < 0:
        return None
    params = [p.strip() for p in page_html[params_start:params_end].split(",") if p.strip()]

    body_start = page_html.find("{", params_end)
    body_end = _matching(page_html, body_start, "{", "}")
    if body_start < 0 or body_end < 0:
        return None
    script_end = page_html.find("</script>", body_end)
    if script_end < 0:
        script_end = len(page_html)
    tail = page_html[body_end + 1 : script_end]
    open_paren = tail.find("(")
    close_paren = _matching(tail, open_paren, "(", ")")
    if open_paren < 0 or close_paren <= open_paren:
        return None
    args = [_parse_js_scalar(item) for item in _split_js_args(tail[open_paren + 1 : close_paren])]
    return (
        dict(zip(params, args, strict=False)),
        page_html[body_start : body_end + 1],
        page_html[body_start + 1 : body_end],
    )


def _nuxt_job(chunk: str, var_map: dict[str, Any]) -> dict[str, Any] | None:
    title = _clean_text(str(_resolve(_raw_field(chunk, "name"), var_map) or ""))
    company = _clean_text(str(_resolve(_raw_field(chunk, "cname"), var_map) or ""))
    job_id = _clean_text(str(_resolve(_raw_field(chunk, "uuid"), var_map) or ""))
    if not title or not company or not job_id.startswith("inn_"):
        return None

    city = _clean_text(str(_resolve(_raw_field(chunk, "city"), var_map) or ""))
    industry = _clean_text(str(_resolve(_raw_field(chunk, "industry"), var_map) or ""))
    degree = _clean_text(str(_resolve(_raw_field(chunk, "degree"), var_map) or ""))
    salary = _format_salary(
        _to_int(_resolve(_raw_field(chunk, "minsalary"), var_map)),
        _to_int(_resolve(_raw_field(chunk, "maxsalary"), var_map)),
    )
    tags = _tag_values(chunk, "i_tags")

    summary_parts = [industry]
    if degree:
        summary_parts.append(f"学历：{degree}")
    if tags:
        summary_parts.append("标签：" + "、".join(tags[:5]))

    return {
        "title": title,
        "url": f"{BASE_URL}/intern/{job_id}",
        "company": company,
        "location": city,
        "salary": salary,
        "department": industry,
        "degree": degree,
        "tags": tags,
        "summary": " · ".join(part for part in summary_parts if part),
        "job_type": "实习",
        "job_id": job_id,
        "source": "shixiseng",
    }


def _requirement_section(description: str) -> str:
    for marker in ("任职要求", "岗位要求", "任职资格", "职位要求"):
        index = description.find(marker)
        if index >= 0:
            return description[index + len(marker) :].lstrip("：: \n")
    return ""


def _raw_field(chunk: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}:(\"(?:[^\"\\]|\\.)*\"|[^,}}]+)", chunk)
    return match.group(1).strip() if match else ""


def _resolve(raw: str, var_map: dict[str, Any]) -> Any:
    if not raw:
        return ""
    if raw in var_map:
        return var_map[raw]
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw.strip('"')
    scalar = _parse_js_scalar(raw)
    return raw if scalar is None and raw not in {"null", "undefined", "void 0"} else scalar


def _tag_values(chunk: str, name: str) -> list[str]:
    match = re.search(rf"\b{re.escape(name)}:\[(.*?)\]", chunk, re.S)
    if not match:
        return []
    values = []
    for raw in re.findall(r'"(?:[^"\\]|\\.)*"', match.group(1)):
        value = _clean_text(str(_resolve(raw, {}) or ""))
        if value:
            values.append(value)
    return values


def _format_salary(low: int | None, high: int | None) -> str:
    if not low and not high:
        return ""
    low = low or high or 0
    high = high or low
    return f"{low}-{high}/天" if low != high else f"{low}/天"


def _to_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _matching(text: str, start: int, open_char: str, close_char: str) -> int:
    if start < 0 or start >= len(text) or text[start] != open_char:
        return -1
    depth = 0
    quote = ""
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue
        if char in ('"', "'"):
            quote = char
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_js_args(text: str) -> list[str]:
    items: list[str] = []
    buffer: list[str] = []
    depth = 0
    quote = ""
    escape = False
    for char in text:
        if quote:
            buffer.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue
        if char in ('"', "'"):
            quote = char
            buffer.append(char)
        elif char in "([{":
            depth += 1
            buffer.append(char)
        elif char in ")]}":
            depth -= 1
            buffer.append(char)
        elif char == "," and depth == 0:
            items.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
    if buffer:
        items.append("".join(buffer).strip())
    return [item for item in items if item]


def _parse_js_scalar(token: str) -> Any:
    token = token.strip()
    if token in ("null", "undefined", "void 0"):
        return None
    if token == "true":
        return True
    if token == "false":
        return False
    if token.startswith('"'):
        try:
            return json.loads(token)
        except (ValueError, TypeError):
            return token.strip('"')
    try:
        return int(token)
    except ValueError:
        try:
            return float(token)
        except ValueError:
            return token


def _split_objects(text: str) -> list[str]:
    objects: list[str] = []
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            break
        end = _matching(text, start, "{", "}")
        if end < 0:
            break
        objects.append(text[start : end + 1])
        index = end + 1
    return objects


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for row in rows:
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(row)
    return result


def _requirements_text(page_html: str) -> str:
    deadline = _DEADLINE_RE.search(page_html)
    parts: list[str] = []
    marker = page_html.find("投递要求")
    if marker >= 0:
        block = page_html[marker : marker + 1200]
        cut = block.find('<div class="con-job', 10)
        if cut > 0:
            block = block[:cut]
        text = _block_text(block)
        if text:
            parts.append(text)
    if deadline and "截止日期" not in "".join(parts):
        parts.append(f"截止日期：{deadline.group(1)}")
    return "\n".join(parts).strip()


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["url"]] = {
        "title": item.get("title", ""),
        "company": item.get("company", ""),
        "location": item.get("location", ""),
        "salary": item.get("salary", ""),
        "department": item.get("department", ""),
        "summary": item.get("summary", ""),
        "job_type": "实习",
        "source": "shixiseng",
    }


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    return match.group(1) if match else ""


def _block_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    text = _TAG_RE.sub("", text)
    text = _decode_pua(_html.unescape(text)).replace("\r", "")
    text = _PUA_RE.sub("", text)
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _span_texts(value: str) -> str:
    return "、".join(
        text
        for text in (_clean_text(item) for item in re.findall(r"<span[^>]*>(.*?)</span>", value or "", re.S))
        if text
    )


def _clean_text(value: str) -> str:
    text = _TAG_RE.sub("", value or "")
    text = _decode_pua(_html.unescape(text))
    text = _PUA_RE.sub("", text)
    return _SPACE_RE.sub(" ", text).strip()


def _clean_salary(value: str) -> str:
    """还原被自定义字体替换的数字；仍取不到数字时留空，不输出残缺文本。"""
    text = _TAG_RE.sub("", value or "")
    text = _decode_pua(_html.unescape(text))
    text = _PUA_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text).strip()
    if not re.search(r"\d", text) and not any(word in text for word in ("面议", "元", "万")):
        return ""
    return text


def _decode_pua(text: str) -> str:
    """按公开字体映射还原私有区字符；未知字符留给调用方剥离。"""
    if not text:
        return ""
    return "".join(PUA_MAP.get(char, char) for char in text)


def _strip_query(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
