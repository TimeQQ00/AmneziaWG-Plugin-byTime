# -*- coding: utf-8 -*-
"""Сборка плагина AmneziaWG byTime.

Собирает единый .plugin файл из:
  * plugin/plugin_code.py      — Python-часть (метаданные, настройки, импорт);
  * configs/default*.conf      — стандартный сервер, парсится в JSON;
  * engine/prebuilt/libawgcore.so — движок, вшивается в base64.

Запуск (из любой папки):
    python plugin/build.py
Результат:
    dist/amnezia_awg_byTime.plugin
"""
import base64
import json
import pathlib
import py_compile
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

SRC = REPO / "plugin" / "plugin_code.py"
LIB = REPO / "engine" / "prebuilt" / "libawgcore.so"
CONF = REPO / "configs" / "default-warp.conf"
CONF_EXAMPLE = REPO / "configs" / "default-warp.conf.example"
OUT = REPO / "dist" / "amnezia_awg_byTime.plugin"

PLACEHOLDER = "__AWG_CONFIG_JSON__"


def section(text, name):
    m = re.search(r"^\[" + name + r"\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not m:
        raise SystemExit("нет секции [" + name + "] в конфиге")
    return m.group(1)


def get(text, key, body, default=""):
    m = re.search(r"^\s*" + key + r"\s*=\s*(.+?)\s*$", body, re.M)
    return m.group(1) if m else default


def parse_conf(path):
    text = path.read_text(encoding="utf-8")
    iface = section(text, "Interface")
    peer = section(text, "Peer")

    awg = {}
    for key in ("Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3",
                "H4", "I1", "I2", "I3", "I4", "I5"):
        value = get(text, key, iface)
        if value:
            awg[key.lower()] = value

    keepalive = get(text, "PersistentKeepalive", peer, "25")
    try:
        keepalive = int(str(keepalive).strip())
    except ValueError:
        keepalive = 25

    return {
        "privateKey": get(text, "PrivateKey", iface),
        "address": [a.strip().split("/")[0] for a in get(text, "Address", iface).split(",") if a.strip()],
        "dns": [a.strip().split("/")[0] for a in get(text, "DNS", iface, "1.1.1.1").split(",") if a.strip()],
        "mtu": int(get(text, "MTU", iface, "1280")),
        "publicKey": get(text, "PublicKey", peer),
        "endpoint": get(text, "Endpoint", peer).strip(),
        "keepalive": keepalive,
        "allowedIPs": [a.strip() for a in get(text, "AllowedIPs", peer, "0.0.0.0/0, ::/0").split(",") if a.strip()],
        "socksPort": 10809,
        "logLevel": 3,
        "awg": awg,
    }


def main():
    conf = CONF if CONF.exists() else CONF_EXAMPLE
    if not conf.exists():
        raise SystemExit("нет файла конфига: " + str(CONF))
    if conf is CONF_EXAMPLE:
        print("! configs/default-warp.conf не найден, беру пример "
              "(ключ-заглушка — туннель не подключится, пока не вставите свой)")

    cfg = parse_conf(conf)
    cfg_json = json.dumps(cfg, separators=(",", ":"))
    print("config:", conf.name,
          "| endpoint:", cfg["endpoint"],
          "| AWG-параметров:", len(cfg["awg"]),
          "| ключ:", "заглушка" if cfg["privateKey"].startswith("<") else "задан")

    if not LIB.exists():
        raise SystemExit("нет движка: " + str(LIB) +
                         "\nсоберите его: см. engine/build.ps1 (или build.sh)")

    code = SRC.read_text(encoding="utf-8")
    if PLACEHOLDER not in code:
        raise SystemExit("в plugin_code.py нет плейсхолдера " + PLACEHOLDER)
    code = code.replace(PLACEHOLDER, repr(cfg_json))

    raw = LIB.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    payload = "\n".join("# " + b64[i:i + 76] for i in range(0, len(b64), 76))

    begin, end = "# __LIB_BEGIN__", "# __LIB_END__"
    pre, rest = code.split(begin, 1)
    _, post = rest.split(end, 1)
    code = pre + begin + "\n" + payload + "\n" + end + post

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(code, encoding="utf-8", newline="\n")
    py_compile.compile(str(OUT), doraise=True)
    print("OK ->", OUT, "|", round(OUT.stat().st_size / 1e6, 1), "MB |",
          "движок", round(len(raw) / 1e6, 1), "MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
