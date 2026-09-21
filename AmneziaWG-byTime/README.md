# AmneziaWG byTime

**AmneziaWG-туннель внутри exteraGram — без системного VPN, без root.**

Плагин встраивает собственный движок AmneziaWG прямо в мессенджер: трафик
Telegram идёт через обфусцированный туннель к вашему серверу, а система про
VPN даже не знает.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Android%2010%2B%20arm64-green)
![Engine](https://img.shields.io/badge/engine-amneziawg--go%20%2B%20gVisor-orange)

**Автор:** Time · **Версия:** 1.1.0

---

## Возможности

- 📄 **Свои конфиги** — импорт `.conf` (AmneziaWG/WireGuard) прямо в настройках;
  конфиг запоминается и используется при каждом старте.
- ✅ **Проверка перед подключением** — плагин реально прогоняет трафик через
  туннель и только потом говорит «готово».
- ♻️ **Личные сборки** — при сборке можно вшить свой конфиг (`build.py --conf`),
  тогда плагин работает «из коробки» с вашим сервером.
- 🔒 **Без разрешений** — не использует `VpnService`, не требует root.
- 🧠 **Тёплый туннель** — не переподключается при каждом сворачивании приложения.

## Как это устроено

```
Telegram (MTProto, медиа)
      │  TCP → SOCKS5 127.0.0.1:10809
      ▼
┌──────────── libawgcore.so (Go) ────────────┐
│  SOCKS5-сервер                             │
│      ▼                                     │
│  gVisor netstack — TCP/IP в userspace      │
│      ▼                                     │
│  AmneziaWG (amneziawg-go): ChaCha20 +      │
│  обфускация Jc/Jmin/Jmax, S1-S4, H1-H4,    │
│  I1-I5                                     │
└──────────────┬─────────────────────────────┘
               │ UDP (обычный сокет процесса)
               ▼
        AmneziaWG-сервер
```

Ключевые решения:

- **Нет `VpnService` и нет TUN** — сетевой стек живёт в userspace (gVisor),
  поэтому не нужны системные разрешения и нет конфликтов с другими VPN.
- **Свой движок** — Go-библиотека (`-buildmode=c-shared`), три C-функции:
  `awgStart/awgStop/awgStatus`. Загружается через `ctypes` из приватного
  каталога приложения.
- **Интеграция через штатный механизм Telegram** — `SharedConfig.addProxy()` +
  `ConnectionsManager.setProxySettings()`.

Подробности: [docs/DESCRIPTION_FULL.md](docs/DESCRIPTION_FULL.md) ·
технический разбор: [docs/HABR_ARTICLE.md](docs/HABR_ARTICLE.md)

## Установка

1. Скачайте `amnezia_awg_byTime.plugin` из раздела **Releases** (или соберите
   сами, см. ниже).
2. exteraGram → **Настройки → Плагины → «+»** → выберите файл.
3. Плагин попросит импортировать `.conf` — положите файл конфига в память
   телефона и следуйте подсказке в настройках плагина.
4. Готово: после успешной проверки туннеля появится уведомление
   «Amnezia byTime: работает ваш конфиг».

## Свой сервер

Плагин поставляется **без встроенного сервера** — подключается ваш:

1. Положите `.conf` в память телефона (например `/sdcard/Download/myvpn.conf`).
2. Настройки плагина → **«Путь к .conf файлу»** → **«Импортировать и подключиться»**.

Поддерживаются ключи `wg-quick`: `PrivateKey`, `Address`, `DNS`, `MTU`,
`Jc`, `Jmin`, `Jmax`, `S1`–`S4`, `H1`–`H4`, `I1`–`I5`,
`PublicKey`, `AllowedIPs`, `Endpoint`, `PersistentKeepalive`.

Пример: [configs/default-warp.conf.example](configs/default-warp.conf.example).

## Сборка из исходников

Нужно: Go 1.25+, Python 3.10+, Android NDK (для пересборки движка).

```bash
# 1. Движок (если не используете prebuilt):
cd engine
./build.sh          # Linux/macOS: GOOS=android GOARCH=arm64 -buildmode=c-shared
# или на Windows:   powershell -File engine\build.ps1
#                    (нужен clang из Android NDK в PATH)

# 2. Публичная сборка плагина (без встроенного сервера):
cd ../plugin
python build.py     # -> dist/amnezia_awg_byTime.plugin

#    ...или ЛИЧНАЯ сборка со вшитым вашим конфигом (НЕ публикуйте её):
python build.py --conf путь/к/myvpn.conf --out dist/my_personal.plugin
```

## Структура проекта

```
AmneziaWG-byTime/
├── plugin/
│   ├── plugin_code.py      # исходник плагина (Python, exteraGram SDK)
│   └── build.py            # сборщик .plugin (base64-вшивание движка/конфига)
├── engine/
│   ├── main.go             # движок: AmneziaWG + gVisor netstack + SOCKS5
│   ├── go.mod / go.sum
│   ├── build.sh / build.ps1
│   └── prebuilt/           # готовые бинарники (android/arm64 + windows для тестов)
├── configs/
│   └── default-warp.conf.example   # пример .conf (ключ-заглушка)
├── tests/
│   ├── test_e2e.py         # живой тест туннеля (реальный handshake + HTTP)
│   ├── test_plugin_logic.py
│   └── _stubs.py           # заглушки exteraGram SDK для тестов на ПК
├── docs/                   # описание + техническая статья
├── LICENSE                 # MIT
└── README.md
```

## Тесты

Тесты запускаются на ПК; для живого теста туннеля нужен ваш `.conf`
(переменная окружения `AWG_TEST_CONF`):

```bash
cd tests
python test_plugin_logic.py   # парсер .conf + логика плагина
set AWG_TEST_CONF=C:\path\to\myvpn.conf
python test_e2e.py            # handshake с сервером + HTTP 200 через туннель
```

## Ограничения

- Только **arm64** (64-битный Android 10+).
- **Звонки идут напрямую** — UDP не туннелируется через SOCKS5.
- Движок использует ~30–60 МБ ОЗУ внутри процесса Telegram.

## Лицензия

MIT — см. [LICENSE](LICENSE). Использует: [amneziawg-go](https://github.com/amnezia-vpn/amneziawg-go) (MIT),
[gVisor netstack](https://github.com/google/gvisor) (Apache-2.0),
[go-socks5](https://github.com/things-go/go-socks5) (MIT).

