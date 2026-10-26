# -*- coding: utf-8 -*-
"""
多语言国际化包构建器：
为 QGIS QuickFieldBrush 构建全球主流语言体系的 .ts 与 .qm 翻译包。
覆盖：zh_CN, zh_TW, ja, ko, es, fr, de, ru, pt, it
"""

import os
import struct
import sys
import xml.etree.ElementTree as ET  # nosec B405

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PLUGIN_ROOT)

from i18n_strings import _zh_translations

CONTEXT = "QuickFieldBrush"

def _elf_hash(data):
    h = 0
    for byte in data:
        h = (h << 4) + byte
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
        h &= ~g & 0xFFFFFFFF
    return h & 0xFFFFFFFF

def build_ts(lang, trans_dict):
    ts_path = os.path.join(HERE, f"QuickFieldBrush_{lang}.ts")
    root = ET.Element("TS", {"version": "2.1", "language": lang, "sourcelanguage": "en"})
    ctx = ET.SubElement(root, "context")
    ET.SubElement(ctx, "name").text = CONTEXT
    for src in sorted(_zh_translations):
        val = trans_dict.get(src, src)
        msg = ET.SubElement(ctx, "message")
        ET.SubElement(msg, "source").text = src
        ET.SubElement(msg, "translation").text = val
    try:
        ET.indent(root)
    except AttributeError:
        pass
    ET.ElementTree(root).write(ts_path, encoding="utf-8", xml_declaration=True)
    return ts_path

def build_qm(lang, trans_dict):
    msg_block = bytearray()
    hash_entries = []
    ctx_bytes = CONTEXT.encode("utf-8")

    for src in sorted(_zh_translations):
        translation = trans_dict.get(src, src)
        offset = len(msg_block)

        trans_bytes = translation.encode("utf-16-be")
        msg_block.append(0x03)
        msg_block.extend(struct.pack(">I", len(trans_bytes)))
        msg_block.extend(trans_bytes)

        msg_block.append(0x07)
        msg_block.extend(struct.pack(">I", len(ctx_bytes)))
        msg_block.extend(ctx_bytes)

        src_bytes = src.encode("utf-8")
        msg_block.append(0x06)
        msg_block.extend(struct.pack(">I", len(src_bytes)))
        msg_block.extend(src_bytes)

        msg_block.append(0x01)
        hash_entries.append((_elf_hash(src_bytes), offset))

    hash_block = bytearray()
    for h, offset in sorted(hash_entries):
        hash_block.extend(struct.pack(">I", h))
        hash_block.extend(struct.pack(">I", offset))

    qm = bytearray(bytes.fromhex("3cb86418caef9c95cd211cbf60a1bddd"))
    qm.append(0x42)
    qm.extend(struct.pack(">I", len(hash_block)))
    qm.extend(hash_block)
    qm.append(0x69)
    qm.extend(struct.pack(">I", len(msg_block)))
    qm.extend(msg_block)

    qm_path = os.path.join(HERE, f"QuickFieldBrush_{lang}.qm")
    with open(qm_path, "wb") as f:
        f.write(qm)
    return qm_path
