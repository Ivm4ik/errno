# Сценарії генератора

Генератор окремий від бекенда і не імпортує його. Команди:

```bash
python -m generator list
python -m generator serve --port 8100   # окремий веб-UI генератора
python -m generator run --scenario solar_storm --astronaut A1 --backend http://127.0.0.1:8000 --device-token "$DEVICE_TOKEN" --time-scale 60
python -m generator run --scenario-file generator/scenarios/nominal.yaml --no-network
python -m generator run --plan multi_astronaut --time-scale 60
```

`--time-scale 60` означає, що 1 реальна секунда = 1 симульована хвилина. Затримка Землі 20 хвилин тоді триває 20 реальних секунд. `--no-network` друкує JSONL і нікуди не шле. `device_id` завжди `sim-gw-1`.

Шум навколо бази менший за допуск, тож у номіналі штраф близький до нуля. Під час `exercise` пульс, дихання і лактат фізіологічно ростуть, а бекенд обнуляє їхній штраф. `eva` ріст не обнуляє.

| Файл | Що має статись |
|---|---|
| `nominal` | 90 с роботи, статус 0 |
| `exercise_false_alarm` | 90 с вправи, пульс високий, статус 0 |
| `mild_warning` | температура +1 °C, статус 1 до третього сповіщення |
| `slow_drift_3_notices` | тиск у жовтій смузі довше двох вікон 5 хв, потім статус 2 |
| `cardiac_stress` | пульс +80, одразу статус 2 і break-glass |
| `solar_storm` | доза 1.8 мЗв/доба під час EVA, статус 2; пакет Землі видимий через затримку |
| `hypoglycemia` | глюкоза 40 мг/дл, статус 2 |
| `hyperkalemia` | калій 6.0, статус 2 |
| `co2_leak` | CO2 1.5%, статус 2 |
| `infection` | температура і сатурація, статус 1 |
| `sleep_loss` | сон 4 год, статус 2 |
| `sensor_fault` | пульс з якістю 0.2, медичний статус 0, далі тривога обладнання |
| `comms_loss_buffering` | дірка в сигналі, далі пакети з `buffered: true` |
| `duplicate_and_gap` | повтор `seq` і стрибок номера |
| `multi_astronaut` | A1 у статусі 2, A2 у статусі 0 |

Поле `expect` у YAML — очікування для перевірки, не команда бекенду.
