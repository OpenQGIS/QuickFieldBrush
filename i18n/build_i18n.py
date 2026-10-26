# -*- coding: utf-8 -*-
"""
翻译文件生成器：从 i18n_strings._zh_translations 生成
  i18n/QuickFieldBrush_zh_CN.ts
  i18n/QuickFieldBrush_zh_CN.qm
"""

import os
import struct
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PLUGIN_ROOT)

from i18n_strings import _zh_translations  # noqa: E402

CONTEXT = "QuickFieldBrush"


def build_ts(lang):
    ts_path = os.path.join(HERE, "QuickFieldBrush_{}.ts".format(lang))
    root = ET.Element("TS", {"version": "2.1", "language": lang, "sourcelanguage": "en"})
    ctx = ET.SubElement(root, "context")
    ET.SubElement(ctx, "name").text = CONTEXT
    for src in sorted(_zh_translations):
        msg = ET.SubElement(ctx, "message")
        ET.SubElement(msg, "source").text = src
        ET.SubElement(msg, "translation").text = _zh_translations[src]
    try:
        ET.indent(root)
    except AttributeError:
        pass
    ET.ElementTree(root).write(ts_path, encoding="utf-8", xml_declaration=True)
    return ts_path


def _elf_hash(data):
    h = 0
    for byte in data:
        h = (h << 4) + byte
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
        h &= ~g & 0xFFFFFFFF
    return h & 0xFFFFFFFF


def build_qm(lang):
    msg_block = bytearray()
    hash_entries = []
    ctx_bytes = CONTEXT.encode("utf-8")

    for src in sorted(_zh_translations):
        translation = _zh_translations[src]
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

    qm_path = os.path.join(HERE, "QuickFieldBrush_{}.qm".format(lang))
    with open(qm_path, "wb") as f:
        f.write(qm)
    return qm_path


if __name__ == "__main__":
    lang = sys.argv[1] if len(sys.argv) > 1 else "zh_CN"
    ts_file = build_ts(lang)
    qm_file = build_qm(lang)
    print("TS ->", ts_file)
    print("QM ->", qm_file, f"({os.path.getsize(qm_file)} bytes, {len(_zh_translations)} entries)")
