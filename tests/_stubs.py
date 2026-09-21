# -*- coding: utf-8 -*-
"""Общие стабы exteraGram для тестов плагина вне телефона."""
import sys
import types


class _Permissive:
    def __getattr__(self, name):
        return _Permissive()

    def __call__(self, *args, **kwargs):
        return _Permissive()


class AppEvent:
    START = "START"
    STOP = "STOP"
    PAUSE = "PAUSE"
    RESUME = "RESUME"


class MenuItemType:
    MAIN_MENU = "MAIN_MENU"


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def install():
    """Регистрирует заглушки модулей exteraGram, чтобы код плагина импортировался."""
    _module("base_plugin",
            AppEvent=AppEvent,
            BasePlugin=type("BasePlugin", (), {}),
            MenuItemData=_Permissive,
            MenuItemType=MenuItemType,
            MethodHook=_Permissive)
    _module("android_utils", run_on_ui_thread=lambda fn: fn(), log=print)
    _module("client_utils", get_last_fragment=lambda: None)
    _module("hook_utils", find_class=lambda *a, **k: None)
    _module("ui")
    _module("ui.settings", Header=_Permissive, Text=_Permissive, Divider=_Permissive,
            Input=_Permissive, Switch=_Permissive)
    _module("ui.bulletin", BulletinHelper=_Permissive)
    _module("java", jclass=lambda name: _Permissive())


def load_plugin_source(path):
    """Читает .plugin/plugin_code.py и подставляет пустой JSON вместо конфига."""
    text = path.read_text(encoding="utf-8")
    if "__LIB_BEGIN__" in text:
        text = text.split("# __LIB_BEGIN__", 1)[0]
    return text.replace("__AWG_CONFIG_JSON__", '"{}"')


def exec_plugin(path):
    install()
    namespace = {"__name__": "plugin_under_test"}
    exec(compile(load_plugin_source(path), path.name, "exec"), namespace)
    return namespace
