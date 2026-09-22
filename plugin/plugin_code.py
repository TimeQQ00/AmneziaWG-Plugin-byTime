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
import random
import socket
import struct
import threading
import time

from base_plugin import AppEvent, BasePlugin, MenuItemData, MenuItemType
from android_utils import run_on_ui_thread
try:
    from android_utils import log as sdk_log  # журнал exteraGram/Android logcat
except Exception:
    def sdk_log(*args, **kwargs):
        pass
from ui.bulletin import BulletinHelper

from java import jclass

__id__ = "amnezia_awg_byTime"
__name__ = "AmneziaWG byTime"
__description__ = "AmneziaWG-туннель для Telegram со своими конфигами. Сделано Time"
__author__ = "Time"
__version__ = "1.3.1"
__icon__ = "exteraPlugins/1"
__app_version__ = ">=12.5.1"
__sdk_version__ = ">=1.4.4.3"

SOCKS_PORT = 10809
ENGINE_DIR_NAME = "awgcore"
LIB_NAME = "libawgcore.so"
LIB_BEGIN = "__LIB_BEGIN__"
LIB_END = "__LIB_END__"

# ---------- журнал событий (для диагностики на устройстве) ----------
_LOG_LINES = []
_LOG_MAX = 120


def _log(message):
    line = "%s | %s" % (time.strftime("%H:%M:%S"), message)
    _LOG_LINES.append(line)
    if len(_LOG_LINES) > _LOG_MAX:
        del _LOG_LINES[:len(_LOG_LINES) - _LOG_MAX]
    try:
        sdk_log("[AWG] " + str(message))
    except Exception:
        pass

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
    "diag": ("Диагностика подключения", "Run connection diagnostics"),
    "diag_title": ("Amnezia byTime — диагностика", "Amnezia byTime — diagnostics"),
    "gen_config": ("Сгенерировать WARP-конфиг и подключиться", "Generate WARP config and connect"),
    "gen_hint": ("Создаёт новый WARP-аккаунт в Cloudflare (свежие ключи, новый I1 из "
                 "проверенного пула, живой endpoint) и сразу подключается. Раньше "
                 "импортированные конфиги при этом сохраняются и остаются доступными.",
                 "Creates a fresh WARP account (new keys, new I1 from the verified pool, "
                 "live endpoint) and connects right away. Previously imported configs "
                 "are kept."),
    "gen_started": ("Генерирую WARP-конфиг… (до 30 секунд)", "Generating WARP config… (up to 30 s)"),
    "gen_failed": ("Ошибка генерации: {0}\nПроверьте интернет и повторите.", "Generation failed: {0}\nCheck internet and retry."),
    "rot_progress": ("Подбираю рабочий endpoint {0}/{1}: {2}…", "Trying endpoint {0}/{1}: {2}…"),
    "rot_failed": ("Не сработал ни один WARP endpoint (перебраны порты 2408/4500/500/1701/8854/880). "
                   "Похоже, WARP заблокирован в твоей сети. Попробуй: другой Wi-Fi/мобильный интернет, "
                   "или выключи другой VPN (иконка «VPN» в шторке).",
                   "No WARP endpoint worked (tried ports 2408/4500/500/1701/8854/880). "
                   "WARP is likely blocked in your network. Try: another Wi-Fi/mobile data, "
                   "or disable the other VPN (the 'VPN' icon in the status bar)."),
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


def _network_state():
    """Есть ли у телефона интернет вообще (проверка мимо туннеля)."""
    try:
        sock = socket.create_connection(("1.1.1.1", 443), timeout=3.0)
        sock.close()
        return "есть (прямое соединение 1.1.1.1:443)"
    except OSError as exc:
        return "НЕТ (%s) — без интернета туннель не поднимется" % exc


# ---------- WARP-генератор конфигов (порт amnezia-config-gen) ----------

WARP_API_BASE = "https://api.cloudflareclient.com/v0i1909051800"
WARP_PEER_PUBKEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
WARP_USER_AGENT = "okhttp/3.12.1"
WARP_ENDPOINTS = (
    "162.159.192.1:2408", "162.159.192.8:2408",
    "162.159.193.1:2408", "162.159.193.8:2408",
    "162.159.195.1:2408", "162.159.195.8:2408",
    "188.114.96.1:2408", "188.114.96.8:2408",
    "188.114.97.1:2408", "188.114.97.66:2408",
    "188.114.99.1:2408",
)

_P = 2 ** 255 - 19


def _x25519_scalarmult(scalar32, u_bytes):
    """X25519 (RFC 7748), умножение Монтгомери — чистый Python, без зависимостей."""
    k = bytearray(scalar32)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    k_int = int.from_bytes(bytes(k), "little")
    x1 = int.from_bytes(u_bytes, "little") % _P
    x2, z2, x3, z3 = 1, 0, x1, 1
    swap = 0
    for t in range(254, -1, -1):
        kt = (k_int >> t) & 1
        swap ^= kt
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = kt
        a = (x2 + z2) % _P
        aa = (a * a) % _P
        b = (x2 - z2) % _P
        bb = (b * b) % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = (d * a) % _P
        cb = (c * b) % _P
        x3 = (da + cb) % _P
        x3 = (x3 * x3) % _P
        z3 = (da - cb) % _P
        z3 = (z3 * z3 * x1) % _P
        x2 = (aa * bb) % _P
        z2 = (e * ((aa + 121665 * e) % _P)) % _P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    return ((x2 * pow(z2, _P - 2, _P)) % _P).to_bytes(32, "little")


def _x25519_keypair_b64():
    """Пара ключей WireGuard (X25519) в base64 — как того ждёт Cloudflare WARP."""
    priv = os.urandom(32)
    pub = _x25519_scalarmult(priv, b"\x09" + b"\x00" * 31)
    return base64.b64encode(priv).decode("ascii"), base64.b64encode(pub).decode("ascii")


def _sip_cps_i1():
    """Свежий SIP-вариант CPS (порт generateSipCpsPair из amnezia-config-gen)."""
    branch = "z9hG4bK%d" % random.randint(100000000, 999999999)
    call_id = "%d@pc33.atlanta.com" % random.randint(100000000, 999999999)
    tag = str(random.randint(1000000000, 9999999999))
    cseq = random.randint(10000, 99999)
    invite = "\r\n".join([
        "INVITE sip:bob@biloxi.com SIP/2.0",
        "Via: SIP/2.0/UDP pc33.atlanta.com;branch=" + branch,
        "Max-Forwards: 70",
        "To: Bob <sip:bob@biloxi.com>",
        "From: Alice <sip:alice@atlanta.com>;tag=" + tag,
        "Call-ID: " + call_id,
        "CSeq: %d INVITE" % cseq,
        "Contact: <sip:alice@pc33.atlanta.com>",
        "Content-Type: application/sdp",
        "Content-Length: 0",
        "", "",
    ])
    return "<b 0x%s>" % invite.encode("utf-8").hex()


def _pick_i1():
    """I1: случайный пейлоад из проверенного пула либо свежий SIP-вариант."""
    return random.choice(list(I1_PAYLOAD_POOL) + [_sip_cps_i1()])


def _pick_warp_endpoint():
    """Живой endpoint WARP: TCP-проба по списку, иначе случайный из списка."""
    candidates = list(WARP_ENDPOINTS)
    random.shuffle(candidates)
    for hostport in candidates[:6]:
        host, _, port = hostport.rpartition(":")
        try:
            probe = socket.create_connection((host, int(port)), timeout=2.0)
            probe.close()
            return hostport
        except OSError:
            continue
    return candidates[0]


# WARP отвечает на нескольких UDP-портах; операторы часто блокируют выборочно.
WARP_PORTS = (2408, 4500, 500, 1701, 8854, 880)


def _warp_endpoint_candidates():
    """Кандидаты «ip:порт»: сначала IP, где TCP отвечает, потом остальные;
    каждый IP перебирается на всех известных WARP-портах."""
    ips = []
    for hostport in WARP_ENDPOINTS:
        host = hostport.rpartition(":")[0]
        if host not in ips:
            ips.append(host)
    alive, rest = [], []
    for host in ips:
        reachable = False
        for port in (2408, 4500):
            try:
                probe = socket.create_connection((host, port), timeout=1.0)
                probe.close()
                reachable = True
                break
            except OSError:
                continue
        (alive if reachable else rest).append(host)
    ordered = alive + rest
    candidates = []
    for port in WARP_PORTS:
        for host in ordered:
            candidates.append("%s:%d" % (host, port))
    return candidates


def _try_warp_endpoints(cfg, max_tries=12):
    """Перебирает комбинации endpoint:порт с настоящей проверкой трафика
    (реальный WireGuard-хендшейк через движок). Возвращает cfg с рабочим
    endpoint'ом либо None, если не подошёл ни один."""
    candidates = _warp_endpoint_candidates()
    total = min(len(candidates), max_tries)
    tried = 0
    for ep in candidates:
        if tried >= total:
            break
        tried += 1
        if total > 1:
            BulletinHelper.show(t("rot_progress").format(tried, total, ep))
        _log("ротация: пробую %s (%d/%d)" % (ep, tried, total))
        trial = dict(cfg)
        trial["endpoint"] = ep
        try:
            ENGINE.start(trial)
        except Exception as exc:
            _log("ротация: старт не удался на %s: %s" % (ep, exc))
            continue
        if not ENGINE.wait_port(8.0):
            ENGINE.stop()
            _wait_port_closed(1.0)
            continue
        if ENGINE.verify_with_retry(attempts=1, timeout=6.0):
            _log("ротация: РАБОЧИЙ endpoint найден — %s" % ep)
            return trial
        ENGINE.stop()
        _wait_port_closed(1.0)
    return None


def _warp_api(method, path, body=None, token=None):
    """Запрос к api.cloudflareclient.com через java.net — TLS и хранилище CA Android."""
    URL = jclass("java.net.URL")
    conn = URL(WARP_API_BASE + "/" + path).openConnection()
    conn.setConnectTimeout(15000)
    conn.setReadTimeout(20000)
    conn.setRequestProperty("Content-Type", "application/json")
    conn.setRequestProperty("User-Agent", WARP_USER_AGENT)
    if token:
        conn.setRequestProperty("Authorization", "Bearer " + token)
    if method == "PATCH":
        # HttpURLConnection не умеет PATCH — используем override-заголовок.
        conn.setRequestMethod("POST")
        conn.setRequestProperty("X-HTTP-Method-Override", "PATCH")
    else:
        conn.setRequestMethod(method)
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        conn.setDoOutput(True)
        conn.setFixedLengthStreamingMode(len(payload))
        out = conn.getOutputStream()
        out.write(payload)
        out.flush()
        out.close()
    code = int(conn.getResponseCode())
    stream = conn.getInputStream() if code < 400 else conn.getErrorStream()
    text_out = ""
    if stream is not None:
        reader = jclass("java.io.BufferedReader")(
            jclass("java.io.InputStreamReader")(stream, "UTF-8"))
        parts = []
        while True:
            line = reader.readLine()
            if line is None:
                break
            parts.append(str(line))
        reader.close()
        text_out = "\n".join(parts)
    if code >= 400:
        try:
            message = json.loads(text_out).get("message") if text_out else None
        except Exception:
            message = None
        raise RuntimeError("Cloudflare API %s: HTTP %s %s" % (path, code, message or ""))
    return json.loads(text_out) if text_out else {}


def generate_warp_config_text():
    """Генерирует полный WARP-конфиг (.conf): регистрация аккаунта в Cloudflare,
    свежие ключи, warp-safe обфускация и I1 из проверенного пула CPS-пейлоадов."""
    priv_b64, pub_b64 = _x25519_keypair_b64()
    _log("генерация: регистрирую WARP-аккаунт")
    reg = _warp_api("POST", "reg", {
        "install_id": "",
        "tos": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "key": pub_b64,
        "fcm_token": "",
        "type": "ios",
        "locale": "en_US",
    })
    result = reg.get("result") or {}
    reg_id = result.get("id")
    token = result.get("token")
    if not reg_id or not token:
        raise RuntimeError("в ответе WARP нет id/token")
    try:
        _warp_api("PATCH", "reg/%s" % reg_id, {"warp_enabled": True}, token)
    except Exception as exc:
        _log("PATCH warp_enabled не прошёл (не критично): %s" % exc)
    try:
        refreshed = _warp_api("GET", "reg/%s" % reg_id, token=token)
        config = (refreshed.get("result") or {}).get("config") or result.get("config") or {}
    except Exception:
        config = result.get("config") or {}
    peers = config.get("peers") or []
    peer_pub = (peers[0].get("public_key") if peers else None) or WARP_PEER_PUBKEY
    addresses = (config.get("interface") or {}).get("addresses") or {}
    v4 = addresses.get("v4")
    v6 = addresses.get("v6")
    if not v4:
        raise RuntimeError("WARP не вернул IPv4-адрес")
    _log("генерация: адрес %s готов" % v4)
    endpoint = _pick_warp_endpoint()
    i1 = _pick_i1()
    return "\n".join([
        "[Interface]",
        "PrivateKey = " + priv_b64,
        "Address = %s/32, %s/128" % (v4.split("/")[0],
                                     str(v6 or "2606:4700:110::1").split("/")[0]),
        "DNS = 1.1.1.1, 1.0.0.1",
        "Jc = 4",
        "Jmin = 40",
        "Jmax = 70",
        "S1 = 0", "S2 = 0", "S3 = 0", "S4 = 0",
        "H1 = 1", "H2 = 2", "H3 = 3", "H4 = 4",
        "I1 = " + i1,
        "MTU = 1280",
        "",
        "[Peer]",
        "PublicKey = " + peer_pub,
        "AllowedIPs = 0.0.0.0/0, ::/0",
        "Endpoint = " + endpoint,
        "PersistentKeepalive = 25",
    ])


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
            _log("движок загружен: " + target)

    def start(self, cfg=None):
        self.ensure_loaded()
        if cfg is None:
            cfg, _ = current_config()
        self.port = int(cfg.get("socksPort") or SOCKS_PORT)
        # Если прошлый экземпляр ещё жив — гасим его и ждём освобождения порта.
        if self.status():
            _log("start: прошлый экземпляр ещё жив — глушу")
            self.stop()
            _wait_port_closed(2.5)
        _log("awgStart: endpoint=%s port=%s" % (cfg.get("endpoint"), self.port))
        rc = self.lib.awgStart(json.dumps(cfg).encode("utf-8"))
        _log("awgStart: rc=%s" % rc)
        if rc == 0:
            return True
        if rc == -1:
            raise RuntimeError("движок отклонил конфиг (неверный JSON)")
        if rc == -2:
            # Порт мог быть занят чем-то другим — пробуем соседние.
            _log("awgStart -2: порт занят, пробую соседние")
            for offset in range(1, 6):
                probe = dict(cfg)
                probe["socksPort"] = SOCKS_PORT + offset
                rc = self.lib.awgStart(json.dumps(probe).encode("utf-8"))
                if rc == 0:
                    self.port = SOCKS_PORT + offset
                    _log("awgStart OK на порту %s" % self.port)
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
            ok = self.verify_tunnel(timeout=timeout)
            _log("verify #%s/%s: %s" % (attempt + 1, attempts, "ok" if ok else "fail"))
            if ok:
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
    _log("install_proxy: port=%s" % ENGINE.port)
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
        _log("tunnel_up: source=%s endpoint=%s" % ("custom" if is_custom else "baked",
                                                   cfg.get("endpoint")))
        ENGINE.start(cfg)
        if not ENGINE.wait_port(timeout):
            _log("tunnel_up: порт не открылся за %s c" % timeout)
            raise RuntimeError(t("start_failed"))
        if ENGINE.verify_with_retry():
            _log("tunnel_up: OK (%s)" % ("custom" if is_custom else "baked"))
            install_proxy()
            return "custom" if is_custom else "default"
        # Трафик не идёт. Для сгенерированных WARP-конфигов сначала пробуем
        # другие endpoint'ы и порты — операторы часто блокируют выборочно.
        if cfg.get("generated"):
            _log("tunnel_up: трафик не идёт, перебираю WARP endpoint'ы")
            working = _try_warp_endpoints(cfg)
            if working is not None:
                set_setting("custom_config_json", json.dumps(working))
                install_proxy()
                return "custom"
            ENGINE.stop()
            _wait_port_closed(2.5)
            raise RuntimeError(t("rot_failed"))
        # Трафик не идёт — глушим движок и пробуем встроенный конфиг.
        _log("tunnel_up: трафик не идёт, пробую встроенный")
        ENGINE.stop()
        _wait_port_closed(2.5)
        builtin = default_config()
        if builtin is None:
            raise RuntimeError(t("custom_bad_no_fallback") + "\nendpoint: %s" % cfg.get("endpoint"))
        if not is_custom:
            raise RuntimeError(t("tunnel_dead") + "\nendpoint: %s" % cfg.get("endpoint"))
        ENGINE.start(builtin)
        if not ENGINE.wait_port(timeout) or not ENGINE.verify_with_retry(attempts=2):
            ENGINE.stop()
            raise RuntimeError(t("custom_bad_fallback_failed") + "\nendpoint: %s" % cfg.get("endpoint"))
        install_proxy()
        _log("tunnel_up: fallback на встроенный")
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
            Divider(text=t("gen_hint")),
            Text(
                link_alias="awg_gen",
                text=t("gen_config"),
                icon="msg_saved",
                accent=True,
                on_click=self._generate_clicked,
            ),
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
            Text(
                link_alias="awg_diag",
                text=t("diag"),
                icon="msg_info",
                on_click=self._diag_clicked,
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
            _log("старт не удался: %s" % exc)
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
                    proxy_current = None
                    try:
                        proxy_current = SharedConfig.currentProxy
                    except Exception:
                        pass
                    if not prefs.getBoolean("proxy_enabled", False) or proxy_current is None:
                        _log("resume: движок жив, но прокси выключен — включаю")
                        install_proxy()
                    else:
                        _log("resume: движок и прокси в порядке")
                    return
                _log("resume: движок мёртв — перезапуск")
                restart_tunnel()
            except Exception as exc:
                _log("resume: ошибка: %s" % exc)
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
                _log("рестарт не удался: %s" % exc)
                BulletinHelper.show(str(exc) or t("start_failed"))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- диагностика ----------

    def _diag_clicked(self, *args):
        """Проверяет всю цепочку «конфиг → сервер → движок → порт → трафик →
        прокси Telegram» и показывает вердикт с журналом последних событий."""
        def worker():
            lines = []
            verdict = None
            try:
                cfg, is_custom = current_config()
                if cfg is None:
                    lines.append("КОНФИГ: не задан — вот причина. Нажмите «Выбрать .conf» в настройках.")
                    self._show_diag_dialog(lines)
                    return
                lines.append("КОНФИГ: %s, endpoint %s" % (
                    "ваш импортированный" if is_custom else "вшитый в сборку",
                    cfg.get("endpoint")))

                lines.append("ИНТЕРНЕТ У ТЕЛЕФОНА: " + _network_state())

                ep = str(cfg.get("endpoint") or "")
                ep_host, _, ep_port = ep.rpartition(":")
                if ep_host and ep_port:
                    try:
                        probe = socket.create_connection((ep_host, int(ep_port)), timeout=4.0)
                        probe.close()
                        lines.append("ENDPOINT %s: доступен" % ep)
                    except OSError as exc:
                        lines.append("ENDPOINT %s: НЕДОСТУПЕН (%s) — сервер лежит или порт закрыт" % (ep, exc))
                else:
                    lines.append("ENDPOINT: не распознан (%r)" % ep)

                lines.append("ДВИЖОК: %s, статус: %s" % (
                    "загружен" if ENGINE.lib is not None else "не загружен",
                    "работает" if ENGINE.status() else "остановлен"))

                port_open = ENGINE.port_open()
                lines.append("ПОРТ 127.0.0.1:%s: %s" % (ENGINE.port, "открыт" if port_open else "закрыт"))

                verify_ok = None
                if port_open:
                    verify_ok = ENGINE.verify_tunnel(timeout=8.0)
                    lines.append("ТРАФИК ЧЕРЕЗ ТУННЕЛЬ: %s" % ("идёт" if verify_ok else "НЕ идёт"))

                proxy_current = None
                try:
                    proxy_current = SharedConfig.currentProxy
                except Exception:
                    pass
                try:
                    proxy_pref = MessagesController.getGlobalMainSettings().getBoolean(
                        "proxy_enabled", False)
                except Exception:
                    proxy_pref = False
                lines.append("ПРОКСИ TELEGRAM: pref=%s, currentProxy=%s" % (
                    proxy_pref, "задан" if proxy_current is not None else "НЕТ"))

                if verify_ok and proxy_current is not None:
                    verdict = "ВСЁ РАБОТАЕТ: туннель и прокси в порядке. Если страницы грузятся с задержкой — Telegram переподключается, подождите пару секунд."
                elif verify_ok and proxy_current is None:
                    verdict = "ТУННЕЛЬ РАБОТАЕТ, НО ПРОКСИ TELEGRAM ВЫКЛЮЧЕН. Нажмите «Перезапустить туннель» в меню плагина."
                elif port_open and verify_ok is False:
                    verdict = ("ДВИЖОК РАБОТАЕТ, НО ТРАФИК НЕ ИДЁТ: сервер %s недоступен "
                               "изнутри туннеля или конфиг устарел — возьмите свежий .conf у администратора." % ep)
                elif not port_open and ENGINE.lib is not None:
                    verdict = "ДВИЖОК ЕСТЬ, НО ПОРТ ЗАКРЫТ. Нажмите «Перезапустить туннель»; если не поможет — пришлите журнал из этого окна."
                elif ENGINE.lib is None:
                    verdict = "ДВИЖОК НЕ ЗАГРУЖЕН. Переустановите плагин."
            except Exception as exc:
                lines.append("ОШИБКА ДИАГНОСТИКИ: %s" % exc)
            lines.append("")
            lines.append("--- журнал (последние события) ---")
            lines.extend(_LOG_LINES[-30:])
            if verdict:
                lines.insert(0, "ВЕРДИКТ: " + verdict)
            self._show_diag_dialog(lines)

        threading.Thread(target=worker, daemon=True).start()

    def _generate_clicked(self, *args):
        """Кнопка «Сгенерировать»: новый WARP-аккаунт → перебор endpoint'ов → подключение."""
        BulletinHelper.show(t("gen_started"))

        def worker():
            try:
                text = generate_warp_config_text()
                cfg = parse_conf_text(text)
                cfg["generated"] = True
            except Exception as exc:
                _log("генерация не удалась: %s" % exc)
                BulletinHelper.show(t("gen_failed").format(str(exc)))
                return
            set_setting("custom_config_json", json.dumps(cfg))
            _log("генерация: конфиг готов, подбираю рабочий endpoint")
            with TUNNEL_LOCK:
                try:
                    disable_proxy()
                    working = _try_warp_endpoints(cfg)
                    if working is None:
                        ENGINE.stop()
                        _log("ротация: ни один endpoint не подошёл")
                        BulletinHelper.show(t("rot_failed"))
                        return
                    set_setting("custom_config_json", json.dumps(working))
                    install_proxy()
                    BulletinHelper.show(t("imported_ok").format(str(working.get("endpoint"))))
                except Exception as exc:
                    BulletinHelper.show(t("import_failed").format(str(exc) or t("start_failed")))

        threading.Thread(target=worker, daemon=True).start()

    def _show_diag_dialog(self, lines):
        def show():
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
                jclass("android.app.AlertDialog$Builder")(activity) \
                    .setTitle(t("diag_title")) \
                    .setMessage("\n".join(lines)) \
                    .setPositiveButton("OK", None) \
                    .show()
            except Exception:
                BulletinHelper.show("\n".join(lines[:12]))
        run_on_ui_thread(show)


# __I1_POOL_BEGIN__
I1_PAYLOAD_POOL = (
    '<b 0xce000000010897a297ecc34cd6dd000044d0ec2e2e1ea2991f467ace4222129b5a098823784694b4897b9986ae0b7280135fa85e196d9ad980b150122129ce2a9379531b0fd3e871ca5fdb883c369832f730e272d7b8b74f393f9f0fa43f11e510ecb2219a52984410c204cf875585340c62238e14ad04dff382f2c200e0ee22fe743b9c6b8b043121c5710ec289f471c91ee414fca8b8be8419ae8ce7ffc53837f6ade262891895f3f4cecd31bc93ac5599e18e4f01b472362b8056c3172b513051f8322d1062997ef4a383b01706598d08d48c221d30e74c7ce000cdad36b706b1bf9b0607c32ec4b3203a4ee21ab64df336212b9758280803fcab14933b0e7ee1e04a7becce3e2633f4852585c567894a5f9efe9706a151b615856647e8b7dba69ab357b3982f554549bef9256111b2d67afde0b496f16962d4957ff654232aa9e845b61463908309cfd9de0a6abf5f425f577d7e5f6440652aa8da5f73588e82e9470f3b21b27b28c649506ae1a7f5f15b876f56abc4615f49911549b9bb39dd804fde182bd2dcec0c33bad9b138ca07d4a4a1650a2c2686acea05727e2a78962a840ae428f55627516e73c83dd8893b02358e81b524b4d99fda6df52b3a8d7a5291326e7ac9d773c5b43b8444554ef5aea104a738ed650aa979674bbed38da58ac29d87c29d387d80b526065baeb073ce65f075ccb56e47533aef357dceaa8293a523c5f6f790be90e4731123d3c6152a70576e90b4ab5bc5ead01576c68ab633ff7d36dcde2a0b2c68897e1acfc4d6483aaaeb635dd63c96b2b6a7a2bfe042f6aed82e5363aa850aace12ee3b1a93f30d8ab9537df483152a5527faca21efc9981b304f11fc95336f5b9637b174c5a0659e2b22e159a9fed4b8e93047371175b1d6d9cc8ab745f3b2281537d1c75fb9451871864efa5d184c38c185fd203de206751b92620f7c369e031d2041e152040920ac2c5ab5340bfc9d0561176abf10a147287ea90758575ac6a9f5ac9f390d0d5b23ee12af583383d994e22c0cf42383834bcd3ada1b3825a0664d8f3fb678261d57601ddf94a8a68a7c273a18c08aa99c7ad8c6c42eab67718843597ec9930457359dfdfbce024afc2dcf9348579a57d8d3490b2fa99f278f1c37d87dad9b221acd575192ffae1784f8e60ec7cee4068b6b988f0433d96d6a1b1865f4e155e9fe020279f434f3bf1bd117b717b92f6cd1cc9bea7d45978bcc3f24bda631a36910110a6ec06da35f8966c9279d130347594f13e9e07514fa370754d1424c0a1545c5070ef9fb2acd14233e8a50bfc5978b5bdf8bc1714731f798d21e2004117c61f2989dd44f0cf027b27d4019e81ed4b5c31db347c4a3a4d85048d7093cf16753d7b0d15e078f5c7a5205dc2f87e330a1f716738dce1c6180e9d02869b5546f1c4d2748f8c90d9693cba4e0079297d22fd61402dea32ff0eb69ebd65a5d0b687d87e3a8b2c42b648aa723c7c7daf37abcc4bb85caea2ee8f55bec20e913b3324ab8f5c3304f820d42ad1b9f2ffc1a3af9927136b4419e1e579ab4c2ae3c776d293d397d575df181e6cae0a4ada5d67ecea171cca3288d57c7bbdaee3befe745fb7d634f70386d873b90c4d6c6596bb65af68f9e5121e67ebf0d89d3c909ceedfb32ce9575a7758ff080724e1ab5d5f43074ecb53a479af21ed03d7b6899c36631c0166f9d47e5e1d4528a5d3d3f744029c4b1c190cbfbad06f5f83f7ad0429fa9a2719c56ffe3783460e166de2d8>',
    '<b 0xc7000000010809a1ed4edbbe7615000044d017a61a0d774f04290f119e701ef0035df2b0ed571b0b575e6a07246b856eb6ec036fef07f1e07b861251ad737abeb67e64be714c1dcd865312b1b6c35c089c997aeb5c18f808696fe97289513945d84ca846467603e94e44224877f2c1d3261e4ac18740be4bd064369c94fc08978d99b54bf615250998639010c1284248e1d73004b81fcb20b559d8a17eced7eab3964b5b88ca7a3b8579fc8c1c934189e77143b4ac434138114b1048651b56545b87acbef0952763538f3ddeb37cfc6d58b4881c3b719d7ff78f6ee1324a2914a32381c05a64c700466d280be007253bb030d179c4f1b3dc221e1974e2ee6d6e2b9e8d709159b5ef22e1783dbba845c20ca1c83b066c73835920ad70b806df0aee0351e3fc9ab1e42e8b2a30fe235ff0612eee19744949cecee0463b76514ad90c1f7ceaa557c18586ab561d49482e73c85d0143785da14a441bf82f78783b61cccd44aecb1947516e79b5ca5a6b3a8aed6040fae0eeabdc55a88dc19ade832d99fca90c7a629cacc07192d7e47e3c6a271b95b0ea3392562a06a1cab79f40ea92916ebee197b7b5f14b251824e1ed20ff2ca80b1f03a43e45157589bc61b978e97851025b3b7ccc17d291e1cb60fe48a5c26829dce11dd23c2e73265a9ebf8617c985e4fee4681e863f990061f4dea465a7d2524bd0edcf4b48d4b8f25fc359b15babd2637284a4774077dca60091f1a781cfee1bef9713dd5943a579d7470bc5970542fbb27fdf77880a8d8751b1f642c7a3f019a05ab94bf63d3525ef34e9290b5c8d477f2714e6d6e3e4d35c1983f5e16fda57fcdf071b513f8f088dbe8d5a97577d17a5383a496c3f313adfdd47c962bbaebd6aa13b46439eb742622c29ca067db0ec1853064c3cbbffe0a215a19fce47d49703ed58ebbd89721172d256d1cf30188106fb2f863186511401fad54d087aa2fb3d1b85768db386bd7102e8060ac157bac011acdcdae2799b9aee1467c3424013455bd028fcaacdc3c77d28ea199967d617ea7d0d0815f3cc407934a76d1293dccba210d1709a13e5dd67c9ba47cd113f5bdd740358eff13164159fd09bc2f7ec6cfa64d9df7e2e2f88706b0ff3a92ccf6f078456cfe0bdd89292cfe2680badc1eac9f7d36efe8eb6912c7b164508d13e6c0911c15f73c233cbe4fc70ff2ade1e1be4bbb738e0939159e2078a9438f05b756a003371f4861481c38f1cdd2d7b06deb62869e9fe79a8abaa920646fa2e8fa28f0d80c136376c7b56046bae4c05c0cdf64efb8c47bbfc5a1a4c0b045061ef0d71618e0d206a1d7f245fd5c03191b152673ba8dff8e1b8de7c50234a93cba91e3888adb228cc02beded4b1c0946797d3ef02dec2edb6ad0ac21f89f4be364c317da7c22440e9f358d512203f4b7ab20388af68b8915d0152db2c8a0687bfaea870f7529bb92a22b35bd79bc6d490591406346ecd78342ee3563c4883a8251679691c2d4e963397e24653520795511b018915374c954bddb940a9d7a16d1c8bd798fc7dbfb0599a7074e13f87e14efa8d511bb2579ec029b1bda18fe971b30fbe19e986ff2686a69bf3f1bb929de93ae70345ebca998b11e0a2b41890cba628d8f6e7c4e94790735e5299b4ff07cd3080f7d53c9cbe1911d2cd5925b3213e033c272506a87886cf761a283a779564d3241e3c28f632e166b5d756e1786ce077614c4444e3f2aed5decb3613b925ea3e558c21d4faf8ba54edd0f3a5d4>',
    '<b 0xc10000000114367096bb0fb3f58f3a3fb8aaacd61d63a1c8a40e14f7374b8a62dccba6431716c3abf6f5afbcfb39bd008000047c32e268567c652e6f4db58bff759bc8c5aaca183b87cb4d22938fe7d8dca22a679a79e4d9ee62e4bbb3a380dd78d4e8e48f26b38a1d42d76b371a5a9a0444827a69d1ab5872a85749f65a4104e931740b4dc1e2dd77733fc7fac4f93011cd622f2bb47e85f71992e2d585f8dc765a7a12ddeb879746a267393ad023d267c4bd79f258703e27345155268bd3cc0506ebd72e2e3c6b5b0f005299cd94b67ddabe30389c4f9b5c2d512dcc298c14f14e9b7f931e1dc397926c31fbb7cebfc668349c218672501031ecce151d4cb03c4c660b6c6fe7754e75446cd7de09a8c81030c5f6fb377203f551864f3d83e27de7b86499736cbbb549b2f37f436db1cae0a4ea39930f0534aacdd1e3534bc87877e2afabe959ced261f228d6362e6fd277c88c312d966c8b9f67e4a92e757773db0b0862fb8108d1d8fa262a40a1b4171961f0704c8ba314da2482ac8ed9bd28d4b50f7432d89fd800c25a50c5e2f5c0710544fef5273401116aa0572366d8e49ad758fcb29e6a92912e644dbe227c247cb3417eabfab2db16796b2fba420de3b1dc94e8361f1f324a331ddaf1e626553138860757fd0bf687566108b77b70fb9f8f8962eca599c4a70ed373666961a8cb506b96756d9e28b94122b20f16b54f118c0e603ce0b831efea614ad836df6cf9affbdd09596412547496967da758cec9080295d853b0861670b71d9abde0d562b1a6de82782a5b0c14d297f27283a895abc889a5f6703f0e6eb95f67b2da45f150d0d8ab805612d570c2d5cb6997ac3a7756226c2f5c8982ffbd480c5004b0660a3c9468945efde90864019a2b519458724b55d766e16b0da25c0557c01f3c11ddeb024b62e303640e17fdd57dedb3aeb4a2c1b7c93059f9c1d7118d77caac1cd0f6556e46cbc991c1bb16970273dea833d01e5090d061a0c6d25af2415cd2878af97f6d0e7f1f936247b394ecb9bd484da6be936dee9b0b92dc90101a1b4295e97a9772f2263eb09431995aa173df4ca2abd687d87706f0f93eaa5e13cbe3b574fa3cfe94502ace25265778da6960d561381769c24e0cbd7aac73c16f95ae74ff7ec38124f7c722b9cb151d4b6841343f29be8f35145e1b27021056820fed77003df8554b4155716c8cf6049ef5e318481460a8ce3be7c7bfac695255be84dc491c19e9dedc449dd3471728cd2a3ee51324ccb3eef121e3e08f8e18f0006ea8957371d9f2f739f0b89e4db11e5c6430ada61572e589519fbad4498b460ce6e4407fc2d8f2dd4293a50a0cb8fcaaf35cd9a8cc097e3603fbfa08d9036f52b3e7fcce11b83ad28a4ac12dba0395a0cc871cefd1a2856fffb3f28d82ce35cf80579974778bab13d9b3578d8c75a2d196087a2cd439aff2bb33f2db24ac175fff4ed91d36a4cdbfaf3f83074f03894ea40f17034629890da3efdbb41141b38368ab532209b69f057ddc559c19bc8ae62bf3fd564c9a35d9a83d14a95834a92bae6d9a29ae5e8ece07910d16433e4c6230c9bd7d68b47de0de9843988af6dc88b5301820443bd4d0537778bf6b4c1dd067fcf14b81015f2a67c7f2a28f9cb7e0684d3cb4b1c24d9b343122a086611b489532f1c3a26779da1706c6759d96d8ab>',
)
# __I1_POOL_END__

# __LIB_BEGIN__
# __LIB_END__
