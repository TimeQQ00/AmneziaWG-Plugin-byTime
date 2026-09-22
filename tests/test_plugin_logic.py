# -*- coding: utf-8 -*-
"""Тест логики плагина без телефона: парсер конфигов, выбор конфига, verify_tunnel.

Запуск:
    python tests/test_plugin_logic.py

Для живого теста туннеля задайте переменную окружения AWG_TEST_CONF
(путь к вашему .conf с реальным ключом) и соберите тестовую DLL:
    set AWG_TEST_CONF=C:\\path\\to\\myvpn.conf
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

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

    # 3) нормализация пути: кавычки, пробелы, file://
    normalize = namespace["_normalize_path"]
    assert normalize('  "/sdcard/Download/my.conf" ') == "/sdcard/Download/my.conf"
    assert normalize("'/sdcard/my.conf'") == "/sdcard/my.conf"
    assert normalize("file:///sdcard/Download/my.conf") == "/sdcard/Download/my.conf"
    assert normalize("content://downloads/document/3") == "content://downloads/document/3"
    assert normalize("") == "" and normalize(None) == ""
    print("NORMALIZE PATH TEST: PASS")

    # 4) чтение источника: обычный файл
    reader = namespace["_read_text_source"]
    handle, tmp_name = tempfile.mkstemp(suffix=".conf")
    os.write(handle, CONF_EXAMPLE.read_bytes())
    os.close(handle)
    try:
        text = reader(tmp_name)
    finally:
        os.unlink(tmp_name)
    assert "[Interface]" in text and "[Peer]" in text
    print("READ SOURCE TEST: PASS")

    # 5) ГЛАВНЫЙ РЕГРЕССИОННЫЙ ТЕСТ: verify-провал НЕ стирает пользовательский конфиг
    class FakePlugin:
        def __init__(self):
            self.data = {}

        def get_setting(self, key, default=None):
            return self.data.get(key, default)

        def set_setting(self, key, value, reload_settings=False):
            self.data[key] = value

    fake_plugin = FakePlugin()
    namespace["_PLUGIN"] = fake_plugin
    namespace["set_setting"]("custom_config_json", json.dumps(example))

    class DeadEngine:
        """Движок, у которого трафик никогда не проходит."""
        port = 10809

        def start(self, cfg):
            pass

        def wait_port(self, timeout=8.0):
            return True

        def verify_with_retry(self, **kwargs):
            return False

        def verify_tunnel(self, **kwargs):
            return False

        def stop(self):
            pass

        def status(self):
            return False

        def port_open(self):
            return False

    namespace["ENGINE"] = DeadEngine()
    # 5а) публичная сборка (встроенного нет): ошибка, но конфиг сохранён
    try:
        namespace["tunnel_up"]()
        raise AssertionError("ожидали RuntimeError (custom_bad_no_fallback)")
    except RuntimeError:
        pass
    kept = json.loads(namespace["get_setting"]("custom_config_json"))
    assert kept.get("privateKey") and kept.get("endpoint"), "конфиг был стёрт!"
    print("NO-WIPE (no builtin) TEST: PASS")

    # 5б) личная сборка: откат на встроенный, конфиг по-прежнему сохранён
    class TwoPhaseEngine(DeadEngine):
        """Свой конфиг не проходит, встроенный — проходит (со 2-й проверки)."""

        def __init__(self):
            self.verify_calls = 0

        def verify_with_retry(self, **kwargs):
            self.verify_calls += 1
            return self.verify_calls >= 2

    namespace["ENGINE"] = TwoPhaseEngine()
    namespace["default_config"] = lambda: dict(example)
    assert namespace["restart_tunnel"]() == "fallback"
    kept = json.loads(namespace["get_setting"]("custom_config_json"))
    assert kept.get("endpoint"), "конфиг был стёрт при откате!"
    print("NO-WIPE (fallback) TEST: PASS")

    # 5в) рабочий конфиг: tunnel_up возвращает "custom"
    class GoodEngine(DeadEngine):
        def verify_with_retry(self, **kwargs):
            return True

    namespace["ENGINE"] = GoodEngine()
    assert namespace["tunnel_up"]() == "custom"
    print("CUSTOM OK TEST: PASS")

    # 6) _resume_check: живой движок не перезапускается
    class AliveEngine(DeadEngine):
        def __init__(self):
            self.restarts = 0

        def status(self):
            return True

        def port_open(self):
            return True

    alive = AliveEngine()

    def fail_restart(*args, **kwargs):
        alive.restarts += 1
        raise AssertionError("resume не должен перезапускать живой туннель")

    namespace["ENGINE"] = alive
    namespace["restart_tunnel"] = fail_restart
    plugin_instance = namespace["AmneziaPlugin"]()
    plugin_instance._resume_check()
    assert alive.restarts == 0
    print("RESUME ALIVE TEST: PASS")

    # 7) verify_with_retry: считает попытки и делает паузы
    attempts = {"n": 0}

    class RetryEngine:
        def verify_tunnel_detailed(self, **kwargs):
            attempts["n"] += 1
            return attempts["n"] >= 3, "ok" if attempts["n"] >= 3 else "ещё не готово"

    engine = namespace["EngineCtl"]()
    engine.verify_tunnel_detailed = RetryEngine().verify_tunnel_detailed
    assert engine.verify_with_retry(attempts=3, pause=0) is True
    assert attempts["n"] == 3
    print("RETRY TEST: PASS")

    # 8) живой движок + verify_tunnel (нужны DLL и реальный конфиг)
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
