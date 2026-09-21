# -*- coding: utf-8 -*-
"""Тест логики плагина без телефона: парсер конфигов, выбор конфига, verify_tunnel.

Запуск:
    python tests/test_plugin_logic.py

Для живого теста туннеля задайте переменную окружения AWG_TEST_CONF
(путь к вашему .conf с реальным ключом) и соберите тестовую DLL:
    set AWG_TEST_CONF=C:\\path\\to\\myvpn.conf
"""
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import _stubs  # noqa: E402

PLUGIN = REPO / "dist" / "amnezia_awg_byTime.plugin"
CONF_EXAMPLE = REPO / "configs" / "default-warp.conf.example"
DLL = REPO / "engine" / "prebuilt" / "windows-amd64" / "awgcore_test.dll"


def test_conf_path():
    """Реальный .conf для живого теста: переменная окружения или configs/default-warp.conf."""
    env = os.environ.get("AWG_TEST_CONF")
    if env and pathlib.Path(env).exists():
        return pathlib.Path(env)
    private = REPO / "configs" / "default-warp.conf"
    if private.exists():
        return private
    return None


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

    # 1) парсер .conf (пример с ключом-заглушкой подходит для проверки разбора)
    example = parse_conf_text(CONF_EXAMPLE.read_text(encoding="utf-8"))
    assert example["endpoint"], "endpoint не распознан"
    assert example["socksPort"] == 10809
    assert example["allowedIPs"] == ["0.0.0.0/0", "::/0"], example["allowedIPs"]
    assert "jc" in example["awg"] and "i1" in example["awg"], sorted(example["awg"])
    print("PARSER TEST: PASS")

    # 2) публичная сборка: встроенного конфига нет
    assert default_config() is None, "в публичной сборке не должно быть встроенного конфига"
    active, is_custom = current_config()
    assert active is None and is_custom is False
    print("NO DEFAULT CONFIG TEST: PASS")

    # 3) живой движок + verify_tunnel (нужны DLL и реальный конфиг)
    conf_path = test_conf_path()
    if not DLL.exists():
        print("TUNNEL TEST: SKIP (нет " + str(DLL) + ")")
        print("ALL TESTS: PASS")
        return 0
    if conf_path is None:
        print("TUNNEL TEST: SKIP (задайте AWG_TEST_CONF — путь к .conf с реальным ключом)")
        print("ALL TESTS: PASS")
        return 0

    import ctypes
    lib = ctypes.CDLL(str(DLL))
    lib.awgStart.argtypes = [ctypes.c_char_p]
    lib.awgStart.restype = ctypes.c_int
    lib.awgStop.argtypes = []
    lib.awgStop.restype = ctypes.c_int

    custom = parse_conf_text(conf_path.read_text(encoding="utf-8"))
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
