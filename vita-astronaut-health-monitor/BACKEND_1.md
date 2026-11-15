# ERRNO: бекенд

База `http://127.0.0.1:8000`. Префікса `/api` немає. Жива схема: `/docs` і `/redoc`.

Час у записах — секунди Unix. Симулятор може йти швидше (`TIME_SCALE`). Час пристрою лишається звичайним epoch після поправки зсуву.

Помилка завжди `{"detail": "..."}`.

| Код | Коли |
|---|---|
| `401` | немає або недійсний токен людини чи пристрою |
| `403` | роль не має права на цю дію або цю групу |
| `404` | немає космонавта, запису або сценарію |
| `409` | логін уже зайнятий |
| `413` | тіло більше 256 КБ або більше 500 показів |
| `422` | бите тіло |
| `429` | пристрій шле частіше ніж 20 запитів на секунду |

## Хто є хто

На старті, якщо таблиця `users` порожня, створюються три акаунти. Пароль збігається з логіном. Це паролі прототипу, їх треба змінити.

| Логін | Пароль | Роль | Що може |
|---|---|---|---|
| `doctor` | `doctor` | `chief` | бачить і змінює клінічні дані, ставить межі, створює акаунти |
| `officer` | `officer` | `officer` | тільки читає, і тільки поки значення поза межами |
| `astronaut` | `astronaut` | `astronaut` | бачить і надсилає свої групи. Прив'язаний до `A1` |

Людей може бути більше. Нового лікаря, офіцера або космонавта створює тільки головний лікар (`chief`). Звичайний лікар (`doctor`) дані бачить і змінює, але акаунти не створює.

Космонавт бачить тільки свій `astronaut_id`. Типовий екіпаж у `config/crew.yaml` — одна людина: `A1` Олена Кравець. Новий космонавт отримує наступний вільний id (`A2`, `A3`, …), якщо його не передали в запиті.

Запит людини: заголовок `Authorization: Bearer <token>`.

Запит пристрою: заголовок `X-Device-Token`. Це окремий вхід, не акаунт людини.

## Що видно кожній ролі

Космонавт бачить свої групи і може надіслати сон і психологічний стан. Офіцер бачить ті самі групи, але лише записи, де значення нижче `min` або вище `max`. Лікар і головний лікар бачать усі групи нижче і можуть їх змінювати.

| Група | Поля | Космонавт | Лікар |
|---|---|---|---|
| Активність | `activity` | так | так |
| Режим і якість сну | `sleep_hours`, `sleep_quality` | так | так |
| Тиск, пульс, кисень | `hr`, `bp_sys`, `bp_dia`, `spo2` | так | так |
| Дихання | `resp` | так | так |
| Температура тіла | `temp` | так | так |
| Психологічний стан | `psych_score` | так | так |
| Імунітет | `wbc`, `hematocrit` | так | так |
| Загальне самопочуття | `wellbeing` | | так |
| Аналізи крові і сечі | `na`, `k`, `creatinine` | | так |
| Психічний стан | `pvt_rt_median`, `pvt_lapses`, `vision_score` | | так |
| Рівень цукру в крові | `glucose` | | так |
| Внутрішньочерепний тиск | `icp` | | так |
| ЕКГ мозку | `eeg_alpha`, `eeg_theta`, `eeg_beta` | | так |
| Підшкірні хімічні датчики | `lactate`, `cortisol` | | так |

`hrv_rmssd`, `bp_subq`, `radiation_dose_rate` і `radiation_career` симулятор пише в базу, але в ці групи вони не входять. Через акаунт їх не видно.

У кожній відповіді з числом є `alert: true`, якщо значення поза межами цього космонавта. Межі ставить лікар. Поки точні числа не задані, стоять робочі з таблиці нижче. Для `eeg_*` і `cortisol` робочих меж немає: алерт з'явиться після `PUT /limits`.

| Поле | min | max | Поле | min | max |
|---|---|---|---|---|---|
| `activity` | 50 | 800 | `wellbeing` | 6 | 10 |
| `sleep_hours` | 7 | 9 | `na` | 135 | 145 |
| `sleep_quality` | 6 | 10 | `k` | 3.5 | 5.1 |
| `hr` | 50 | 100 | `creatinine` | 50 | 110 |
| `bp_sys` | 90 | 120 | `pvt_rt_median` | 180 | 300 |
| `bp_dia` | 60 | 80 | `pvt_lapses` | 0 | 2 |
| `spo2` | 95 | 100 | `vision_score` | 70 | 100 |
| `resp` | 12 | 20 | `glucose` | 3.9 | 6.0 |
| `temp` | 36.1 | 37.2 | `icp` | 5 | 15 |
| `psych_score` | 60 | 100 | `lactate` | 0.5 | 2.2 |
| `wbc` | 4 | 10 | `hematocrit` | 36 | 48 |

Це окремо від клінічної оцінки за z-score. Оцінка лишається для лікаря в `GET /status` і `GET /alerts`. Космонавт і офіцер у статусі отримують `score: null` і порожні `systems`, щоб приховані метрики не просвічували.

## Вхід

`POST /auth/login`

```json
{"login": "astronaut", "password": "astronaut"}
```

```json
{"token": "…", "role": "astronaut", "name": "Олена Кравець", "astronaut_id": "A1"}
```

`GET /auth/me` з Bearer повертає `login`, `role`, `name`, `astronaut_id`.

```bash
TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/auth/login \
  -H 'content-type: application/json' \
  -d '{"login":"doctor","password":"doctor"}' | python -c 'import json,sys; print(json.load(sys.stdin)["token"])')
```

Далі в прикладах `$TOKEN` — цей токен.

## Отримати дані

`GET /astronauts`

Космонавт отримує лише себе. Лікар і офіцер — увесь список.

`GET /metrics`

Каталог доступних груп і останнє значення по кожному космонавту, якого роль має право бачити.

```json
[{
  "id": "hr",
  "name_uk": "Пульс",
  "group": "Тиск, пульс, кисень",
  "unit": "bpm",
  "source": "sim",
  "latest": [{"astronaut_id": "A1", "value": 72.1, "ts": 1731580000.1, "alert": false}]
}]
```

У офіцера метрика зникає зі списку, якщо зараз ні в кого немає виходу за межі.

`GET /readings?astronaut_id=A1&sensor_id=hr`

`astronaut_id` обов'язковий. `sensor_id`, `from`, `to` — секунди. `resolution=raw` (типово) або `1m`. Без вікна береться остання година.

`raw`: `id, ts, astronaut_id, sensor_id, value, unit, quality, source, device_id, alert`.

`1m`: `ts, astronaut_id, sensor_id, value` (середнє), `min`, `max`, `n, alert`. Для офіцера хвилина потрапляє у відповідь, якщо середнє поза межами.

Чужа група дає `403`. Чужий космонавт для акаунта космонавта теж `403`.

```bash
curl -sS "http://127.0.0.1:8000/readings?astronaut_id=A1&sensor_id=hr" \
  -H "Authorization: Bearer $TOKEN"
```

`GET /range-alerts?astronaut_id=A1`

Останнє значення кожної метрики, яке зараз поза `min`/`max`. Це список для прапорця на фронтенді. Офіцер бачить тут лише групи космонавта.

```json
[{"id": 18, "ts": 1731580000.2, "astronaut_id": "A1", "sensor_id": "hr", "value": 160, "unit": "bpm", "min": 50, "max": 100, "alert": true}]
```

`GET /limits?astronaut_id=A1`

Межі, які роль має право бачити. Космонавт бачить свої.

`GET /status?astronaut_id=A1`

Без id лікар і офіцер отримують список. Космонавт завжди отримує лише себе.

```json
{
  "astronaut_id": "A1",
  "score": 96.2,
  "level": "Normal",
  "help_needed": false,
  "systems": {"cardio": 98.0},
  "alerts": []
}
```

У космонавта і офіцера `score` дорівнює `null`, `systems` порожній.

`GET /alerts?astronaut_id=A1&active=true`

Клінічні тривоги z-score: `watch` і `act`. `active` типово `true`. Поля: `id, ts, astronaut_id, sensor_id, category, level, message, explanation, acknowledged`. Офіцер не бачить `HELP_NEEDED` і тривоги з груп лікаря.

`WS /live?token=<token>&astronaut_id=A1`

Той самий токен, що після логіна, у query. Події `reading`, `alert`, `status`. Показ однієї метрики не частіше ніж раз на секунду. Подія чужої групи не надсилається. Без токена сокет закривається з кодом `4401`.

## Надіслати дані

Анкети йдуть у ту саму чергу, що й датчики. `source=form`. Відповідь `{"accepted": N}`. Офіцер отримує `403`. Космонавт може писати тільки у свої групи і тільки собі: сон і психологічний стан. Самопочуття, PVT і зір приймає лікар.

`POST /forms/sleep`

```json
{"astronaut_id": "A1", "hours": 7.5, "quality": 8}
```

Пише `sleep_hours` і `sleep_quality`.

`POST /forms/psych`

```json
{"astronaut_id": "A1", "answers": [3, 4, 2, 3]}
```

Відповіді 0..4. `psych_score = 100 * середнє / 4`.

`POST /forms/wellbeing` — лікар

```json
{"astronaut_id": "A1", "score": 7, "comfort": 6}
```

Оцінюється `score`. `comfort` приймається і не зберігається.

`POST /forms/pvt` — лікар

```json
{"astronaut_id": "A1", "times": [240, 260, 510, 230]}
```

`pvt_rt_median` — медіана, мс. `pvt_lapses` — скільки реакцій довші за 500 мс.

`POST /forms/vision` — лікар

```json
{"astronaut_id": "A1", "score": 90}
```

`POST /readings/manual` — лікар

Будь-який id з груп лікаря. Невідомий id — `400`. Неможливе значення пишеться з `quality=0` і не йде в оцінку.

```json
{"astronaut_id": "A1", "sensor_id": "wbc", "value": 6.5, "unit": "10^9/L"}
```

```bash
curl -sS -X POST http://127.0.0.1:8000/readings/manual \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"astronaut_id":"A1","sensor_id":"glucose","value":5.1,"unit":"mmol/L"}'
```

Запис з'являється в `GET /readings` після злиття черги (типово раз на секунду).

## Змінити межі і значення

Це може лікар і головний лікар. Кожна зміна пишеться в журнал: хто, роль, коли, космонавт, поле, старе і нове.

`PUT /limits`

```json
{"astronaut_id": "A1", "sensor_id": "hr", "min": 45, "max": 110}
```

`min` має бути меншим за `max`. Межа діє одразу: наступний `GET /readings` і `GET /range-alerts` вже дивляться на неї.

`PUT /readings/{id}`

```json
{"value": 6.8}
```

Міняє збережене число. `id` є в `raw` відповіді `GET /readings`.

`GET /changes?astronaut_id=A1`

Останні 200 рядків. Бачить тільки лікар.

```json
[{
  "ts": 1731580100.0,
  "actor_login": "doctor",
  "role": "chief",
  "astronaut_id": "A1",
  "sensor_id": "hr",
  "field": "max",
  "old_value": 100,
  "new_value": 110
}]
```

`field` буває `min`, `max` або `value`.

`POST /alerts/{id}/ack` і `POST /actions` теж тільки лікар.

```json
{"astronaut_id": "A1", "alert_id": 3, "action": "rest 10 min, hydrate, re-check"}
```

Підтвердження тривоги: `{"ok": true}`. Дія: `{"id": 1}`.

## Облікові записи

`GET /accounts` і `POST /accounts` — тільки головний лікар.

```json
{"login": "astro2", "password": "secret", "role": "astronaut", "name": "Другий"}
```

`role`: `chief`, `doctor`, `officer`, `astronaut`. Для космонавта можна передати `astronaut_id`. Якщо не передати, візьметься перший вільний `A<n>`. Новому космонавту одразу копіюються робочі межі. Симулятор для нього сам не стартує: дані приходять анкетою, ручним записом або пристроєм.

```bash
curl -sS -X POST http://127.0.0.1:8000/accounts \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"login":"lab","password":"secret","role":"doctor","name":"Лікар зміни"}'
```

## Датчик

`POST /ingest` і `WS /ingest/ws` не ходять через акаунт людини. Токен пристрою — `X-Device-Token`, у сокета ще й `?token=`. `DEV_NO_AUTH=true` пропускає перевірку і пише попередження в лог.

Тіло — один показ, список або конверт. Не більше 500 показів і 256 КБ.

```json
{
  "device_id": "gw-1",
  "astronaut_id": "A1",
  "seq": 42,
  "buffered": false,
  "ts_device": 1731580000.12,
  "readings": [
    {"sensor_id": "hr", "value": 72, "unit": "bpm", "quality": 1.0, "ts_device": 1731580000.1}
  ]
}
```

```json
{"accepted": 1, "dropped": 0, "duplicate": false}
```

1. Токен звіряється з `DEVICE_TOKENS` для `device_id`.
2. Повтор `(device_id, seq)` дає `duplicate: true`. Дірка в `seq` додається до `lost_packets`.
3. Зсув годинника — медіана останніх 20 живих пакетів: `offset = arrival - ts_device`. Пакет `buffered: true` бере цей зсув, а не час приходу.
4. Значення поза правдоподібним діапазоном пишеться з `quality=0`. Невідомий `sensor_id` відкидається.
5. `quality <= 0.2` означає немає контакту. Замість цього не пиши нуль.
6. Запит кладе рядки в чергу. У SQLite їх зливає окрема задача, раз на секунду або кожні 200 рядків.

Правдоподібні межі: пульс 20–250, HRV 1–300, SpO2 50–100, дихання 4–60, температура 30–43, систола 60–250, діастола 30–150, глюкоза 1–30, лейкоцити 0.5–50, активність 0–20000.

```bash
curl -sS -X POST http://127.0.0.1:8000/ingest \
  -H 'content-type: application/json' -H 'X-Device-Token: secret' \
  -d '{"device_id":"gw-1","astronaut_id":"A1","seq":1,"readings":[{"sensor_id":"hr","value":72,"unit":"bpm"}]}'
```

## Оцінка і сценарії

Кожна метрика мовчить перші 120 зразків. Далі `act`, якщо значення поза `norm.watch` або `|z| >= 3.5`; `watch`, якщо поза `norm.ok` або `|z| >= 2`. Безперервна метрика чекає 5 зразків поспіль. `quality < 0.5` не вчиться. Якщо так триває ≥ 30 с, це тривога `equipment`, і вона не рахується як проблема здоров'я.

Оцінка системи: середнє `100 * (1 - min(|z|/4, 1))`. Загальна — середнє систем. `>= 75` Normal, `>= 50` Watch, інакше Act.

`help_needed` стає true, коли за 60 хв є щонайменше 3 тривоги `watch`/`act` з ≥ 2 метрик і розривом ≥ 5 хв. Прапор спадає через 30 хв без нових таких тривог.

`GET /sim/scenarios` і `POST /sim/scenario` без акаунта людини. Це перемикач симулятора.

```json
{"name": "solar_storm", "astronaut_id": "A1"}
```

`nominal` знімає сценарії. Решта складаються. `metric_id` потрібен лише `sensor_fault` (типово `hr`).

| Ім'я | Що робить |
|---|---|
| `nominal` | знімає активні |
| `solar_storm` | 20 хв: радіація ×10, пульс +15 з 6-ї хвилини, бета ЕЕГ з 12-ї. Далі сон −3 і самопочуття −2 |
| `infection` | 20 хв: температура +1.2 і SpO2 −2, пульс +20 і HRV −20 з 6-ї хвилини, дихання +5 з 12-ї, лейкоцити +4 |
| `sleep_loss` | 3 доби: сон близько 4 год, реакція до +80 мс, самопочуття −2, HRV −15 |
| `sensor_fault` | 2 хв обрана метрика повторює останнє значення з `quality=0.2` |
| `cardiac_stress` | 10 хв: пульс +45, систола +25, SpO2 −3 |

## Журнал підпису

Це не журнал правок лікаря. Правки лікаря — `GET /changes`. Тут ланцюжок `sha256(prev_hash + canonical_json({ts, kind, payload}))` і підпис Ed25519. Перший `prev_hash` — 64 нулі. Ключ `backend/device_key.pem`.

`GET /audit?limit=50` — `id, ts, kind, payload, prev_hash, hash, sig`.

`GET /audit/verify` — `{"ok": true, "broken_at": null, "total": 12}`.

`POST /audit/tamper` лише при `DEMO_MODE=true`. Міняє payload і не перераховує хеш. Далі `verify` дає `ok: false`.

Журнал показує, що рядок змінили після підпису. Він не доводить, що датчик з самого початку сказав правду.

## База

Драйвери, анкети і `/ingest` кладуть показ в одну чергу. Writer зливає її однією транзакцією. На з'єднанні: `journal_mode=WAL`, `synchronous=NORMAL`.

Таблиці: `readings`, `rollups_1m`, `baselines`, `alerts`, `status`, `actions`, `audit_log`, `devices`, `device_state`, `ingest_seen`, `users`, `sessions`, `limits`, `changes`.

Сирі рядки старші за 24 симульовані години стираються. Хвилинні зведення лишаються. Сирий ЕКГ не зберігається.

`GET /health` без токена: `{"status": "ok"}`.
