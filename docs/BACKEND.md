# ERRNO: бекенд

База `http://127.0.0.1:8000`. Помилка завжди `{"detail": "..."}`: 401, 403, 404, 409, 413, 422, 429.

Час показів — секунди. Якщо в тілі `time_scale > 1`, `ts_device` і є симульований годинник. Інакше живі пакети отримують медіанну поправку з останніх 20 приходів. Дії людей без пакета йдуть за стіною годинника, а годинник корабля — це `max(час пакетів, стіна)`, доки тест його не зафіксує.

## Облікові записи

Порожня база створює три акаунти. Demo-паролі беруться з `SEED_PASSWORD_DOCTOR`, `SEED_PASSWORD_OFFICER`, `SEED_PASSWORD_ASTRONAUT`: `doctor/doctor`, `officer/officer`, `astronaut/astronaut`.

| Логін | Роль | Прив'язка |
|---|---|---|
| `doctor` | `chief` | усі клінічні групи, акаунти, межі |
| `officer` | `officer` | звичайний космонавт `A2` (не медперсонал); свої дані як у astronaut; чужі числа лише в break-glass при статусі 2 |
| `astronaut` | `astronaut` | `A1` |

`POST /auth/login`, `GET /auth/me`. Пристрій: `X-Device-Token`, не акаунт людини.

## Видимість

Космонавт бачить свої групи: активність, сон, пульс і тиск, дихання, температуру, психологічний стан, імунітет. Лікар бачить їх і ще самопочуття, аналізи (включно з кальцієм), психічні тести, глюкозу в мг/дл, ICP, ЕЕГ (індекс втоми і альфа/тета/бета), лактат, кортизол, CO2, дозу. Альфа, тета і бета не входять у суму штрафу.

Офіцер на вкладці «Я» бачить ті самі групи, що космонавт. Запит чужих чисел без активного break-glass дає 403. Кожен такий перегляд пише `breakglass_access_log` і `audit_log`.

Приховане поле відсутнє в JSON. Сховати його стилем не можна, бо сервер його не віддає.

Лікар на всіх своїх ендпоінтах бачить дані з `ts <= sim_now - SIGNAL_DELAY_SEC`. `SIGNAL_DELAY_SEC=0` вимикає затримку. Конверт пакета (`in_transit`, `eta_sec`) видно одразу, вміст — після `visible_at`.

## Штраф і статус

`GET /penalties?astronaut_id=` — розклад `{metric, value, baseline, deviation, penalty, one_sided, suppressed_by_fusion, stale}` і індекс `max(0, 100-S)`.

`GET /status`, `GET /status/history`, `GET /hud`.

Статуси: `0 NO_DOCTOR_NEEDED`, `1 ALLOW_FINISH_MISSION`, `2 CALL_DOCTOR_NOW`. Текст статусу 2: «КРИТИЧНИЙ СТАН! Негайно припини роботу та очікуй допомоги екіпажу».

`GET /crew/readiness` — офіцер, без чисел: `green`, `yellow`, `red-breakglass`.

`GET /sensors/board?astronaut_id=` — панель датчиків екіпажу (astronaut / officer): live/stale/offline, останнє значення.
`POST /sensors/pulse` — згенерувати покази з панелі (`source=panel`, режими `rest|exercise|eva`). Офіцер для чужого id лише під break-glass.

`GET /emergency/{astronaut_id}` — офіцер і лише під час break-glass.

`GET /incidents`, `POST /incidents/{id}/steps`, `POST /incidents/{id}/close`.

`GET /earth/packets`, `GET /earth/packets/{id}`, `GET /earth/warning-log` — лікар.
`GET /earth/actions` — повідомлення зв'язку: лікар бачить `direction=down` (від офіцера), офіцер — `up` (від лікаря).

`GET /config/public` — без секретів: назва місії, затримка, підпис про симуляцію.

`WS /live?token=` — події `reading`, `alert`, `status`, `breakglass`, `earth_packet`. Без токена сокет закривається з `4401`. Подія чужої ролі не надсилається.

## Що лишилось як було

`GET /astronauts`, `/metrics`, `/readings`, `/range-alerts`, `/limits`, `/alerts`, `/changes`, `/accounts`, `/audit`, `/audit/verify`, `POST /audit/tamper` лише при `DEMO_MODE`, `/forms/*`, `/readings/manual`, `PUT /limits`, `PUT /readings/{id}`, `/ingest`, `/ingest/ws`, `/health`.

`PUT /limits` застосовується одразу. Це свідоме спрощення: затримка діє на телеметрію і на `POST /actions`, не на межі.

`POST /actions` приймає офіцера (вниз, на Землю) і лікаря (вгору, на борт). Рядок у `actions` з'являється в `arrives_at = sim_now + SIGNAL_DELAY_SEC`.

## Ingest

Тіло до 256 КБ і 500 показів, не частіше 20 запитів на секунду з одного `device_id`. Повтор `(device_id, seq)` дає `duplicate: true`. Дірка в `seq` додається до `lost_packets`.

```json
{
  "device_id": "sim-gw-1",
  "astronaut_id": "A1",
  "seq": 1,
  "buffered": false,
  "time_scale": 60,
  "activity_mode": "rest",
  "ts_device": 1700000000,
  "readings": [{"sensor_id": "hr", "value": 72, "unit": "bpm", "quality": 1}]
}
```

`activity_mode`: `rest`, `exercise`, `eva`. Інше значення — 422. Під час `exercise` штраф HR, RR і LAC дорівнює нулю. `eva` зберігається, але штраф не гасить.

`quality <= 0.2` або значення поза правдоподібним діапазоном не входять у штраф. Якщо так триває щонайменше 30 с, пишеться тривога `equipment`. Вона не піднімає медичний статус.

Глюкоза зберігається в мг/дл. Старі межі 3.9–6.0 ммоль/л один раз помножені на 18: 70.2 і 108. Повторного перерахунку під час запиту немає.

## Журнал

`changes` — правки лікаря. `audit_log` — підписаний ланцюжок Ed25519. Туди ж потрапляє зміна статусу і відкриття break-glass.

`GET /audit/verify` → `{"ok": true, "broken_at": null, "total": N}`.
