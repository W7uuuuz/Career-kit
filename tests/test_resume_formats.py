"""简历格式测试——用真实简历文件测试解析功能。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.tools.resume_parser import extract_text

TEST_DIR = Path(__file__).parent.parent / "dev" / "test"


def parse_markdown() -> str | None:
    """解析 Markdown 简历；文件缺失返回 None。"""
    md_file = TEST_DIR / "AI.md"
    if not md_file.exists():
        return None
    text = extract_text(str(md_file))
    print(f"[OK] Markdown 提取成功，共 {len(text)} 字符")
    return text


def parse_docx() -> str | None:
    """解析 DOCX 简历；文件缺失返回 None。"""
    docx_file = TEST_DIR / "AI岗.docx"
    if not docx_file.exists():
        return None
    text = extract_text(str(docx_file))
    print(f"[OK] DOCX 提取成功，共 {len(text)} 字符")
    return text


def parse_pdf() -> str | None:
    """解析 PDF 简历；文件缺失返回 None。"""
    pdf_file = TEST_DIR / "AI岗.pdf"
    if not pdf_file.exists():
        return None
    text = extract_text(str(pdf_file))
    print(f"[OK] PDF 提取成功，共 {len(text)} 字符")
    return text


def test_markdown():
    text = parse_markdown()
    if text is None:
        pytest.skip("AI.md 不存在")
    assert len(text) > 0


def test_docx():
    text = parse_docx()
    if text is None:
        pytest.skip("AI岗.docx 不存在")
    assert len(text) > 0


def test_pdf():
    text = parse_pdf()
    if text is None:
        pytest.skip("AI岗.pdf 不存在")
    assert len(text) > 0


def compare_results(md_text, docx_text, pdf_text):
    """比较三种格式的解析结果。"""
    print("=" * 60)
    print("比较分析")
    print("=" * 60)

    results = {
        "Markdown": md_text,
        "DOCX": docx_text,
        "PDF": pdf_text,
    }

    for name, text in results.items():
        if text:
            print(f"{name}: {len(text)} 字符")

    keywords = ["AI", "经验", "技能", "项目"]
    print("\n关键信息提取检查:")
    for kw in keywords:
        found_in = [name for name, text in results.items() if text and kw in text]
        print(f"  '{kw}': {', '.join(found_in) if found_in else '未找到'}")


def main():
    """手动运行：解析三种格式并比较。"""
    print("\n" + "=" * 60)
    print("简历格式解析测试")
    print("=" * 60 + "\n")

    md_text = parse_markdown()
    docx_text = parse_docx()
    pdf_text = parse_pdf()

    if any([md_text, docx_text, pdf_text]):
        compare_results(md_text, docx_text, pdf_text)

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
