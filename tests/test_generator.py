# -*- coding: utf-8 -*-
"""Проверка X25519, пула I1 и кнопок генератора (без телефона)."""
import base64
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import _stubs  # noqa: E402

PLUGIN = REPO / "dist" / "amnezia_awg_byTime.plugin"


def main():
    ns = _stubs.exec_plugin(PLUGIN)
    print("plugin code executed OK")

    # 1) RFC 7748 test vector
    scalar = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
    u = bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")
    out = ns["_x25519_scalarmult"](scalar, u)
    expected = bytes.fromhex("c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552")
    assert out == expected, "X25519 MISMATCH: " + out.hex()
    print("X25519 RFC7748 vector: PASS")

    # 2) keypair: pub = priv * 9
    priv, pub = ns["_x25519_keypair_b64"]()
    raw_priv = base64.b64decode(priv)
    raw_pub = base64.b64decode(pub)
    derived = ns["_x25519_scalarmult"](raw_priv, b"\x09" + b"\x00" * 31)
    assert derived == raw_pub, "keypair mismatch"
    print("X25519 keypair consistency: PASS")

    # 3) I1 pool
    pool = ns["I1_PAYLOAD_POOL"]
    assert len(pool) == 3, pool
    i1 = ns["_pick_i1"]()
    assert i1.startswith("<b 0x") and len(i1) > 100
    print("I1 pool pick: PASS (len %d, pool %d)" % (len(i1), len(pool)))

    # 4) генератор: без сети должен дать внятную ошибку, а не тихо вернуть None
    try:
        ns["generate_warp_config_text"]()
        print("GENERATOR (no network): UNEXPECTED SUCCESS")
    except Exception as exc:
        print("GENERATOR (no network): expected failure ->", str(exc)[:60])
    return 0


if __name__ == "__main__":
    sys.exit(main())
