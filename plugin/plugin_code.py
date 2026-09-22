# -*- coding: utf-8 -*-
#
# AmneziaWG Tunnel byTime — плагин для exteraGram.
# Автор: Time. Полностью самодостаточный AmneziaWG-движок (userspace,
# без VpnService) + локальный SOCKS5 для трафика Telegram.
#
import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time

from base_plugin import AppEvent, BasePlugin, MenuItemData, MenuItemType
from android_utils import run_on_ui_thread
from ui.bulletin import BulletinHelper

from java import jclass

__id__ = "amnezia_awg_byTime"
__name__ = "AmneziaWG byTime"
__description__ = "AmneziaWG-туннель для Telegram со своими конфигами. Сделано Time"
__author__ = "Time"
__version__ = "1.2.0"
__icon__ = "exteraPlugins/1"
__app_version__ = ">=12.5.1"
__sdk_version__ = ">=1.4.4.3"

SOCKS_PORT = 10809
ENGINE_DIR_NAME = "awgcore"
LIB_NAME = "libawgcore.so"
LIB_BEGIN = "__LIB_BEGIN__"
LIB_END = "__LIB_END__"

# Встроенный конфиг. В ЛИЧНОЙ сборке сборщик подставляет сюда JSON вашего .conf
# (см. python plugin/build.py --conf путь/к/file.conf). В ПУБЛИЧНОЙ сборке это
# значение пустое: плагин работает только с импортированными пользователем .conf
# (настройки плагина -> «Путь к .conf файлу» -> «Импортировать и подключиться»).
DEFAULT_ENGINE_CONFIG_JSON = __AWG_CONFIG_JSON__

Build = jclass("android.os.Build")
BuildVersion = jclass("android.os.Build$VERSION")
ApplicationLoader = jclass("org.telegram.messenger.ApplicationLoader")
SharedConfig = jclass("org.telegram.messenger.SharedConfig")
ConnectionsManager = jclass("org.telegram.tgnet.ConnectionsManager")
PROXY_INFO = jclass("org.telegram.messenger.SharedConfig$ProxyInfo")
NotificationCenter = jclass("org.telegram.messenger.NotificationCenter")
MessagesController = jclass("org.telegram.messenger.MessagesController")
# org.telegram.proxy.ProxySettings импортируем лениво: в части версий его нет.

TRANSLATIONS = {
    "starting": ("Amnezia byTime: запускаю туннель…", "Amnezia byTime: starting tunnel…"),
    "running": ("Amnezia byTime: туннель работает", "Amnezia byTime: tunnel is running"),
    "running_custom": ("Amnezia byTime: работает ваш конфиг", "Amnezia byTime: custom config is running"),
    "running_fallback": ("Amnezia byTime: ваш конфиг не прошёл — подключён встроенный (конфиг сохранён)",
                         "Amnezia byTime: your config failed — built-in is active (your config is kept)"),
    "stopped": ("Amnezia byTime: туннель выключен", "Amnezia byTime: tunnel is stopped"),
    "start_failed": ("Amnezia byTime: не удалось запустить", "Amnezia byTime: failed to start"),
    "stop_failed": ("Amnezia byTime: не удалось остановить", "Amnezia byTime: failed to stop"),
    "need_arm64": ("Amnezia byTime нужен 64-битный Android", "Amnezia byTime requires 64-bit Android"),
    "restart": ("Перезапустить туннель (Amnezia byTime)", "Restart tunnel (Amnezia byTime)"),
    "menu_import": ("Amnezia byTime: применить конфиг", "Amnezia byTime: apply config"),
    "tunnel_dead": ("Amnezia byTime: туннель не пропускает трафик",
                    "Amnezia byTime: tunnel does not pass traffic"),
    "no_config": ("Amnezia byTime: конфиг не задан — нажмите «Выбрать .conf» в настройках плагина",
                  "Amnezia byTime: no config — tap 'Pick .conf' in the plugin settings"),
    "custom_bad_fallback_failed": ("Amnezia byTime: не удалось поднять ни ваш конфиг, ни встроенный",
                                   "Amnezia byTime: failed with both your config and the built-in one"),
    "custom_bad_no_fallback": ("Amnezia byTime: ваш конфиг не заработал — туннель остановлен, проверьте конфиг",
                               "Amnezia byTime: your config failed — tunnel stopped, check the config"),
    "settings_server": ("Сервер", "Server"),
    "settings_about": ("О плагине", "About"),
    "current_server": ("Активный сервер: {0}\nИсточник: {1}", "Active server: {0}\nSource: {1}"),
    "current_awg": ("AWG-параметров в конфиге: {0}", "AWG parameters in config: {0}"),
    "src_default": ("встроенный конфиг сборки", "config baked into this build"),
    "src_none": ("конфиг не задан", "no config set"),
    "src_custom": ("ваш импортированный файл", "your imported file"),
    "conf_path": ("Путь к .conf файлу", "Path to .conf file"),
    "conf_path_hint": ("Например: /sdcard/Download/myvpn.conf — формат AmneziaWG/WireGuard",
                       "Example: /sdcard/Download/myvpn.conf — AmneziaWG/WireGuard format"),
    "import_hint": ("Импорт конфига: «Выбрать .conf» ищет файлы в Download/Documents, «Из буфера» — "
                    "импортирует скопированный текст, либо укажите путь вручную. "
                    "Ключи wg-quick: PrivateKey, Address, DNS, MTU, Jc/Jmin/Jmax, S1-S4, H1-H4, I1-I5, "
                    "PublicKey, Endpoint, AllowedIPs.",
                    "Import a config: 'Pick .conf' scans Download/Documents, 'Clipboard' imports copied "
                    "text, or enter the path manually. Supported wg-quick keys: PrivateKey, Address, "
                    "DNS, MTU, Jc/Jmin/Jmax, S1-S4, H1-H4, I1-I5, PublicKey, Endpoint, AllowedIPs."),
    "import_now": ("Импортировать и подключиться", "Import and connect"),
    "reset_default": ("Сбросить конфиг (вернуть встроенный, если он вшит)", "Reset config (restore built-in, if any)"),
    "path_empty": ("Укажите путь к .conf файлу", "Enter the .conf file path"),
    "file_missing": ("Файл не найден: {0}", "File not found: {0}"),
    "import_failed": ("Ошибка импорта: {0}", "Import error: {0}"),
    "imported_ok": ("Конфиг применён: {0}", "Config applied: {0}"),
    "pick_file": ("Выбрать .conf на устройстве", "Pick a .conf file on device"),
    "pick_none": (".conf файлы не найдены. Положите файл в Download (или Documents) и повторите.",
                  "No .conf files found. Put the file into Download (or Documents) and try again."),
    "pick_title": ("Выберите конфиг", "Choose a config"),
    "pick_many": ("Найдено несколько конфигов — выбран самый свежий:\n{0}",
                  "Found several configs — took the newest:\n{0}"),
    "clip_import": ("Импорт из буфера обмена", "Import from clipboard"),
    "clip_empty": ("В буфере обмена нет текста конфига (должен быть [Interface]). "
                   "Скопируйте содержимое .conf и повторите.",
                   "Clipboard has no config text ([Interface] expected). "
                   "Copy the .conf contents and try again."),
    "file_denied": ("Нет доступа к файлу: {0}\nСкопируйте его в Download или используйте «Выбрать .conf».",
                    "Cannot access file: {0}\nCopy it to Download or use 'Pick .conf'."),
    "reset_ok": ("Готово — возвращён встроенный конфиг", "Done — built-in config restored"),
    "about_text": ("AmneziaWG byTime v{0}\nСделано Time.\n"
                   "Свой userspace-движок AmneziaWG (amneziawg-go + gVisor), локальный SOCKS5, "
                   "без системного VPN. Звонки идут напрямую (UDP не туннелируется).",
                   "AmneziaWG byTime v{0}\nMade by Time.\n"
                   "Custom userspace AmneziaWG engine (amneziawg-go + gVisor), local SOCKS5, "
                   "no system VPN. Voice calls go directly (UDP is not tunneled)."),
}


def _is_russian():
    try:
        LocaleController = jclass("org.telegram.messenger.LocaleController")
        info = LocaleController.getInstance().getCurrentLocaleInfo()
        return str(info.getShortName()).lower().startswith("ru")
    except Exception:
        return False


def t(key):
    pair = TRANSLATIONS.get(key)
    if not pair:
        return key
    return pair[0] if _is_russian() else pair[1]


def _payload_source():
    # Плагин читает собственный файл: base64-движок лежит в блочных комментариях.
    import inspect
    return open(inspect.getsourcefile(lambda: None), "rb").read().decode("utf-8")


def _read_lib_payload():
    text = _payload_source()
    try:
        block = text.split("# " + LIB_BEGIN, 1)[1].split("# " + LIB_END, 1)[0]
    except IndexError:
        raise RuntimeError("engine payload is missing")
    lines = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped[1:].strip()
        if stripped:
            lines.append(stripped)
    return base64.b64decode("".join(lines))

def _check_platform():
    if int(str(BuildVersion.SDK_INT)) < 21:
        raise RuntimeError(t("need_arm64"))
    abis = list(Build.SUPPORTED_ABIS)
    if not abis or str(abis[0]) != "arm64-v8a":
        raise RuntimeError(t("need_arm64"))


# ---------- импорт пользовательских конфигураций ----------

AWG_KEYS = ("Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4",
            "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5")

_PLUGIN = None  # экземпляр плагина: нужен для get_setting/set_setting


def get_setting(key, default=None):
    if _PLUGIN is None:
        return default
    try:
        return _PLUGIN.get_setting(key, default)
    except Exception:
        return default


def set_setting(key, value):
    if _PLUGIN is None:
        return
    try:
        _PLUGIN.set_setting(key, value, reload_settings=True)
    except Exception:
        try:
            _PLUGIN.set_setting(key, value)
        except Exception:
            pass


# ---------- удобный импорт: файл, буфер обмена, путь ----------

def _normalize_path(path):
    """Чистит путь: пробелы, кавычки, префикс file://."""
    text = str(path or "").strip()
    for quote in ('"', "'"):
        if len(text) >= 2 and text.startswith(quote) and text.endswith(quote):
            text = text[1:-1].strip()
    if text.startswith("file://"):
        text = text[len("file://"):]
    return text.strip()


def _read_text_source(source):
    """Читает текст конфига из файла по пути или из content:// URI."""
    if source.startswith("content://"):
        context = ApplicationLoader.applicationContext
        uri = jclass("android.net.Uri").parse(source)
        stream = context.getContentResolver().openInputStream(uri)
        try:
            return bytes(stream.read()).decode("utf-8", "replace")
        finally:
            stream.close()
    with open(source, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _read_clipboard_text():
    try:
        context = ApplicationLoader.applicationContext
        clipboard = context.getSystemService("clipboard")
        clip = clipboard.getPrimaryClip()
        if clip is None or int(clip.getItemCount()) == 0:
            return None
        text = clip.getItemAt(0).getText()
        return str(text) if text is not None else None
    except Exception:
        return None


def _scan_conf_files():
    """Ищет .conf файлы в Download, Documents, корне памяти и каталоге приложения.
    Возвращает пути, отсортированные по свежести (новые — первыми)."""
    found = {}
    roots = []
    try:
        ext = str(jclass("android.os.Environment")
                  .getExternalStorageDirectory().getAbsolutePath())
        roots += [ext + "/Download", ext + "/Documents", ext]
    except Exception:
        pass
    try:
        ext_dir = ApplicationLoader.applicationContext.getExternalFilesDir(None)
        if ext_dir is not None:
            roots.append(str(ext_dir.getAbsolutePath()))
    except Exception:
        pass
    file_cls = jclass("java.io.File")
    for root in roots:
        try:
            children = file_cls(root).listFiles()
        except Exception:
            continue
        if children is None:
            continue
        for child in children:
            try:
                if not child.isFile():
                    continue
                name = str(child.getName()).lower()
                if (name.endswith(".conf") or name.endswith(".conf.txt")
                        or (name.endswith(".txt") and "conf" in name)):
                    found[str(child.getAbsolutePath())] = int(child.lastModified())
            except Exception:
                continue
    return sorted(found.keys(), key=lambda p: found[p], reverse=True)


def _conf_section(text, name):
    import re
    pattern = r"^\[" + name + r"\]\s*$(.*?)(?=^\[|\Z)"
    match = re.search(pattern, text, re.M | re.S)
    return match.group(1) if match else ""


def _conf_value(text, key, body, default=""):
    import re
    match = re.search(r"^\s*" + key + r"\s*=\s*(.+?)\s*$", body, re.M)
    return match.group(1) if match else default


def parse_conf_text(text):
    """Разбирает .conf (AmneziaWG/WireGuard, формат wg-quick) в конфиг движка."""
    iface = _conf_section(text, "Interface")
    peer = _conf_section(text, "Peer")
    if not iface or not peer:
        raise RuntimeError("в файле нет секций [Interface]/[Peer]")

    private_key = _conf_value(text, "PrivateKey", iface)
    public_key = _conf_value(text, "PublicKey", peer)
    endpoint = _conf_value(text, "Endpoint", peer).strip()
    if not private_key or not public_key or not endpoint:
        raise RuntimeError("нет PrivateKey / PublicKey / Endpoint")

    addresses = [a.strip() for a in _conf_value(text, "Address", iface).split(",") if a.strip()]
    addresses = [a.split("/")[0] for a in addresses]
    dns = [a.strip().split("/")[0] for a in _conf_value(text, "DNS", iface, "1.1.1.1").split(",") if a.strip()]
    allowed = [a.strip() for a in _conf_value(text, "AllowedIPs", peer, "0.0.0.0/0, ::/0").split(",") if a.strip()]

    awg = {}
    for key in AWG_KEYS:
        value = _conf_value(text, key, iface)
        if value:
            awg[key.lower()] = value

    keepalive = _conf_value(text, "PersistentKeepalive", peer, "25")
    try:
        keepalive = int(str(keepalive).strip())
    except ValueError:
        keepalive = 25

    try:
        mtu = int(_conf_value(text, "MTU", iface, "1280"))
    except ValueError:
        mtu = 1280

    return {
        "privateKey": private_key,
        "address": addresses,
        "dns": dns or ["1.1.1.1"],
        "mtu": mtu,
        "publicKey": public_key,
        "endpoint": endpoint,
        "keepalive": keepalive,
        "allowedIPs": allowed,
        "socksPort": SOCKS_PORT,
        "logLevel": 3,
        "awg": awg,
    }


def default_config():
    """Встроенный конфиг личной сборки; None — если сборка публичная."""
    if not DEFAULT_ENGINE_CONFIG_JSON:
        return None
    return json.loads(DEFAULT_ENGINE_CONFIG_JSON)


def current_config():
    """Активный конфиг: пользовательский из настроек, иначе встроенный (если вшит)."""
    raw = get_setting("custom_config_json", "")
    if raw:
        try:
            cfg = json.loads(raw)
            if cfg.get("privateKey") and cfg.get("publicKey") and cfg.get("endpoint"):
                cfg.setdefault("socksPort", SOCKS_PORT)
                cfg["socksPort"] = SOCKS_PORT
                cfg.setdefault("logLevel", 3)
                return cfg, True
        except Exception:
            pass
    return default_config(), False



class EngineCtl:
    """Загрузка libawgcore.so через ctypes и управление туннелем."""

    def __init__(self):
        self.lib = None
        self.lib_path = None
        self.port = SOCKS_PORT
        self.lock = threading.RLock()

    def ensure_loaded(self):
        with self.lock:
            if self.lib is not None:
                return
            _check_platform()
            context = ApplicationLoader.applicationContext
            if context is None:
                raise RuntimeError("application context is not ready")
            root = str(context.getDir(ENGINE_DIR_NAME, 0).getAbsolutePath())
            os.makedirs(root, exist_ok=True)
            target = os.path.join(root, LIB_NAME)

            raw = _read_lib_payload()
            expected_sha = hashlib.sha256(raw).hexdigest()

            def _write_staged(path):
                staged = path + ".tmp"
                try:
                    with open(staged, "wb") as output:
                        output.write(raw)
                        output.flush()
                        os.fsync(output.fileno())
                    os.chmod(staged, 0o700)
                    os.replace(staged, path)
                finally:
                    try:
                        os.unlink(staged)
                    except OSError:
                        pass

            need_write = True
            if os.path.exists(target):
                try:
                    digest = hashlib.sha256()
                    with open(target, "rb") as source:
                        for chunk in iter(lambda: source.read(256 * 1024), b""):
                            digest.update(chunk)
                    need_write = digest.hexdigest() != expected_sha
                except OSError:
                    need_write = True
            if need_write:
                _write_staged(target)

            from ctypes import CDLL, c_char_p, c_int
            lib = CDLL(target)
            lib.awgStart.argtypes = [c_char_p]
            lib.awgStart.restype = c_int
            lib.awgStop.argtypes = []
            lib.awgStop.restype = c_int
            lib.awgStatus.argtypes = []
            lib.awgStatus.restype = c_int
            self.lib = lib
            self.lib_path = target

    def start(self, cfg=None):
        self.ensure_loaded()
        if cfg is None:
            cfg, _ = current_config()
        self.port = int(cfg.get("socksPort") or SOCKS_PORT)
        # Если прошлый экземпляр ещё жив — гасим его и ждём освобождения порта.
        if self.status():
            self.stop()
            _wait_port_closed(2.5)
        rc = self.lib.awgStart(json.dumps(cfg).encode("utf-8"))
        if rc == 0:
            return True
        if rc == -1:
            raise RuntimeError("движок отклонил конфиг (неверный JSON)")
        if rc == -2:
            # Порт мог быть занят чем-то другим — пробуем соседние.
            for offset in range(1, 6):
                probe = dict(cfg)
                probe["socksPort"] = SOCKS_PORT + offset
                rc = self.lib.awgStart(json.dumps(probe).encode("utf-8"))
                if rc == 0:
                    self.port = SOCKS_PORT + offset
                    return True
            raise RuntimeError("движок не смог запуститься (код -2)")
        raise RuntimeError("движок не смог запуститься (код %s)" % rc)

    def wait_port(self, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.port_open():
                return True
            time.sleep(0.25)
        return False

    def verify_tunnel(self, host="1.1.1.1", port=80, timeout=8.0):
        """Проверка данных через туннель: SOCKS5-подключение внутри движка."""
        try:
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
            sock.settimeout(timeout)
            sock.sendall(b"\x05\x01\x00")
            if sock.recv(2) != b"\x05\x00":
                sock.close()
                return False
            raw = socket.inet_aton(host)
            sock.sendall(b"\x05\x01\x00\x01" + raw + struct.pack(">H", port))
            reply = sock.recv(4)
            if len(reply) < 2 or reply[1] != 0:
                sock.close()
                return False
            # Добираем остаток SOCKS5-ответа: ATYP + адрес + порт.
            atyp = reply[3]
            if atyp == 1:
                sock.recv(4 + 2)
            elif atyp == 4:
                sock.recv(16 + 2)
            elif atyp == 3:
                length = sock.recv(1)
                if length:
                    sock.recv(length[0] + 2)
            sock.sendall(b"HEAD / HTTP/1.0\r\nHost: %s\r\n\r\n" % host.encode())
            data = sock.recv(32)
            sock.close()
            return data.startswith(b"HTTP/")
        except OSError:
            return False

    def verify_with_retry(self, attempts=3, pause=1.5, timeout=8.0):
        """Проверка с повторами. При пробуждении сети (утро, смена Wi-Fi) первый
        CONNECT может не успеть за рукопожатием WireGuard — это не повод хоронить
        туннель и, тем более, стирать конфиг пользователя."""
        for attempt in range(attempts):
            if self.verify_tunnel(timeout=timeout):
                return True
            if attempt + 1 < attempts:
                time.sleep(pause)
        return False


    def stop(self):
        with self.lock:
            if self.lib is not None:
                try:
                    self.lib.awgStop()
                except Exception:
                    pass

    def status(self):
        try:
            with self.lock:
                if self.lib is None:
                    return False
                return int(self.lib.awgStatus()) == 1
        except Exception:
            return False

    def port_open(self):
        try:
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=1.5)
            sock.close()
            return True
        except OSError:
            return False


ENGINE = EngineCtl()

TUNNEL_LOCK = threading.RLock()  # сериализует все операции жизненного цикла туннеля


def _wait_port_closed(timeout=2.5):
    """Ждёт, пока SOCKS5-порт старого движка реально освободится: без этого
    awgStart получает занятый порт и молча «переползает» на соседний."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not ENGINE.port_open():
            return True
        time.sleep(0.2)
    return not ENGINE.port_open()


def install_proxy():
    """Включает SOCKS5-прокси Telegram на локальный порт движка."""
    prefs = MessagesController.getGlobalMainSettings()
    prefs.edit().putBoolean("proxy_enabled", True).apply()

    try:
        # Старый API (exteraGram 12.x): ProxyInfo(addr, port, user, pass, secret)
        info = PROXY_INFO("127.0.0.1", ENGINE.port, "", "", "")
        SharedConfig.addProxy(info)
        SharedConfig.currentProxy = info
        ConnectionsManager.setProxySettings(True, "127.0.0.1", ENGINE.port, "", "", "")
    except Exception:
        # Новый API: ProxySettings.builder() + setProxySettings(True, settings)
        ProxySettings = jclass("org.telegram.proxy.ProxySettings")
        settings = ProxySettings.builder() \
            .setAddress("127.0.0.1") \
            .setPort(ENGINE.port) \
            .setUser("") \
            .setPassword("") \
            .setSecret("") \
            .build()
        info = SharedConfig.addProxy(SharedConfig.ProxyInfo(settings))
        SharedConfig.currentProxy = info
        ConnectionsManager.setProxySettings(True, settings)

    NotificationCenter.getGlobalInstance().postNotificationName(
        NotificationCenter.proxySettingsChanged
    )
    return info


def disable_proxy():
    try:
        prefs = MessagesController.getGlobalMainSettings()
        prefs.edit().putBoolean("proxy_enabled", False).apply()
        try:
            ConnectionsManager.setProxySettings(False, "", 1080, "", "", "")
        except Exception:
            ConnectionsManager.setProxySettings(False, None)
        SharedConfig.currentProxy = None
        NotificationCenter.getGlobalInstance().postNotificationName(
            NotificationCenter.proxySettingsChanged
        )
    except Exception:
        pass


def tunnel_up(timeout=8.0):
    """Запускает туннель на активном конфиге; при провале пользовательского —
    автоматически возвращается на встроенный (если он вшит в сборку).
    Пользовательский конфиг при этом НИКОГДА не стирается: разовая неудача
    (только что проснувшаяся сеть, моргнувший сервер) не должна стоить
    пользователю его конфига."""
    with TUNNEL_LOCK:
        cfg, is_custom = current_config()
        if cfg is None:
            raise RuntimeError(t("no_config"))
        ENGINE.start(cfg)
        if not ENGINE.wait_port(timeout):
            raise RuntimeError(t("start_failed"))
        if ENGINE.verify_with_retry():
            install_proxy()
            return "custom" if is_custom else "default"
        # Трафик не идёт — глушим движок и пробуем встроенный конфиг.
        ENGINE.stop()
        _wait_port_closed(2.5)
        builtin = default_config()
        if builtin is None:
            raise RuntimeError(t("custom_bad_no_fallback"))
        if not is_custom:
            raise RuntimeError(t("tunnel_dead"))
        ENGINE.start(builtin)
        if not ENGINE.wait_port(timeout) or not ENGINE.verify_with_retry(attempts=2):
            ENGINE.stop()
            raise RuntimeError(t("custom_bad_fallback_failed"))
        install_proxy()
        return "fallback"


def restart_tunnel(timeout=8.0):
    with TUNNEL_LOCK:
        disable_proxy()
        ENGINE.stop()
        _wait_port_closed(2.5)
        return tunnel_up(timeout)


class AmneziaPlugin(BasePlugin):
    def on_plugin_load(self):
        global _PLUGIN
        _PLUGIN = self
        self.add_menu_item(
            MenuItemData(
                MenuItemType.MAIN_MENU,
                text=t("restart"),
                on_click=lambda ctx: self._restart_clicked(),
            )
        )
        self.add_menu_item(
            MenuItemData(
                MenuItemType.MAIN_MENU,
                text=t("menu_import"),
                on_click=lambda ctx: self._apply_pending_conf(),
            )
        )
        threading.Thread(target=self._start_background, daemon=True).start()

    def on_plugin_unload(self):
        disable_proxy()
        ENGINE.stop()

    def on_app_event(self, event_type):
        if event_type == AppEvent.RESUME:
            threading.Thread(target=self._resume_check, daemon=True).start()
        elif event_type == AppEvent.STOP:
            # Туннель НЕ глушим при уходе в фон: он «тёплый» и продолжает
            # обслуживать push-уведомления. Глушение здесь порождало гонку
            # с _resume_check на возврате в приложение (подключение поднималось
            # и сразу обрывалось).
            pass

    # ---------- настройки ----------

    def create_settings(self):
        from ui.settings import Divider, Header, Input, Text

        cfg, is_custom = current_config()
        if cfg is None:
            source = t("src_none")
            endpoint = "—"
            totals = "0"
        else:
            source = t("src_custom") if is_custom else t("src_default")
            endpoint = str(cfg.get("endpoint") or "?")
            totals = str(len(list(cfg.get("awg") or {})))

        try:
            path = self.get_setting("conf_path", "") or ""
        except Exception:
            path = ""

        return [
            Header(text=t("settings_server")),
            Text(link_alias="awg_current", icon="msg_info",
                 text=t("current_server").format(endpoint, source)),
            Text(link_alias="awg_awg_params", icon="msg_info",
                 text=t("current_awg").format(totals)),
            Divider(text=t("import_hint")),
            Text(
                link_alias="awg_pick",
                text=t("pick_file"),
                icon="msg_file",
                accent=True,
                on_click=self._pick_conf_clicked,
            ),
            Text(
                link_alias="awg_clip",
                text=t("clip_import"),
                icon="msg_copy",
                on_click=self._clipboard_clicked,
            ),
            Input(
                key="conf_path",
                link_alias="awg_conf_path",
                default=path,
                text=t("conf_path"),
                subtext=t("conf_path_hint"),
                icon="msg_file",
            ),
            Text(
                link_alias="awg_import",
                text=t("import_now"),
                icon="msg_file",
                accent=True,
                on_click=self._import_clicked,
            ),
            Text(
                link_alias="awg_reset",
                text=t("reset_default"),
                icon="msg_reset",
                red=True,
                on_click=self._reset_clicked,
            ),
            Header(text=t("settings_about")),
            Text(link_alias="awg_about", icon="msg_info",
                 text=t("about_text")),
        ]

    # ---------- workers ----------

    def _start_background(self):
        try:
            BulletinHelper.show(t("starting"))
            result = tunnel_up()
            if result == "custom":
                BulletinHelper.show(t("running_custom"))
            else:
                BulletinHelper.show(t("running"))
        except Exception as exc:
            BulletinHelper.show(str(exc) or t("start_failed"))

    def _resume_check(self):
        with TUNNEL_LOCK:
            try:
                if ENGINE.status() and ENGINE.port_open():
                    # Движок жив — просто убеждаемся, что прокси включён.
                    # Жёсткая проверка трафика здесь не нужна: WireGuard
                    # само-восстанавливается при первом же пакете, а неудачный
                    # verify на проснувшейся сети раньше убивал рабочий туннель.
                    prefs = MessagesController.getGlobalMainSettings()
                    if not prefs.getBoolean("proxy_enabled", False):
                        install_proxy()
                    return
                restart_tunnel()
            except Exception:
                pass

    def _full_stop(self):
        disable_proxy()
        ENGINE.stop()

    # ---------- импорт конфигураций ----------

    def _conf_path(self):
        try:
            return str(self.get_setting("conf_path", "") or "").strip()
        except Exception:
            return ""

    def _import_clicked(self, *args):
        path = _normalize_path(self._conf_path())
        if not path:
            BulletinHelper.show(t("path_empty"))
            return
        self._import_path(path)

    def _import_path(self, raw_path):
        """Читает .conf (файл или URI), применяет и перезапускает туннель."""
        def worker():
            path = _normalize_path(raw_path)
            try:
                try:
                    text = _read_text_source(path)
                except PermissionError:
                    BulletinHelper.show(t("file_denied").format(path))
                    return
                except OSError:
                    BulletinHelper.show(t("file_missing").format(path))
                    return
                cfg = parse_conf_text(text)
            except Exception as exc:
                BulletinHelper.show(t("import_failed").format(str(exc)))
                return
            set_setting("conf_path", path)
            set_setting("custom_config_json", json.dumps(cfg))
            BulletinHelper.show(t("starting"))
            try:
                result = restart_tunnel()
                BulletinHelper.show(t("running_fallback") if result == "fallback"
                                    else t("imported_ok").format(str(cfg.get("endpoint"))))
            except Exception as exc:
                BulletinHelper.show(t("import_failed").format(str(exc) or t("start_failed")))

        threading.Thread(target=worker, daemon=True).start()

    def _pick_conf_clicked(self, *args):
        """Кнопка «Выбрать .conf»: ищет файлы в Download/Documents и предлагает выбор."""
        def worker():
            try:
                candidates = _scan_conf_files()
            except Exception:
                candidates = []
            if not candidates:
                BulletinHelper.show(t("pick_none"))
                return
            if len(candidates) == 1:
                self._import_path(candidates[0])
                return
            run_on_ui_thread(lambda: self._show_conf_chooser(candidates))

        threading.Thread(target=worker, daemon=True).start()

    def _show_conf_chooser(self, candidates):
        """Диалог выбора конфига; при неудаче — берём самый свежий и сообщаем список."""
        options = list(candidates)
        try:
            from client_utils import get_last_fragment
            fragment = get_last_fragment()
            activity = None
            if fragment is not None:
                for getter in ("getParentActivity", "getActivity"):
                    try:
                        activity = getattr(fragment, getter)()
                    except Exception:
                        activity = None
                    if activity is not None:
                        break
            if activity is None:
                raise RuntimeError("activity not ready")

            click_cls = jclass("android.content.DialogInterface$OnClickListener")
            plugin = self

            class _Choose(click_cls):
                def onClick(self, dialog, which):
                    index = int(which)
                    if 0 <= index < len(options):
                        plugin._import_path(options[index])

            names = [c.rsplit("/", 1)[-1] for c in options]
            try:
                from jarray import array as jarray_array
                items = jarray_array(names, jclass("java.lang.String"))
            except Exception:
                items = names
            jclass("android.app.AlertDialog$Builder")(activity) \
                .setTitle(t("pick_title")) \
                .setItems(items, _Choose()) \
                .show()
        except Exception:
            BulletinHelper.show(t("pick_many").format("\n".join(options[:5])))
            self._import_path(options[0])

    def _clipboard_clicked(self, *args):
        def worker():
            text = _read_clipboard_text()
            if not text or "[interface]" not in text.lower():
                BulletinHelper.show(t("clip_empty"))
                return
            try:
                cfg = parse_conf_text(text)
            except Exception as exc:
                BulletinHelper.show(t("import_failed").format(str(exc)))
                return
            set_setting("custom_config_json", json.dumps(cfg))
            BulletinHelper.show(t("starting"))
            try:
                result = restart_tunnel()
                BulletinHelper.show(t("running_fallback") if result == "fallback"
                                    else t("imported_ok").format(str(cfg.get("endpoint"))))
            except Exception as exc:
                BulletinHelper.show(t("import_failed").format(str(exc) or t("start_failed")))

        threading.Thread(target=worker, daemon=True).start()

    def _reset_clicked(self, *args):
        def worker():
            try:
                set_setting("custom_config_json", "")
                if default_config() is None:
                    # Публичная сборка: встроенного конфига нет — останавливаем туннель.
                    disable_proxy()
                    ENGINE.stop()
                    BulletinHelper.show(t("no_config"))
                    return
                BulletinHelper.show(t("starting"))
                restart_tunnel()
                BulletinHelper.show(t("reset_ok"))
            except Exception as exc:
                BulletinHelper.show(str(exc) or t("start_failed"))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_pending_conf(self):
        """Пункт меню: применить конфиг из ранее указанного пути."""
        path = self._conf_path()
        if path:
            self._import_clicked()
        else:
            self._restart_clicked()

    def _restart_clicked(self):
        def worker():
            try:
                BulletinHelper.show(t("starting"))
                result = restart_tunnel()
                if result == "custom":
                    BulletinHelper.show(t("running_custom"))
                elif result == "fallback":
                    BulletinHelper.show(t("running_fallback"))
                else:
                    BulletinHelper.show(t("running"))
            except Exception as exc:
                BulletinHelper.show(str(exc) or t("start_failed"))

        threading.Thread(target=worker, daemon=True).start()


# __LIB_BEGIN__
# __LIB_END__
