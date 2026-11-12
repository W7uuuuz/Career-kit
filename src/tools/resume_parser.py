"""简历文件解析——支持 PDF、DOCX、Markdown、TXT。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt", ".markdown"}

# 联系方式检测：只做轻量正则提示，不追求完美，也不写入档案。
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[\s-]?)?1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NAME_LABEL_RE = re.compile(
    r"(?:姓\s*名|name)\s*[:：]\s*([^\s,，;；|]{2,40})", re.I
)
_EN_NAME_RE = re.compile(r"[A-Z][a-z]+(?:[ .'-][A-Z][a-z]+){0,3}")

_SECTION_WORDS = {
    "个人简历", "求职简历", "个人信息", "基本信息", "教育背景", "工作经历",
    "项目经验", "专业技能", "自我评价", "联系方式",
}


def extract_text(file_path: str) -> str:
    """Extract text from a resume file.

    Args:
        file_path: Absolute path to the resume file.

    Returns:
        Extracted plain text content.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file extension is not supported.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"不支持的文件格式：{ext}。支持的格式：{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if ext == ".pdf":
        return _extract_pdf(path)
    elif ext == ".docx":
        return _extract_docx(path)
    else:
        return _extract_text(path)


def _extract_pdf(path: Path) -> str:
    import pdfplumber

    pages_text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
    return "\n\n".join(pages_text)


def _extract_docx(path: Path) -> str:
    from docx import Document

    doc = Document(path)
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def _extract_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _looks_like_name(line: str) -> bool:
    """首行姓名兜底判断：仅接受 2-4 个汉字或常见英文姓名格式。"""
    text = line.strip().lstrip("#*-• ").strip()
    if not text:
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text):
        return text not in _SECTION_WORDS
    return bool(_EN_NAME_RE.fullmatch(text))


def detect_contact_fields(text: str) -> dict[str, Any]:
    """检测简历文本中的姓名、手机号、邮箱（简单正则，不追求完美）。

    只返回解析提示，供上层询问用户是否补充；不写入档案、不推断缺失值。
    """
    content = str(text or "")
    name = ""
    label_match = _NAME_LABEL_RE.search(content)
    if label_match:
        name = label_match.group(1).strip()
    if not name:
        for line in content.splitlines()[:8]:
            if _looks_like_name(line):
                name = line.strip().lstrip("#*-• ").strip()
                break
    return {
        "name": name,
        "phone": bool(_PHONE_RE.search(content)),
        "email": bool(_EMAIL_RE.search(content)),
    }
