# -*- coding: utf-8 -*-
"""Встраивает пул I1-пейлоадов (_i1_pool.json) в plugin_code.py между маркерами."""
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
POOL = REPO / "plugin" / "_i1_pool.json"
PLUGIN = REPO / "plugin" / "plugin_code.py"

BEGIN = "# __I1_POOL_BEGIN__"
END = "# __I1_POOL_END__"

payloads = json.loads(POOL.read_text(encoding="utf-8"))
block_lines = [BEGIN, "I1_PAYLOAD_POOL = ("]
for payload in payloads:
    block_lines.append("    %r," % payload)
block_lines += [")", END]
block = "\n".join(block_lines)

code = PLUGIN.read_text(encoding="utf-8")
if BEGIN in code and END in code:
    pre, rest = code.split(BEGIN, 1)
    _, post = rest.split(END, 1)
    code = pre + block + post
else:
    marker = "# __LIB_BEGIN__"
    pre, post = code.split(marker, 1)
    code = pre + block + "\n\n" + marker + post
PLUGIN.write_text(code, encoding="utf-8", newline="\n")
print("embedded %d payloads into plugin_code.py" % len(payloads))
