# -*- coding: utf-8 -*-
"""E2E-тест движка на ПК: рукопожатие AmneziaWG + SOCKS5 + HTTP через туннель.

Требуется:
  * engine/prebuilt/windows-amd64/awgcore_test.dll  (сборка: engine/build.ps1 -Windows)
  * реальный .conf: переменная окружения AWG_TEST_CONF или configs/default-warp.conf
    (в публичном репозитории его нет — тест корректно SKIP)

Запуск:
    python tests/test_e2e.py
"""
import ctypes
import json
import os
import pathlib
import socket
import struct
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import _stubs  # noqa: E402

DLL = REPO / "engine" / "prebuilt" / "windows-amd64" / "awgcore_test.dll"
PORT = 10809


def find_conf():
    env = os.environ.get("AWG_TEST_CONF")
    if env and pathlib.Path(env).exists():
        return pathlib.Path(env)
    private = REPO / "configs" / "default-warp.conf"
    if private.exists():
        return private
    return None


def skip(message):
    print("SKIP:", message)
    sys.exit(0)


if not DLL.exists():
    skip("нет " + str(DLL) + " — соберите: pwsh engine/build.ps1 -Windows")

conf_path = find_conf()
if conf_path is None:
    skip("нет реального .conf — задайте переменную окружения AWG_TEST_CONF")

namespace = _stubs.exec_plugin(REPO / "plugin" / "plugin_code.py")
cfg = namespace["parse_conf_text"](conf_path.read_text(encoding="utf-8"))

if str(cfg.get("privateKey", "")).startswith("<"):
    skip("в " + conf_path.name + " ключ-заглушка — вставьте свой PrivateKey")

lib = ctypes.CDLL(str(DLL))
lib.awgStart.argtypes = [ctypes.c_char_p]
lib.awgStart.restype = ctypes.c_int
lib.awgStop.argtypes = []
lib.awgStop.restype = ctypes.c_int
lib.awgStatus.restype = ctypes.c_int

print("config:", conf_path.name, "| endpoint:", cfg["endpoint"])
print("starting engine…")
if lib.awgStart(json.dumps(cfg).encode()) != 0:
    print("E2E RESULT: FAIL (awgStart)")
    sys.exit(1)


def port_open():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=1.5).close()
        return True
    except OSError:
        return False


for _ in range(20):
    if port_open():
        break
    time.sleep(0.5)
print("socks port open:", port_open(), "| status:", lib.awgStatus())


def socks_connect(host, port):
    sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    sock.sendall(b"\x05\x01\x00")
    assert sock.recv(2) == b"\x05\x00"
    raw = host.encode()
    sock.sendall(b"\x05\x01\x00\x03" + bytes([len(raw)]) + raw + struct.pack(">H", port))
    reply = sock.recv(4)
    assert reply[1] == 0, "connect reply code=%s" % reply[1]
    if reply[3] == 1:
        sock.recv(4 + 2)
    elif reply[3] == 3:
        length = sock.recv(1)
        if length:
            sock.recv(length[0] + 2)
    elif reply[3] == 4:
        sock.recv(16 + 2)
    return sock


print("GET example.com через туннель…")
s = socks_connect("example.com", 80)
s.sendall(b"GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n")
data = b""
deadline = time.time() + 15
while len(data) < 4000 and time.time() < deadline:
    chunk = s.recv(4096)
    if not chunk:
        break
    data += chunk
s.close()
head = data.split(b"\r\n", 1)[0] if data else b"(no data)"
print("получено", len(data), "байт:", head.decode(errors="replace"))

lib.awgStop()
ok = data.startswith(b"HTTP/")
print("E2E RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
