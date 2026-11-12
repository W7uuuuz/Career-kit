"""实习僧自定义字体解码。

站点用 myFont 把部分汉字/字母替换成私有区字符，字体文件随页面下发。
这里用标准库解析 WOFF/TTF 的 cmap 与 post 表，把 PUA 码位还原为原字符；
解析失败时由调用方回退到静态 PUA_MAP。
"""

from __future__ import annotations

import html as _html
import re
import struct
import zlib
from urllib.parse import urljoin, urlsplit

_FONT_FACE_RE = re.compile(
    r"font-family\s*:\s*myFont\b.*?src\s*:\s*url\(([^)]+)\)",
    re.I | re.S,
)
_UNI_NAME_RE = re.compile(r"^uni([0-9A-Fa-f]{2,6})$")


def extract_font_url(page_html: str, base_url: str) -> str:
    """从页面内联样式中提取 myFont 的字体地址。"""
    match = _FONT_FACE_RE.search(page_html or "")
    if not match:
        return ""
    raw = _html.unescape(match.group(1).strip()).strip("'\"")
    if not raw:
        return ""
    return urljoin(base_url, raw)


def font_cache_key(font_url: str) -> str:
    """去掉随机 rand 参数作为缓存键；同一字体映射可复用。"""
    parsed = urlsplit(font_url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def parse_font_map(data: bytes) -> dict[str, str]:
    """解析字体 cmap + post，返回 PUA 码位 -> 原字符。失败返回空字典。"""
    if not data:
        return {}
    try:
        tables = _read_tables(data)
        cmap = tables.get("cmap")
        post = tables.get("post")
        if not cmap or not post:
            return {}
        glyph_ids = _parse_cmap(cmap)
        names = _parse_post(post)
        if not glyph_ids or not names:
            return {}
        mapping: dict[str, str] = {}
        for codepoint, glyph_id in glyph_ids.items():
            if not 0xE000 <= codepoint <= 0xF8FF:
                continue
            name = names.get(glyph_id, "")
            match = _UNI_NAME_RE.match(name or "")
            if not match:
                continue
            try:
                original = chr(int(match.group(1), 16))
            except (ValueError, OverflowError):
                continue
            mapping[chr(codepoint)] = original
        return mapping
    except (KeyError, ValueError, struct.error, zlib.error):
        return {}


def _read_tables(data: bytes) -> dict[str, bytes]:
    signature = data[:4]
    if signature == b"wOFF":
        return _read_woff_tables(data)
    if signature in {b"\x00\x01\x00\x00", b"true", b"OTTO", b"ttcf"}:
        return _read_sfnt_tables(data)
    return {}


def _read_woff_tables(data: bytes) -> dict[str, bytes]:
    if len(data) < 44:
        return {}
    _, _, _, num_tables = struct.unpack(">4sIIH", data[:14])
    tables: dict[str, bytes] = {}
    directory = 44
    for index in range(num_tables):
        start = directory + index * 20
        tag, offset, comp_length, orig_length, _ = struct.unpack(
            ">4sIIII", data[start : start + 20]
        )
        raw = data[offset : offset + (comp_length or orig_length)]
        if comp_length < orig_length:
            raw = zlib.decompress(raw)
        tables[tag.decode("latin1")] = raw
    return tables


def _read_sfnt_tables(data: bytes) -> dict[str, bytes]:
    if len(data) < 12:
        return {}
    num_tables = struct.unpack(">H", data[4:6])[0]
    tables: dict[str, bytes] = {}
    directory = 12
    for index in range(num_tables):
        start = directory + index * 16
        tag, _, offset, length = struct.unpack(">4sIII", data[start : start + 16])
        tables[tag.decode("latin1")] = data[offset : offset + length]
    return tables


def _parse_cmap(cmap: bytes) -> dict[int, int]:
    if len(cmap) < 4:
        return {}
    _, num_tables = struct.unpack(">HH", cmap[:4])
    best: tuple[int, int] | None = None
    for index in range(num_tables):
        start = 4 + index * 8
        platform, encoding, offset = struct.unpack(">HHI", cmap[start : start + 8])
        if offset + 2 > len(cmap):
            continue
        fmt = struct.unpack(">H", cmap[offset : offset + 2])[0]
        if fmt == 12:
            best = (offset, 12)
        elif fmt == 4 and (best is None or best[1] != 12):
            best = (offset, 4)
    if best is None:
        return {}
    offset, fmt = best
    return _parse_cmap12(cmap, offset) if fmt == 12 else _parse_cmap4(cmap, offset)


def _parse_cmap12(cmap: bytes, offset: int) -> dict[int, int]:
    if offset + 16 > len(cmap):
        return {}
    _, _, _, _, groups = struct.unpack(">HHIII", cmap[offset : offset + 16])
    mapping: dict[int, int] = {}
    for index in range(groups):
        start = offset + 16 + index * 12
        if start + 12 > len(cmap):
            break
        first, last, glyph = struct.unpack(">III", cmap[start : start + 12])
        for codepoint in range(first, last + 1):
            mapping[codepoint] = glyph + (codepoint - first)
    return mapping


def _parse_cmap4(cmap: bytes, offset: int) -> dict[int, int]:
    if offset + 14 > len(cmap):
        return {}
    seg_x2 = struct.unpack(">H", cmap[offset + 6 : offset + 8])[0]
    segments = seg_x2 // 2
    end_start = offset + 14
    start_start = end_start + seg_x2 + 2
    delta_start = start_start + seg_x2
    range_start = delta_start + seg_x2
    if range_start + seg_x2 > len(cmap):
        return {}
    ends = struct.unpack(f">{segments}H", cmap[end_start : end_start + seg_x2])
    starts = struct.unpack(f">{segments}H", cmap[start_start : start_start + seg_x2])
    deltas = struct.unpack(f">{segments}h", cmap[delta_start : delta_start + seg_x2])
    offsets = struct.unpack(f">{segments}H", cmap[range_start : range_start + seg_x2])
    glyph_array_at = range_start + seg_x2
    mapping: dict[int, int] = {}
    for index in range(segments):
        if starts[index] == 0xFFFF:
            continue
        for codepoint in range(starts[index], ends[index] + 1):
            if offsets[index] == 0:
                glyph = (codepoint + deltas[index]) & 0xFFFF
            else:
                at = glyph_array_at + 2 * index + offsets[index] + 2 * (
                    codepoint - starts[index]
                )
                if at + 2 > len(cmap):
                    continue
                glyph = struct.unpack(">H", cmap[at : at + 2])[0]
                if glyph:
                    glyph = (glyph + deltas[index]) & 0xFFFF
            if glyph:
                mapping[codepoint] = glyph
    return mapping


def _parse_post(post: bytes) -> dict[int, str]:
    if len(post) < 34:
        return {}
    version = struct.unpack(">I", post[:4])[0]
    if version != 0x00020000:
        return {}
    num_glyphs = struct.unpack(">H", post[32:34])[0]
    index_start = 34
    names_start = index_start + 2 * num_glyphs
    if names_start > len(post):
        return {}
    name_indices = struct.unpack(f">{num_glyphs}H", post[index_start:names_start])
    names: list[str] = []
    position = names_start
    while position < len(post):
        length = post[position]
        position += 1
        if position + length > len(post):
            break
        names.append(post[position : position + length].decode("latin1"))
        position += length
    mapping: dict[int, str] = {}
    for glyph_id, name_index in enumerate(name_indices):
        if 258 <= name_index < 258 + len(names):
            mapping[glyph_id] = names[name_index - 258]
    return mapping


__all__ = ["extract_font_url", "font_cache_key", "parse_font_map"]
