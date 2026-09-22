# -*- coding: utf-8 -*-
"""Генерация WARP-конфига на ПК: код плагина + urllib вместо java.net.

Запуск:  python tools/generate_conf_pc.py [выход.conf]
"""
import json
import pathlib
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import _stubs  # noqa: E402

OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "_personal" / "generated-warp.conf"


def pc_warp_api(method, path, body=None, token=None):
    """Тот же API, что _warp_api в плагине, но через urllib (для ПК)."""
    req = urllib.request.Request(
        "https://api.cloudflareclient.com/v0i1909051800/" + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "okhttp/3.12.1",
            **({"Authorization": "Bearer " + token} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            code, text = resp.getcode(), resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        code, text = err.code, err.read().decode("utf-8", "replace")
    if code >= 400:
        try:
            message = json.loads(text).get("message") if text else None
        except Exception:
            message = None
        raise RuntimeError("Cloudflare API %s: HTTP %s %s" % (path, code, message or ""))
    return json.loads(text) if text else {}


def main():
    ns = _stubs.exec_plugin(REPO / "dist" / "amnezia_awg_byTime.plugin")
    ns["_warp_api"] = pc_warp_api  # транспорт на urllib

    print("[1/3] X25519-ключи и регистрация в Cloudflare…")
    conf_text = ns["generate_warp_config_text"]()

    cfg = ns["parse_conf_text"](conf_text)
    print("[2/3] Конфиг собран:")
    print("      endpoint:", cfg["endpoint"])
    print("      адрес:", ", ".join(cfg["address"]))
    print("      peer:", cfg["publicKey"][:20] + "…")
    print("      AWG-параметров:", len(cfg["awg"]), "| I1:", len(cfg["awg"].get("i1", "")), "симв.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(conf_text, encoding="utf-8", newline="\n")
    print("[3/3] Сохранено:", OUT)

    # Копия в JSON-формате движка — можно вставить в плагин через буфер обмена
    json_out = OUT.with_suffix(".engine.json")
    json_out.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    print("      JSON для движка:", json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
