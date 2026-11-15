# Як влаштований ERRNO

Браузер на `http://localhost:3000`. Бекенд на `http://127.0.0.1:8000`. Генератор — окремий процес: він шле `POST /ingest` і не імпортується бекендом.

```
генератор або пристрій
  → POST /ingest, X-Device-Token
  → FastAPI
  → черга → SQLite WAL
  → штраф і автомат статусу
браузер
  → Bearer
  → ті самі ендпоінти, вже відфільтровані за роллю і затримкою
```

## Дерево

```
NASA/
├── README.md
├── Makefile                  make demo / make test
├── .env.example
├── docker-compose.yml        необов'язковий запуск
├── docs/
│   ├── BACKEND.md
│   ├── STRUCTURE.md
│   └── SCENARIOS.md
├── generator/                CLI + окремий веб-UI (:8100), scenarios/, не імпортує backend
└── backend/
    ├── main.py
    ├── access.py             ролі і паролі з середовища
    ├── zones.py              лише підсвітка значення
    ├── earth_link.py         симульований годинник і черга дій
    ├── scoring/penalty.py
    ├── scoring/status_machine.py
    ├── scoring/clinical.py
    ├── config/               екіпаж, метрики, штраф, статус, затримка, CSV правил
    └── api/
```

Фронтенд: `vita-astronaut-health-monitor/frontend`. Токен у `sessionStorage` під ключем `errno:auth-token`.

## Хто куди потрапляє

| Логін | Роль | Куди | Що бачить |
|---|---|---|---|
| `astronaut` | космонавт `A1` Олена Кравець | `/`, `/training` | свої групи. Статус 0 без повідомлень. Статус 1 — картки HUD лише для штрафів. Статус 2 — червоний екран |
| `officer` | космонавт `A2` Тарас Бондар з правом вахти | `/captain`, `/training`, `/captain/incident/[id]` | свої дані як у astronaut. «Екіпаж» — лише готовність. Чужі числа лише в критиці (break-glass) |
| `doctor` | головний лікар (`chief`) | `/medic`, `/medic/crew`, `/medic/earth`, `/medic/audit` | телеметрія із затримкою. Пакет хірурга відкривається після `visible_at` |

Demo-паролі беруться з `.env` (`SEED_PASSWORD_*`): `doctor/doctor`, `officer/officer`, `astronaut/astronaut`.

## Сторінки

| Шлях | Хто |
|---|---|
| `/login` | усі |
| `/` | космонавт |
| `/training` | космонавт, сон і анкета |
| `/captain` | офіцер |
| `/captain/incident/[id]` | офіцер, break-glass |
| `/medic` | лікар |
| `/medic/crew`, `/medic/crew/[id]` | лікар |
| `/medic/earth` | лікар, пакети і журнал попереджень |
| `/medic/alerts` | лікар |
| `/medic/audit` | лікар, перевірка підпису |

Меню: `lib/navigation.ts`. Числа: `lib/number.ts` (`uk-UA`). Зони на екрані збігаються з `backend/zones.py`. Рішення про статус іде зі штрафу, не з кольору зони.

## Як показ стає статусом

1. `POST /ingest` кладе рядки в чергу. Якщо `time_scale > 1`, час пристрою — це симульований час, медіана зсуву не рахується.
2. Writer пише пачку в SQLite.
3. `scoring/penalty.py` рахує штраф. `scoring/status_machine.py` оновлює статус кожні 5 симульованих секунд і на миттєвих метриках.
4. Вхід у статус 2 відкриває інцидент, break-glass і пакет Землі.
5. Лікар бачить рядки з `ts <= sim_now - SIGNAL_DELAY_SEC`. Вміст пакета — лише після `visible_at`.

`PUT /limits` діє одразу. `POST /actions` офіцера йде на Землю, а дія лікаря — на борт, обидві після затримки.
