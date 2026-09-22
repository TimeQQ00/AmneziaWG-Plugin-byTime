# -*- coding: utf-8 -*-
"""Извлекает пул проверенных I1-пейлоадов из warpCpsPayloads.js в JSON."""
import json
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "amnezia-config-gen-main" / "src" / "server" / "warpCpsPayloads.js"
DST = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "_i1_pool.json"

text = SRC.read_text(encoding="utf-8")
payloads = re.findall(r"'(<b 0x[0-9a-f]+>)'", text)
print("found payloads:", len(payloads))
for i, p in enumerate(payloads):
    print("  #%d: len=%d magic=%s" % (i, len(p), p[:12]))
DST.write_text(json.dumps(payloads), encoding="utf-8")
print("saved:", DST)
