"""Scraper 加载器——从 config.yaml 读取注册信息，动态加载 Scraper 实现。

框架层职责：
- 动态加载和缓存 Scraper 类
- 搜索/详情成功后自动写入知识库
- URL 路由：按 supports_url 匹配最合适的 Scraper
- 输出校验：确保 title 和 url 字段存在
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .base import CompanyScraper
from .catalog import company_for_scraper, get_company, tier_for_scraper
from .knowledge_writer import write_to_knowledge

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.yaml"
COMPANIES_PATH = Path(__file__).parent / "companies.yaml"

# 缓存已加载的 Scraper 类
_scraper_classes: dict[str, type[CompanyScraper]] = {}
_config: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    """加载 config.yaml。"""
    global _config
    if _config is None:
        if not CONFIG_PATH.exists():
            _config = {"scrapers": {}}
        else:
            raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = {}
            raw.setdefault("scrapers", {})
            if raw["scrapers"] is None:
                raw["scrapers"] = {}
            _config = raw
    return _config


@lru_cache(maxsize=1)
def _platform_aliases() -> dict[str, str]:
    """读取 companies.yaml 的 platforms 段：平台源（BOSS/牛客/GitHub）的别名。

    企业别名统一由 catalog.get_company 读取 companies.yaml 的 companies 段；
    平台不是企业，因此单独放在同一文件的 platforms 段，避免第二份别名表。
    """
    try:
        data = yaml.safe_load(COMPANIES_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    items = data.get("platforms") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}
    mapping: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        platform_id = str(item.get("id") or "").strip()
        if not platform_id:
            continue
        names = [platform_id, item.get("name"), *(item.get("aliases") or [])]
        for name in names:
            key = str(name or "").strip().lower()
            if key:
                mapping[key] = platform_id
    return mapping


def resolve_company_scrapers(identifier: str) -> list[str]:
    """别名 / 企业名 / 企业 id / scraper id → 该企业全部 scraper id。

    返回企业目录中的 ``available_scrapers``；平台与单源返回自身；
    未找到返回 ``[]``。别名可能对应多个数据源（如阿里校招 + 社招），
    查询多个来源时应使用本函数，而不是只看 primary。
    """
    raw = (identifier or "").strip()
    if not raw:
        return []
    key = raw.lower()

    company = get_company(raw)
    if company:
        available = company.get("available_scrapers") or []
        if available:
            return list(available)

    config = _load_config().get("scrapers", {})
    for scraper_id in config:
        if key == scraper_id.lower():
            return [scraper_id]
    for scraper_id, info in config.items():
        if key == str(info.get("name") or "").strip().lower():
            return [scraper_id]

    platform_id = _platform_aliases().get(key)
    if platform_id:
        return [platform_id]
    return []


def resolve_company(identifier: str) -> str:
    """别名 / 企业名 / 企业 id / scraper id → primary scraper id（唯一解析入口）。

    顺序：注册表 id → 注册表显示名 → 平台别名（companies.yaml platforms）→
    企业目录（companies.yaml + catalog.get_company 的 id/名称/别名/scraper）。
    解析不到时原样返回，交由调用方给出「未找到 Scraper」的真实错误。
    需要企业全部数据源时改用 resolve_company_scrapers。
    """
    raw = (identifier or "").strip()
    if not raw:
        return ""
    key = raw.lower()
    config = _load_config().get("scrapers", {})

    for scraper_id in config:
        if key == scraper_id.lower():
            return scraper_id
    for scraper_id, info in config.items():
        if key == str(info.get("name") or "").strip().lower():
            return scraper_id

    platform_id = _platform_aliases().get(key)
    if platform_id:
        return platform_id

    company = get_company(raw)
    if company:
        available = company.get("available_scrapers") or []
        if available:
            return available[0]
    return raw


def _load_scraper_class(company: str) -> type[CompanyScraper] | None:
    """动态加载指定公司的 Scraper 类。"""
    if company in _scraper_classes:
        return _scraper_classes[company]

    config = _load_config()
    scraper_config = config.get("scrapers", {}).get(company)
    if not scraper_config:
        return None

    module_path = scraper_config.get("module", "")
    class_name = scraper_config.get("class", "Scraper")

    if not module_path:
        return None

    try:
        if not module_path.startswith("src."):
            full_path = f"src.scrapers.{module_path}" if module_path else ""
        else:
            full_path = module_path
        module = importlib.import_module(full_path)
        cls = getattr(module, class_name)
        if not issubclass(cls, CompanyScraper):
            return None
        _scraper_classes[company] = cls
        return cls
    except (ImportError, AttributeError, TypeError):
        return None


def _instantiate_scraper(company: str) -> CompanyScraper | None:
    """实例化 Scraper 并注入 config 信息（url_patterns 等）。"""
    cls = _load_scraper_class(company)
    if cls is None:
        return None
    try:
        scraper = cls()
    except Exception:
        return None

    # 注入 config.yaml 中的 url_patterns
    config = _load_config()
    scraper_config = config.get("scrapers", {}).get(company, {})
    url_patterns = scraper_config.get("url_patterns", [])
    scraper._url_patterns = url_patterns

    # 注入 COMPANY_SLUG（如果子类没设）
    if not scraper.COMPANY_SLUG:
        scraper.COMPANY_SLUG = company

    return scraper


def get_scraper(company: str) -> CompanyScraper | None:
    """获取指定公司的 Scraper 实例（公司名/别名统一解析后再加载）。"""
    return _instantiate_scraper(resolve_company(company))


def list_scrapers() -> list[dict[str, Any]]:
    """列出所有已注册的企业 Scraper。

    参数定义以 scraper 类的 PARAMS 类属性为唯一事实源；
    未声明 PARAMS 的旧式 scraper 回退到 config.yaml 的 params 段。
    """
    config = _load_config()
    result = []
    for company_id, info in config.get("scrapers", {}).items():
        params = info.get("params") or {}
        source = "config"

        # 类属性 PARAMS 优先（单一事实源在代码里，随实现同步演化）
        cls = _load_scraper_class(company_id)
        if cls is not None and getattr(cls, "PARAMS", None):
            params = cls.PARAMS
            source = "class"

        company = company_for_scraper(company_id)
        result.append({
            "id": company_id,
            "name": info.get("name", company_id),
            "description": info.get("description", ""),
            "params": params,
            "params_source": source,
            "tier": tier_for_scraper(company_id),
            "industry": company["industry"] if company else "",
        })
    return result


def read_scraper_guide(company: str) -> str | None:
    """读取指定企业源的 guide.md 使用教程。

    教程随 scraper 包分发（唯一事实源），未提供时返回 None。
    """
    guide_path = Path(__file__).parent / company / "guide.md"
    if not guide_path.exists():
        return None
    try:
        return guide_path.read_text(encoding="utf-8")
    except OSError:
        return None


def get_scraper_for_url(url: str) -> CompanyScraper | None:
    """根据 URL 匹配最合适的 Scraper。

    优先用 supports_url() 匹配，避免盲遍历。
    """
    config = _load_config()
    for company_id in config.get("scrapers", {}):
        scraper = get_scraper(company_id)
        if scraper is None:
            continue
        if scraper.supports_url(url):
            return scraper
    return None


def _validate_results(results: list[dict[str, Any]], company_name: str) -> list[dict[str, Any]]:
    """校验搜索结果，补全缺失的必要字段。

    错误条目（含 "error" 键）原样保留，不做字段装饰——
    否则内部失败会被伪装成「未知岗位」假数据。
    """
    validated = []
    for r in results:
        if not isinstance(r, dict):
            continue
        if r.get("error"):
            validated.append(r)
            continue
        if not r.get("title"):
            r["title"] = "未知岗位"
            logger.warning(f"{company_name}: 搜索结果缺少 title 字段")
        if not r.get("url"):
            r["url"] = ""
            logger.warning(f"{company_name}: 搜索结果缺少 url 字段")
        validated.append(r)
    return validated


def _auto_write_knowledge(company: str, data: Any, data_type: str | None = None) -> None:
    """自动写入知识库。scraper 无需手动调用。

    data_type 优先级：参数 > config.yaml > scraper 类属性 > 默认 "jds"
    """
    try:
        config = _load_config()
        scraper_config = config.get("scrapers", {}).get(company, {})
        module_path = scraper_config.get("module", "")
        if not module_path:
            return

        # 确定 data_type
        if data_type is None:
            data_type = scraper_config.get("data_type", "")

        if not data_type:
            # 尝试从 scraper 类属性获取
            scraper = get_scraper(company)
            if scraper and hasattr(scraper, "DATA_TYPE"):
                data_type = scraper.DATA_TYPE

        if not data_type:
            data_type = "jds"

        full_module = f"src.scrapers.{module_path}"
        write_to_knowledge(full_module, data, data_type=data_type)
    except Exception as e:
        logger.warning(f"知识库写入失败 ({company}): {e}")


def search_company_jobs(company: str, **kwargs: Any) -> dict[str, Any]:
    """搜索指定公司的岗位。自动处理缓存、校验、知识库写入。"""
    company = resolve_company(company)
    scraper = get_scraper(company)
    if scraper is None:
        config = _load_config()
        available = list(config.get("scrapers", {}).keys())
        return {
            "error": f"未找到「{company}」的 Scraper",
            "available": available,
        }

    # BUG-025：未知参数直接报错，不静默吞掉——
    # LLM 引用错误参数名时，静默忽略会让用户以为搜索条件已生效
    scraper_config = _load_config().get("scrapers", {}).get(company, {})
    params_spec = getattr(scraper, "PARAMS", None) or scraper_config.get("params") or {}
    unknown = sorted(k for k in kwargs if k not in params_spec)
    if unknown:
        return {
            "error": (
                f"未知参数：{', '.join(unknown)}——"
                f"{company} 只支持：{sorted(params_spec)}"
                "（完整说明见 get_scraper_guide(company)）"
            ),
            "results": [],
        }

    try:
        results = scraper.search(**kwargs)
    except Exception as e:
        return {"error": f"搜索失败: {e}", "results": []}

    # 分离错误条目和有效结果
    # scraper 内部失败以 [{"error": "..."}] 形式返回，
    # 不能当作岗位数据透传（否则显示为「未知岗位」假结果）
    error_items = [r for r in results if isinstance(r, dict) and r.get("error")]
    valid_items = [r for r in results if isinstance(r, dict) and not r.get("error")]

    # 从 config 补充 company 字段
    scraper_config = _load_config().get("scrapers", {}).get(company, {})
    company_name = scraper_config.get("name", company)
    for r in valid_items:
        if not r.get("company"):
            r["company"] = company_name

    # 校验输出（仅对有效结果）
    valid_items = _validate_results(valid_items, company_name)

    # 全部失败：把第一个底层错误上抛，让上层看到真实原因
    if not valid_items and error_items:
        return {"error": error_items[0]["error"], "results": []}

    # 自动写入知识库
    if valid_items:
        _auto_write_knowledge(company, valid_items)

    resp: dict[str, Any] = {
        "company": company_name,
        "results": valid_items,
        "count": len(valid_items),
    }
    if error_items:
        # 部分失败：有效结果照常返回，错误作为警告附带上报
        resp["warnings"] = [r["error"] for r in error_items]
    return resp


def get_job_detail(url: str, company: str | None = None) -> dict[str, Any]:
    """获取岗位详情。自动处理缓存、URL 路由、知识库写入。"""
    if company:
        scraper = get_scraper(company)
        if scraper is None:
            return {"error": f"未找到「{company}」的 Scraper"}
        try:
            result = scraper.get_detail(url)
        except Exception as e:
            return {"error": f"获取详情失败: {e}"}
    else:
        # URL 路由：先用 supports_url 匹配
        scraper = get_scraper_for_url(url)
        if scraper:
            try:
                result = scraper.get_detail(url)
            except Exception as e:
                return {"error": f"获取详情失败: {e}"}
        else:
            # 兜底：遍历所有 Scraper
            config = _load_config()
            result = None
            for company_id in config.get("scrapers", {}):
                s = get_scraper(company_id)
                if s is None:
                    continue
                try:
                    r = s.get_detail(url)
                    if r and not r.get("error"):
                        result = r
                        break
                except Exception:
                    continue
            if result is None:
                return {"error": f"没有 Scraper 能处理此 URL: {url}"}

    # 自动写入知识库
    if result and not result.get("error"):
        # 从 URL 推断 company
        if not company:
            # 尝试从 result 中获取 company
            slug = result.get("company_slug", "")
            if slug:
                company = slug
            else:
                # 从 supports_url 匹配的 scraper 获取
                matched = get_scraper_for_url(url)
                if matched:
                    company = matched.COMPANY_SLUG
        if company:
            _auto_write_knowledge(company, result)

    return result
