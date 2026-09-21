# -*- coding: utf-8 -*-
"""Тест логики плагина без телефона: парсер конфигов, выбор конфига, verify_tunnel.

Запуск:
    python tests/test_plugin_logic.py
"""
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import _stubs  # noqa: E402

PLUGIN = REPO / "dist" / "amnezia_awg_byTime.plugin"
CONF = REPO / "configs" / "default-warp.conf"
CONF_EXAMPLE = REPO / "configs" / "default-warp.conf.example"
DLL = REPO / "engine" / "prebuilt" / "windows-amd64" / "awgcore_test.dll"


def ensure_built():
    if PLUGIN.exists():
        return
    print("dist-плагин не найден, собираю: python plugin/build.py")
    subprocess.run([sys.executable, str(REPO / "plugin" / "build.py")], check=True)


def main():
    ensure_built()
    namespace = _stubs.exec_plugin(PLUGIN)
    print("plugin code executed OK")

    parse_conf_text = namespace["parse_conf_text"]
    default_config = namespace["default_config"]
    current_config = namespace["current_config"]

    conf_path = CONF if CONF.exists() else CONF_EXAMPLE
    custom = parse_conf_text(conf_path.read_text(encoding="utf-8"))
    builtin = default_config()

    # 1) парсер: пользовательский .conf должен дать тот же конфиг, что вшит сборщиком
    assert custom["endpoint"] == builtin["endpoint"], "endpoint mismatch"
    assert custom["publicKey"] == builtin["publicKey"], "publicKey mismatch"
    assert custom["awg"] == builtin["awg"], "awg params mismatch"
    assert custom["socksPort"] == 10809
    assert custom["allowedIPs"] == ["0.0.0.0/0", "::/0"], custom["allowedIPs"]
    print("PARSER TEST: PASS")

    # 2) при пустых настройках активен встроенный WARP
    active, is_custom = current_config()
    assert is_custom is False
    assert active["endpoint"] == builtin["endpoint"]
    print("DEFAULT CONFIG TEST: PASS")

    # 3) живой движок + verify_tunnel (если собрана тестовая DLL)
    if not DLL.exists():
        print("TUNNEL TEST: SKIP (нет " + str(DLL) + ")")
        print("ALL TESTS: PASS")
        return 0

    import ctypes
    lib = ctypes.CDLL(str(DLL))
    lib.awgStart.argtypes = [ctypes.c_char_p]
    lib.awgStart.restype = ctypes.c_int
    lib.awgStop.argtypes = []
    lib.awgStop.restype = ctypes.c_int

    engine = namespace["EngineCtl"]()
    engine.lib = lib  # подменяем CDLL на тестовую сборку
    engine.start(custom)
    print("awgStart ok | port:", engine.port)
    assert engine.wait_port(10), "порт SOCKS5 не открылся"
    ok = engine.verify_tunnel()
    lib.awgStop()
    print("verify_tunnel:", ok)
    assert ok, "проверка трафика через туннель не прошла"
    print("TUNNEL TEST: PASS")
    print("ALL TESTS: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
