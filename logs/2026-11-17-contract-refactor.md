# 2026-11-17 — Сесія агента: верифікація контракту (T-59) і рефакторинг без зміни поведінки (Лаб. 5, крок 3)

**Задача:** крок 3 методички Лаб. 5. Реалізацію Б1–Б3 завершено (871 тест зелений). Три частини
строго по черзі: (1) T-59 — 82 контрактні сценарії `tests/contract/scenarios.json` проти
справжнього сервера до рефакторингу; (2) рефакторинг `src/spm` без зміни зовнішньої поведінки;
(3) підтвердження незмінності: повний pytest, ruff, повторний прогін 82 сценаріїв на тих самих
даних, порівняння журналів. Гілка `agent/contract-refactor` від `main` (`97c5e38`).

## Промпт (суть)

- Тести лише через `.venv` (Python 3.12). Нових залежностей немає.
- Частина 1: підняти імітатор і застосунок командою запуску з Б2 (`uvicorn --no-access-log`,
  тимчасовий секрет у змінній середовища, своя база в `var/`); наповнити систему вигаданими даними
  так, щоб усі 82 сценарії мали сенс; cookie сесій — з `POST /sessions`; скрипт наповнення і
  мінімальні зміни раннера — у `tests/contract/`, `scenarios.json` не змінювати. Протокол: кожен
  сценарій, окремо Н-27, які обмеження mock проти сервера вже не діють. Розбіжності лише
  записувати; якщо розбіжність — помилка коду, зупинитися.
- Частина 2: спершу перелік запахів у `src/spm` (дублювання web/api, довгі функції — особливо
  `update/runner.py` і `api/routes.py`, магічні числа й рядки, непослідовні імена, мертвий код),
  потім малі кроки, кожен — окремий `refactor:`; після кожного кроку — тести зачепленої частини.
  Заборонено змінювати тести, `scenarios.json`, `spec/openapi.yaml` і будь-яку видиму поведінку;
  правило залежностей `docs/architecture.md` лишається.
- Частина 3: повний pytest один раз у кінці, `ruff format --check`, `ruff check`; повторний прогін
  82 сценаріїв, порівняння сценарій у сценарій; аналіз журналів обох контрольних запусків.
- Код — в індекс, зміни `tests/contract/` — окремо в індекс, лог — ні; `var/` не комітити; не
  комітити.

---

## Частина 1. T-59 — 82 сценарії проти справжнього сервера (до рефакторингу)

### Що зроблено в `tests/contract/`

| Файл | Зміна |
|---|---|
| `tests/contract/run_mock_scenarios.py` | мінімальна: параметр `--sessions FILE` — JSON з cookie за тими самими назвами (`admin`, `manager`), що замінює заглушки `mock-admin`/`mock-manager` з `scenarios.json`; опис у докстрінгу. Решта раннера без змін |
| `tests/contract/server_run.py` (новий) | скрипт наповнення і поетапного прогону: каталог `var/contract-<мітка>/`, облікові записи командою, запуск імітатора й застосунку, наповнення через API, прогін раннера етапами (`--only`), зупинка процесів, `results.json` |

`scenarios.json` не змінювався. Pytest скрипт не збирає (назва не `test_*`). `ruff format` і
`ruff check` для обох файлів — чисто.

### Середовище і команди

Одна команда з кореня репозиторію (мітка `before` — до рефакторингу, `after` — після):

```
.venv/Scripts/python.exe tests/contract/server_run.py before
```

Що робить скрипт, щоразу однаково:

1. Створює `var/contract-before/` (якщо каталог існує — зупиняється) і пише туди вигаданий файл
   даних імітатора `sim-data.json`. База, журнал дій, технічний журнал, вивід процесів — там само.
2. Облікові записи `admin` і `manager` — функцією `main()` команди `spm.auth.cli` з
   `read_password` (як у Б1–Б3). Пароль адміністратора — `correct-password` із самого сценарію
   П-01; пароль менеджера і секрет сесії — випадкові `secrets.token_urlsafe`, лише в пам'яті й у
   змінних середовища дочірніх процесів, у файли не пишуться.
3. Імітатор: `python -m simulator 8831 var/contract-before/sim-data.json`. Застосунок — команда
   запуску з Б2: `python -m uvicorn spm.app:create_service --factory --no-access-log --host
   127.0.0.1 --port 8000` (`SPM_SESSION_SECRET`, `SPM_DATABASE_PATH`, `SPM_ACTION_LOG_PATH`,
   `SPM_TECHNICAL_LOG_PATH` — на `var/contract-before/`).
4. Наповнення через API (`http://127.0.0.1:8000/api/v1`, cookie адміністратора з `POST /sessions`).
5. Прогін раннера: `run_mock_scenarios.py http://localhost:8000/api/v1 --target server --sessions
   var/contract-before/sessions.json --only …` — 8 етапів (нижче). Cookie в `sessions.json` —
   з `POST /sessions` (адміністратор і менеджер); для П-03 — окремий файл з другою сесією
   адміністратора.
6. Зупинка застосунку й імітатора, `results.json` — рядок на сценарій у порядку `scenarios.json`.

Реальний годинник: 2026-11-17, 20:12–20:15 за Києвом (+02:00). Наповнення — 8 с; сценарії — ~3 хв:
сценарії йдуть на `localhost`, як у `docs/api/scenarios.md`, а у Windows `localhost` спершу
пробує `::1`, де сервер не слухає, тож кожен запит чекає ~2 с. Тому наповнення скрипт робить
через `127.0.0.1` — на результат це не впливає.

### Дані наповнення (вигадані)

Чотири каталоги імітатора; постачальники обробляються за назвою, позиції — у порядку сторінки, тож
id позицій першого запуску передбачувані: 1–10, 11–22, 23–27, 28–32. Скрипт звіряє id з
очікуваними й зупиняється, якщо щось не так.

| id | Постачальник (розбирач) | Позицій | Для яких сценаріїв |
|---|---|---|---|
| 1 | Арка Плита (`table_layout`) | 10 (АР-101…АР-110) | П-07, Н-08, Н-26, Н-30, Н-31; позиції 1, 2 |
| 2 | Брама Меблі (`cards_layout`) | 12 (БМ-01…БМ-12) | позиції 11, 12 (Н-13), 21 (П-19, П-20) |
| 3 | Вега Фурнітура (`list_layout`) | 5 (ВФ-01…ВФ-05) | запуски 40/41 (П-31, Н-15) |
| 4 | Грань Декор (`table_layout`) | 5 (ГД-01…ГД-05) | П-08; позиція 29 (П-18, Н-06, Н-12, Н-14) |

| id | Матеріал (одиниця) | Навіщо |
|---|---|---|
| 1 | ЛДСП дуб сонома 16 мм (шт) | П-10 (`q=лдсп`), П-12, П-14, П-15, П-22, П-23, Н-10, Н-13, П-18 |
| 2 | Плита МДФ 18 мм (шт) | П-19 (перев'язка 21 → 2), потім П-13 деактивує → Н-14 |
| 3 | Кромка ПВХ біла 2 мм (м.п.) | Н-12: одиниця відрізняється від позиції 29 (шт) |
| 4 | ДВП біле 3 мм (шт) | П-17: позиція АР-102 приходить в «уп» |
| 5 | Плита ДСП біла 16 мм (шт) | позиція 21 до П-19 (щоб П-19 дав 200, а не 201) |

Кроки наповнення:

1. Постачальники 1–4 (`POST /suppliers`, 201 × 4). Доганяння під час старту вже записало «немає
   активних постачальників» (03:30 минув) — скрипт чекає цього запису, щоб доганяння не забрало
   id запуску 1.
2. Запуск 1 (`POST /runs`, 202; скрипт чекає завершення через `GET /runs/{id}`) — позиції 1–32.
3. Матеріали 1–5 (201 × 5); прив'язки АР-101 → 1, АР-102 → 4, БМ-01 → 1, БМ-11 → 5 (201 × 4).
4. В імітаторі АР-102 тепер «уп»; запуск 2 — ціни й події «з'явився»; ціна АР-102 — з позначкою
   «одиниця не збігається» (інших цін цієї дати в неї немає), тож позиція в списку уваги.
5. В імітаторі АР-101 1250,50 → 1313,03 (+5 %); запуски 3…40 — подія «зміна ціни» в запуску 3.
6. Вега в режимі `reduced` (3 з 5 позицій); запуск 41 — Вега «частково», кнопка «прийняти новий
   обсяг» доступна (скрипт це перевіряє).
7. Вегу деактивовано (`PATCH /suppliers/3`), запуск 42 — без Веги, тож 41 лишається її останнім
   запуском зі статусом (П-31), а запуск 40 — ні (Н-15).

### Чому етапи

У `scenarios.json` кілька сценаріїв вимагають станів, що виключають один одного, а Prism стану не
мав (обмеження 2 `docs/api/scenarios.md`). Одним проходом у порядку файлу на тих самих id частина
сценаріїв не мала б сенсу: П-27 (202) і П-28 (200 «немає активних постачальників») і Н-09 (409
«оновлення вже триває») — той самий `POST /runs`; Н-06 (404: позиція 29 без прив'язки) іде після
П-18 (прив'язує 29); П-19 (перев'язка на матеріал 2) іде після П-13 (деактивує матеріал 2); П-03
закриває сесію адміністратора, якою користуються наступні сценарії; Н-45 (500) потребує штучного
збою. Тому раннер запускається 8 разів з `--only`; усередині етапу — порядок `scenarios.json`.

| Етап | Підготовка (скрипт) | Сценарії |
|---|---|---|
| 1 main-1 | — | П-01, П-02, П-04…П-12, П-14…П-17, Н-06 |
| 2 links | — | П-18, П-19, П-20 |
| 3 deactivate-material | — | П-13 |
| 4 main-2 | — | П-21…П-26, П-29…П-37, Н-01…Н-44 крім Н-06, Н-09 |
| 5 run-in-progress | Арка в режимі `slow` (5 с, менше тайм-ауту 30 с) | П-27 (запуск 43 почався), Н-09 (поки 43 триває); далі скрипт чекає кінця 43 і повертає `normal` |
| 6 database-locked | інше з'єднання тримає `BEGIN EXCLUSIVE` на базі (штучний збій, як пропонує обмеження 6) | Н-45 |
| 7 no-active-suppliers | деактивувати всіх активних (1, 2 і 5 — «Альфа» з П-06) | П-28 |
| 8 logout | окрема сесія адміністратора | П-03 |

### Результат: 82 з 82

Вивід скрипту: `82 scenarios: 82 passed, 0 failed`; кожен етап — код виходу раннера 0. Розбіжностей
між контрактом і сервером немає; зупинятися не було потреби.

| ID | Запит | Очікується | Отримано | Результат | Етап |
|---|---|---|---|---|---|
| П-01 | `POST /sessions` | 201 | 201 | ✅ PASS | 1 main-1 |
| П-02 | `GET /sessions/current` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-03 | `DELETE /sessions/current` | 204 | 204 | ✅ PASS | 8 logout |
| П-04 | `GET /suppliers` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-05 | `GET /suppliers` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-06 | `POST /suppliers` | 201 | 201 | ✅ PASS | 1 main-1 |
| П-07 | `GET /suppliers/1` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-08 | `PATCH /suppliers/4` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-09 | `GET /parsers` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-10 | `GET /materials?q=лдсп` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-11 | `POST /materials` | 201 | 201 | ✅ PASS | 1 main-1 |
| П-12 | `GET /materials/1` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-13 | `PATCH /materials/2` | 200 | 200 | ✅ PASS | 3 deactivate-material |
| П-14 | `GET /materials/1/links` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-15 | `GET /materials/1/price-history?period=last_7_days` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-16 | `GET /unlinked-items` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-17 | `GET /attention-items` | 200 | 200 | ✅ PASS | 1 main-1 |
| П-18 | `PUT /supplier-items/29/link` | 201 | 201 | ✅ PASS | 2 links |
| П-19 | `PUT /supplier-items/21/link` | 200 | 200 | ✅ PASS | 2 links |
| П-20 | `DELETE /supplier-items/21/link` | 204 | 204 | ✅ PASS | 2 links |
| П-21 | `GET /material-comparisons` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-22 | `GET /material-comparisons/1` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-23 | `GET /events?material_id=1` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-24 | `GET /supplier-update-statuses` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-25 | `GET /settings` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-26 | `PATCH /settings` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-27 | `POST /runs` | 202 | 202 | ✅ PASS | 5 run-in-progress |
| П-28 | `POST /runs` | 200 | 200 | ✅ PASS | 7 no-active-suppliers |
| П-29 | `GET /runs/42` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-30 | `GET /run-log-entries` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-31 | `POST /volume-acceptances` | 201 | 201 | ✅ PASS | 4 main-2 |
| П-32 | `PATCH /settings` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-33 | `PATCH /settings` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-34 | `PATCH /settings` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-35 | `PATCH /settings` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-36 | `GET /materials` | 200 | 200 | ✅ PASS | 4 main-2 |
| П-37 | `GET /materials?active=true` | 200 | 200 | ✅ PASS | 4 main-2 |
| Н-01 | `GET /material-comparisons` | 401 unauthenticated | 401 | ✅ PASS | 4 main-2 |
| Н-02 | `POST /sessions` | 401 invalid_credentials | 401 | ✅ PASS | 4 main-2 |
| Н-03 | `PATCH /settings` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-04 | `PATCH /materials/1` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-05 | `GET /suppliers/999` | 404 not_found | 404 | ✅ PASS | 4 main-2 |
| Н-06 | `DELETE /supplier-items/29/link` | 404 not_found | 404 | ✅ PASS | 1 main-1 |
| Н-07 | `GET /no-such-resource` | 404 not_found | 404 | ✅ PASS | 4 main-2 |
| Н-08 | `DELETE /suppliers/1` | 405 method_not_allowed | 405 | ✅ PASS | 4 main-2 |
| Н-09 | `POST /runs` | 409 run_in_progress | 409 | ✅ PASS | 5 run-in-progress |
| Н-10 | `PATCH /materials/1` | 409 unit_locked | 409 | ✅ PASS | 4 main-2 |
| Н-11 | `POST /suppliers` | 409 supplier_name_taken | 409 | ✅ PASS | 4 main-2 |
| Н-12 | `PUT /supplier-items/29/link` | 409 link_units_differ | 409 | ✅ PASS | 4 main-2 |
| Н-13 | `PUT /supplier-items/12/link` | 409 material_supplier_already_linked | 409 | ✅ PASS | 4 main-2 |
| Н-14 | `PUT /supplier-items/29/link` | 409 material_inactive | 409 | ✅ PASS | 4 main-2 |
| Н-15 | `POST /volume-acceptances` | 409 volume_acceptance_unavailable | 409 | ✅ PASS | 4 main-2 |
| Н-16 | `PATCH /settings` | 415 unsupported_media_type | 415 | ✅ PASS | 4 main-2 |
| Н-17 | `PATCH /settings` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-18 | `POST /suppliers` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-19 | `GET /suppliers/abc` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-20 | `PATCH /settings` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-21 | `PATCH /settings` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-22 | `GET /materials/1/price-history` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-23 | `GET /events?kind=price_drop` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-24 | `GET /suppliers?page=abc` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-25 | `POST /materials` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-26 | `PATCH /suppliers/1` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-27 | `POST /materials` | 422 validation_failed | 422 | ✅ PASS | 4 main-2 |
| Н-28 | `POST /materials` | 409 material_name_taken | 409 | ✅ PASS | 4 main-2 |
| Н-29 | `POST /suppliers` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-30 | `GET /suppliers/1` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-31 | `PATCH /suppliers/1` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-32 | `GET /parsers` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-33 | `POST /materials` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-34 | `GET /materials/1` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-35 | `GET /materials/1/links` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-36 | `GET /unlinked-items` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-37 | `GET /attention-items` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-38 | `PUT /supplier-items/29/link` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-39 | `DELETE /supplier-items/21/link` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-40 | `GET /settings` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-41 | `POST /runs` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-42 | `GET /runs/42` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-43 | `GET /run-log-entries` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-44 | `POST /volume-acceptances` | 403 forbidden | 403 | ✅ PASS | 4 main-2 |
| Н-45 | `GET /material-comparisons` | 500 internal_error | 500 | ✅ PASS | 6 database-locked |

### Н-27 окремо

Н-27 — єдиний сценарій, який mock не відтворював (Prism 5.16.0 не відповідав на тіло, що не є
JSON; у прогоні 3 `docs/api/mock-run.md` — `SKIP`). Проти сервера: `POST /api/v1/materials`,
`Content-Type: application/json`, тіло `{"name": ` — відповідь одразу, **422**,
`Content-Type: application/problem+json`, `code: validation_failed`, в `errors` є пара
`field: null` / `code: malformed_json` — усе, що перевіряє сценарій. **PASS.** У журналі дій —
`http_request` `POST /api/v1/materials` 422 і запис відмови створення матеріалу (`material_create`,
`result: rejected`, `reason_code: validation_failed`); матеріал не створено.

### Обмеження mock, які проти сервера вже не діють

Обмеження — з `docs/api/scenarios.md` («Відомі обмеження mock»), на які посилається `mock-run.md`.

| № | Обмеження mock | Проти сервера |
|---|---|---|
| 1 | 404 на невідомій адресі й 405 на методі (Н-07, Н-08) — у форматі Prism, перевірявся лише статус | **не діє**: сервер відповідає в моделі помилок контракту — `application/problem+json`, `code` `not_found` і `method_not_allowed`; раннер перевірив усе (позначка `prism_format` діє лише для `--target mock`) |
| 2 | Стан не моделюється: 403, 404, 409 — лише через `Prefer` | **не діє**: усі 403 (Н-03, Н-04, Н-29…Н-44 — 18 операцій «адмін»), 404 (Н-05, Н-06), 409 (Н-09…Н-15, Н-28) дав справжній стан даних; `Prefer` сервер ігнорує. Наслідок — потрібні передумови й етапи (вище) |
| 3 | Для некоректного запиту Prism брав перший приклад 422 | **не діє**: `errors` будує валідація сервера; у Н-17 обидві помилки (поріг і час) — бо обидва поля справді неправильні, а не бо такий перший приклад |
| 4 | Тіло, що не є JSON (Н-27) — mock не відповідав, `SKIP` | **не діє**: 422 `malformed_json`, PASS (вище) |
| 5 | Крок порогу mock не перевіряв (1.25 пропускав, 422 лише через `Prefer`) | **не діє**: Н-21 (1.25) — 422 `notification_threshold_out_of_range` від сервера; П-32…П-35 (0.1, 0.3, 0.5, 50) — 200 |
| 6 | 500 (Н-45) — лише через `Prefer` | **частково**: `Prefer` сервер ігнорує, тому 500 відтворено штучним збоєм (база заблокована іншим з'єднанням). Сервер віддав 500 `internal_error`, `application/problem+json`, без `errors`; у технічному журналі — `unhandled_exception` з `OperationalError: database is locked`. Без штучного збою сценарій на сервері дав би 200 — це властивість сценарію, не помилка коду |

Інші спостереження (не розбіжності):
- П-01 входить як `Admin` при обліковому записі `admin` — 201: логін порівнюється без регістру
  (як у Б1).
- П-05 і П-36: для менеджера в постачальника й матеріалу лише `id`, `name`, `active` — `Prefer:
  example=manager` не потрібен, роль визначає сервер.
- П-24: першим у списку статусів оновлення — «Альфа» (створена в П-06) з `last_update_date: null`
  («ще не оновлювався»): поле є, сценарій перевіряє лише наявність.
- Під час етапу 5 запуск 43 для «Альфи» (адреса `http://localhost:8001/a` з П-06) — «помилка»
  `unavailable`: на 8001 нічого не слухає. Це дані сценарію, не дефект.

---

## Частина 2. Рефакторинг

### Запахи коду в `src/spm`

Перелік складено до першої правки: читання `api/routes.py`, `web/routes.py`, `update/runner.py`,
`services/*`, частин `storage/updates.py`; пошук назв, що ніде не використовуються (скрипт по
`src` і `tests`), і довжин функцій (`ast`, понад 40 рядків: `runner._write` 80, `runner._begin` 77,
`web.log_rows` 59, `directories.update_supplier` 47, `views._comparison_rows` 45; в
`api/routes.py` функцій довших за 40 рядків немає — там запах інший, дублювання представлень).

| № | Де | Що саме | Чому це погано | Крок |
|---|---|---|---|---|
| З-01 | `web/routes.py` `login`, `logout`; `api/routes.py` `set_session_cookie`, `delete_current_session` | атрибути cookie сесії (`max_age`, `httponly`, `samesite="lax"`, `path="/"`) і коментар ЗП-4 записано двічі | дублювання web/api: зміна атрибута в одному місці дасть різні cookie для входу через екран і через API, а REQ-NF-031 вимагає тієї самої поведінки | 1 |
| З-02 | `web/routes.py` `WRONG_CREDENTIALS`; `api/routes.py` `create_session` | текст «Неправильний логін або пароль.» — константа в web і літерал в api | дублювання видимого користувачу тексту; правка в одному місці розведе повідомлення | 1 |
| З-03 | `api/routes.py`, `web/routes.py` | типи об'єктів журналу дій — літерали `"supplier"`, `"material"`, `"supplier_item"`, `"run"`, `"settings"`, `"volume_acceptance"`, `"parser"` (≈45 місць), хоча `services` має константи `SUPPLIER`, `MATERIAL`, `SUPPLIER_ITEM`, `RUN`, `VOLUME_ACCEPTANCE`, `SETTINGS` | магічні рядки: одрук дасть запис журналу з чужим `object_type`, помітний лише в самому журналі | 2 |
| З-04 | `api/routes.py` | форма «`id`, `name`, `active`» тричі (`supplier_json(full=False)`, `material_json(full=False)`, `material_active_json`); `x.isoformat() if x else None` двічі; блок `supplier_item` (`id`, `supplier`, `sku`, `name`, `unit`) тричі (`link_json`, `unlinked_json`, `attention_json`); `moment_json`, `ref_json`, `money_json` розкидані між представленнями | дублювання представлень контракту: зміна схеми потребує однакових правок у кількох місцях; три назви для однієї форми | 3 |
| З-05 | `web/routes.py` | перевірка сесії екранів обох ролей (`session_account` + `redirect("/login")`) — 7 разів і ще в `admin_screen`; рендер `material_form.html` 4 рази з тими самими аргументами (для постачальника вже є `supplier_form`); `x if x is not None else 0` 9 разів без пояснення, чому 0 | дублювання; неявна домовленість «0 — id, якого немає» | 4 |
| З-06 | `web/routes.py` | `auth(request)` у web і `auth_service(request)` в api для того самого; `views_service` оголошено посеред файлу, а не з іншими доступами; адреси `"/login"`, `"/"` — літерали в маршрутах і переадресаціях | непослідовні імена й розміщення; магічні рядки адрес | 5 |
| З-07 | `update/runner.py`, `services/runs.py`, `services/views.py` | види записів журналу оновлень і подій, статус запуску — літерали `"run"`, `"skipped"`, `"no_active_suppliers"`, `"volume_acceptance"`, `"price_change"`, `"appeared"`, `"disappeared"`, `"interrupted"` у трьох модулях, хоча допустимі значення задає схема `storage` | магічні рядки між компонентами; `EVENT_KINDS` у `services` і запис подій в `update` могли б розійтися | 6 |
| З-08 | `update/runner.py` | `_write` — 80 рядків (статус обходу, позиції, ціни й події, відсутні позиції, база обсягу, статус постачальника); `_begin` — 77 рядків (знімок, вставка запуску, журнал) і двічі той самий вираз `MANUAL if trigger == MANUAL else SCHEDULED`; `_execute` — вкладений умовний вираз загального статусу | довгі функції: правила REQ-F-030, REQ-F-032, REQ-F-047, REQ-F-052 важко знайти й перевірити окремо; повтор виразу | 7 |
| З-09 | `update/runner.py` | `state.absences >= 2` (REQ-F-047: два запуски поспіль), `abs(change) * 1000` (поріг у десятих відсотка), `join(timeout=5)` | магічні числа без назви й пояснення | 8 |
| З-10 | `storage/updates.py` `item_ids_by_sku`; `services/directories.py` `SUPPLIER_FIELDS`, `MATERIAL_FIELDS` | ніде не використовуються (у `tests/test_api_directories.py` — власні однойменні константи) | мертвий код: читач шукає, де це потрібно | 9 |
| З-11 | `services/runs.py` `list_log` | кількість сторінок рахується вручну `-(-total // PAGE_SIZE)`, у решті списків — `ceil` у `paginate` | два способи однієї формули сторінок (REQ-F-057) | 10 |
| З-12 | `web/routes.py` `log_rows` | 59 рядків: рядки запуску (по постачальнику) і рядки інших записів в одному циклі | довга функція | 11 |

**Помічено, але не виправлено** (ризик видимої поведінки або нова структура більша за користь):

| № | Де | Що | Чому залишено |
|---|---|---|---|
| З-13 | `api/routes.py`, `web/routes.py` | однакові однорядкові доступи до сервісів (`directories`, `settings_service`, `runs_service`, `views_service`, `actor`) | спільний модуль для них був би новим елементом поза `docs/architecture.md` або залежністю `web → api`, якої в правилі немає; п'ять однорядкових функцій дешевше лишити |
| З-14 | `api/routes.py` | пара `authenticate` + `require_admin(...)` у 18 операціях | залежність чи декоратор FastAPI змінили б порядок перевірок 401 → 403 → 422 (`api/requests.py`), тобто видиму поведінку |
| З-15 | `web/routes.py` | `if not isinstance(account, Account): return account` після `admin_screen`/`user_screen` (~25 разів) | прибрати можна лише декоратором, що змінює сигнатури обробників FastAPI |
| З-16 | `storage/updates.py` | SQL з `'in_progress'`, `'interrupted'`, `'partial'`, `'success'` у тексті запитів | значення збігаються з CHECK `storage/schema.py`; параметризувати всі запити — окрема зміна; біля констант кроку 6 є коментар, що SQL використовує ті самі значення |
| З-17 | `services/directories.py` `update_supplier` (47), `services/views.py` `_comparison_rows` (45) | довгі, але одна послідовна дія (перевірка → зміна → скидання REQ-F-056; рядки порівняння) | поділ не дає зрозумілих частин; до переліку промпту не входили |

### Кроки рефакторингу

Кожен крок — окремий коміт `refactor:`. Код кожного кроку після його тестів додано в індекс; диф
кожного кроку окремо збережено в `var/refactor-steps/step-NN.patch` (`var/` не комітиться), щоб
коміти можна було зробити по одному (`git apply --cached` / `git add -p`).

| Крок | Запах | Коміт | Файли | Тести зачепленої частини | Результат |
|---|---|---|---|---|---|
| 1 | З-01, З-02 | `refactor: share session cookie attributes between web and api` | `src/spm/auth/service.py` (`SESSION_COOKIE_MAX_AGE`, `SESSION_COOKIE_SCOPE`, `WRONG_CREDENTIALS`), `src/spm/api/routes.py`, `src/spm/web/routes.py` | `test_auth`, `test_api_sessions`, `test_screens_roles`, `test_action_log_b1` | 212 passed |
| 2 | З-03 | `refactor: use object type constants in web and api` | `src/spm/services/directories.py` (`PARSER`), `src/spm/services/__init__.py` (експорт констант), `src/spm/api/routes.py`, `src/spm/web/routes.py` | `test_action_log_b1/b2/b3`, `test_screens_roles`, `test_api_errors` | 149 passed |
| 3 | З-04 | `refactor: deduplicate api representations` | `src/spm/api/routes.py` (`date_json`, `active_ref_json`, `supplier_item_json`; прибрано `material_active_json`) | `test_api_directories`, `test_api_errors`, `test_api_runs`, `test_api_sessions`, `test_api_views`, `test_attention_items`, `test_update_statuses` | 300 passed |
| 4 | З-05 | `refactor: extract web screen helpers` | `src/spm/web/routes.py` (`user_screen`, `material_form`, `known_id`) | `test_screens_directories/feed/history/links/roles/updates`, `test_comparison`, `test_auth` | 273 passed |
| 5 | З-06 | `refactor: align web service accessor names and paths` | `src/spm/web/routes.py` (`auth` → `auth_service`, `views_service` до інших доступів, `LOGIN_PATH`, `HOME_PATH`) | `test_auth`, `test_screens_roles`, `test_screens_directories`, `test_action_log_b1` | 207 passed |
| 6 | З-07 | `refactor: name run log entry and event kinds` | `src/spm/storage/updates.py` (`ENTRY_*`, `EVENT_*`, `RUN_INTERRUPTED`), `src/spm/update/runner.py`, `src/spm/services/runs.py`, `src/spm/services/views.py` | `test_update_run`, `test_feed_assortment`, `test_feed_price_change`, `test_scheduler`, `test_deactivation`, `test_api_runs`, `test_api_views`, `test_screens_feed` | 191 passed |
| 7 | З-08 | `refactor: split long functions of the update runner` | `src/spm/update/runner.py` (`crawl_status`, `overall_status`, `_open_run`, `_write_items`, `_mark_missing`; `_write` 80 → 28 рядків, `_begin` 77 → 57) | `test_update_run`, `test_feed_*`, `test_scheduler`, `test_deactivation`, `test_api_runs`, `test_screens_updates`, `test_action_log_b2`, `test_update_statuses` | 206 passed |
| 8 | З-09 | `refactor: name magic numbers of the update runner` | `src/spm/update/runner.py` (`DISAPPEAR_AFTER_ABSENCES`, `SCHEDULER_STOP_SECONDS`, `_TENTHS_IN_WHOLE`) | `test_feed_assortment`, `test_feed_price_change`, `test_scheduler`, `test_settings` | 115 passed |
| 9 | З-10 | `refactor: remove unused storage and services names` | `src/spm/storage/updates.py`, `src/spm/services/directories.py` | `test_update_run`, `test_api_directories`, `test_skeleton` | 191 passed |
| 10 | З-11 | `refactor: count run log pages like other lists` | `src/spm/services/ordering.py` (`page_count`), `src/spm/services/runs.py` | `test_api_runs`, `test_screens_updates`, `test_api_directories` | 205 passed |
| 11 | З-12 | `refactor: split run rows out of the web run log` | `src/spm/web/routes.py` (`run_rows`) | `test_screens_updates`, `test_screens_roles` | 105 passed |

Після кожного кроку — `ruff format` і `ruff check src` (чисто). Порядок роботи з базою й годинником у
`runner` не змінено: `now` у `_write` береться один раз на початку, як і раніше, і передається в
`_write_items` і `_mark_missing`; черговість запитів (база обсягу → позиції → відсутні → база обсягу
→ статус) та сама. Ключі JSON-відповідей і їхній порядок ті самі (`active_ref_json` дає `id`, `name`,
`active`; `supplier_item_json` — `id`, `supplier`, `sku`, `name`, `unit`, далі `last_seen_date`).
Перевірка, що патчі кроків складаються в проіндексований код: `step-01…11.patch` по черзі
застосовано (`git apply`) до `src` з `HEAD` у тимчасовому каталозі — результат ідентичний `src`.

Під час кроку 4 скрипт правки двічі зупинився на власній перевірці кількості збігів (очікував 10
замін `… if … is not None else 0`, їх 9; шаблон перевірки сесії траплявся 8 разів разом з
`admin_screen`) — файл тоді не змінювався; виправлено очікування, крок повторено.

**Правило залежностей** після рефакторингу (імпорти між пакетами `src/spm`): `web → auth, services,
clock`; `api → auth, services, clock`; `services → storage, clock`; `update → services, storage,
logging, clock`; `auth → storage, logging, clock` (і `config` лише в команді `auth/cli.py`, як до
рефакторингу). Нових стрілок немає: `web` і `api` до `storage` не ходять, `services` від `update` і
FastAPI не залежить. Тести, `scenarios.json`, `spec/openapi.yaml`, шаблони не змінювались.

---

## Частина 3. Підтвердження незмінності поведінки

### Повний прогін і ruff

- `.venv/Scripts/python.exe -m pytest -q --tb=short` (один раз, після всіх 11 кроків):
  **871 passed, 1 warning in 789.54s** (13 хв 10 с) — стільки ж тестів, скільки до рефакторингу.
  Попередження — `StarletteDeprecationWarning` з `fastapi.testclient`, як у Б1–Б3.
- `ruff format --check src simulator tests` — «76 files already formatted».
- `ruff check src simulator tests` — «All checks passed!».

### Повторний прогін 82 сценаріїв на тих самих даних

`.venv/Scripts/python.exe tests/contract/server_run.py after` — той самий скрипт, ті самі вигадані
дані й етапи, нова база в `var/contract-after/` (першу базу сценарії вже змінили: П-06 створив
«Альфу», П-13 деактивував матеріал, тож прогін на ній дав би інші коди). 2026-11-17,
20:58–21:01 за Києвом. Вивід: `82 scenarios: 82 passed, 0 failed`.

Порівняння `var/contract-before/results.json` і `var/contract-after/results.json` за всіма полями
(ID, запит, очікується, отримано, результат, примітка, етап): **82 з 82 збігаються, різниць 0.**

| ID | Очікується | До | Після | Збіг |
|---|---|---|---|---|
| П-01 | 201 | 201 PASS | 201 PASS | так |
| П-02 | 200 | 200 PASS | 200 PASS | так |
| П-03 | 204 | 204 PASS | 204 PASS | так |
| П-04 | 200 | 200 PASS | 200 PASS | так |
| П-05 | 200 | 200 PASS | 200 PASS | так |
| П-06 | 201 | 201 PASS | 201 PASS | так |
| П-07 | 200 | 200 PASS | 200 PASS | так |
| П-08 | 200 | 200 PASS | 200 PASS | так |
| П-09 | 200 | 200 PASS | 200 PASS | так |
| П-10 | 200 | 200 PASS | 200 PASS | так |
| П-11 | 201 | 201 PASS | 201 PASS | так |
| П-12 | 200 | 200 PASS | 200 PASS | так |
| П-13 | 200 | 200 PASS | 200 PASS | так |
| П-14 | 200 | 200 PASS | 200 PASS | так |
| П-15 | 200 | 200 PASS | 200 PASS | так |
| П-16 | 200 | 200 PASS | 200 PASS | так |
| П-17 | 200 | 200 PASS | 200 PASS | так |
| П-18 | 201 | 201 PASS | 201 PASS | так |
| П-19 | 200 | 200 PASS | 200 PASS | так |
| П-20 | 204 | 204 PASS | 204 PASS | так |
| П-21 | 200 | 200 PASS | 200 PASS | так |
| П-22 | 200 | 200 PASS | 200 PASS | так |
| П-23 | 200 | 200 PASS | 200 PASS | так |
| П-24 | 200 | 200 PASS | 200 PASS | так |
| П-25 | 200 | 200 PASS | 200 PASS | так |
| П-26 | 200 | 200 PASS | 200 PASS | так |
| П-27 | 202 | 202 PASS | 202 PASS | так |
| П-28 | 200 | 200 PASS | 200 PASS | так |
| П-29 | 200 | 200 PASS | 200 PASS | так |
| П-30 | 200 | 200 PASS | 200 PASS | так |
| П-31 | 201 | 201 PASS | 201 PASS | так |
| П-32 | 200 | 200 PASS | 200 PASS | так |
| П-33 | 200 | 200 PASS | 200 PASS | так |
| П-34 | 200 | 200 PASS | 200 PASS | так |
| П-35 | 200 | 200 PASS | 200 PASS | так |
| П-36 | 200 | 200 PASS | 200 PASS | так |
| П-37 | 200 | 200 PASS | 200 PASS | так |
| Н-01 | 401 unauthenticated | 401 PASS | 401 PASS | так |
| Н-02 | 401 invalid_credentials | 401 PASS | 401 PASS | так |
| Н-03 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-04 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-05 | 404 not_found | 404 PASS | 404 PASS | так |
| Н-06 | 404 not_found | 404 PASS | 404 PASS | так |
| Н-07 | 404 not_found | 404 PASS | 404 PASS | так |
| Н-08 | 405 method_not_allowed | 405 PASS | 405 PASS | так |
| Н-09 | 409 run_in_progress | 409 PASS | 409 PASS | так |
| Н-10 | 409 unit_locked | 409 PASS | 409 PASS | так |
| Н-11 | 409 supplier_name_taken | 409 PASS | 409 PASS | так |
| Н-12 | 409 link_units_differ | 409 PASS | 409 PASS | так |
| Н-13 | 409 material_supplier_already_linked | 409 PASS | 409 PASS | так |
| Н-14 | 409 material_inactive | 409 PASS | 409 PASS | так |
| Н-15 | 409 volume_acceptance_unavailable | 409 PASS | 409 PASS | так |
| Н-16 | 415 unsupported_media_type | 415 PASS | 415 PASS | так |
| Н-17 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-18 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-19 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-20 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-21 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-22 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-23 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-24 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-25 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-26 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-27 | 422 validation_failed | 422 PASS | 422 PASS | так |
| Н-28 | 409 material_name_taken | 409 PASS | 409 PASS | так |
| Н-29 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-30 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-31 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-32 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-33 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-34 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-35 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-36 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-37 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-38 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-39 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-40 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-41 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-42 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-43 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-44 | 403 forbidden | 403 PASS | 403 PASS | так |
| Н-45 | 500 internal_error | 500 PASS | 500 PASS | так |

### Аналіз журналів обох контрольних запусків

| | До (`var/contract-before/`) | Після (`var/contract-after/`) |
|---|---|---|
| Журнал дій, записів | 666 | 667 |
| з них `http_request` | 293 | 294 |
| з них інші події | 373 | 373 |
| Технічний журнал, записів | 3 | 3 |

**Журнал дій.** Набір подій однаковий, кількість кожної події однакова: `supplier_status` 170,
`manual_run` 45, `run_started` 43, `run_finished` 43, `access_denied` 18, `material_create` 9,
`settings_update` 8, `supplier_create` 7, `link_create` 6, `supplier_deactivate` 5,
`login_succeeded` 4, `link_change` 3, `account_created` 2, `no_active_suppliers` 2, `volume_accept`
2, `login_failed` 1, `logout` 1, `link_remove` 1, `material_deactivate` 1, `material_update` 1,
`supplier_update` 1. Набір полів кожної події однаковий (наприклад, `supplier_status` — `time`,
`level`, `event`, `login`, `role`, `request_id`, `result`, `run_id`, `supplier_id`, `status`,
`parsed_items_count`, `reason_code`; `access_denied` — `action`, `object_type`, `object_id` поверх
спільних). Усі 373 записи, крім `http_request`, порівняно поелементно без `time` і
`request_id`: **послідовність ідентична** — ті самі `object_type` (`supplier`, `material`,
`supplier_item`, `run`, `settings`, `volume_acceptance`, `parser`), `reason_code`, `result`,
`trigger`, статуси й кількості позицій.

**`http_request`.** За методом, шаблоном шляху, кодом і логіном збігаються всі групи, крім однієї:
`GET /api/v1/runs/{id}` 200 (admin) — 146 до, 147 після. Це опитування самого скрипта
(`wait_run` чекає кінця кожного з 43 запусків, крок 0,1 с), кількість опитувань залежить від
тривалості запуску; сценарії тут ні до чого. Шлях без рядка запиту — у всіх записах обох журналів.

**Ідентифікатор запиту.** В обох журналах кожен запис, крім `http_request`, має `request_id`
якогось HTTP-запиту, за двома винятками, однаковими до і після: `account_created` × 2 (`null`,
команда поза HTTP) і `no_active_suppliers` × 2 (id запису журналу оновлень: доганяння під час
старту і П-28 — так задано в Б2).

**Технічний журнал** — ті самі 3 записи в тому самому порядку: `supplier_update_failed` (запуск
43, «Альфа» з П-06, `unavailable` — на `localhost:8001` нічого не слухає), `scheduler_failed`
(`OperationalError: database is locked` — планувальник під час штучного збою етапу 6),
`unhandled_exception` (`/api/v1/material-comparisons`, та сама причина — Н-45). Кількість
`scheduler_failed` залежить від того, скільки перевірок планувальника припало на ~5 с блокування;
обидва рази — одна.

**Секрети.** В обох журналах немає `spm_session`, `password`, `correct-password`, `scrypt$`.
Секрет сесії й пароль менеджера ніде не друкувалися. Файли `sessions*.json` з cookie сесій лежать
лише у `var/contract-*/` (не комітиться); сесії закінчуються через 8 годин, сервер зупинено.

### Висновок

Зовнішня поведінка після 11 кроків рефакторингу та сама: 871 тест, 82 контрактні сценарії
сценарій у сценарій, ті самі події й поля в обох журналах.

## Стан індексу

Коміту немає. В індексі (`git diff --cached --stat`: 12 файлів):

- **Код** (`src/spm`, 10 файлів: `api/routes.py`, `auth/service.py`, `services/__init__.py`,
  `services/directories.py`, `services/ordering.py`, `services/runs.py`, `services/views.py`,
  `storage/updates.py`, `update/runner.py`, `web/routes.py`) — усі 11 кроків разом.
- **`tests/contract/`** (окремий коміт, наприклад `test: run contract scenarios against the
  server`):
  - `tests/contract/run_mock_scenarios.py` — змінено (`--sessions`);
  - `tests/contract/server_run.py` — новий.

Щоб закомітити кроки по одному: `git restore --staged src`, далі для кожного NN від 01 до 11
`git apply --cached var/refactor-steps/step-NN.patch` і коміт з повідомленням із таблиці кроків
(патчі послідовно відтворюють код у робочому дереві — перевірено). Трейлер кожного коміту:
`Author-role: agent`, `Agent: claude-code`.

Не в індексі: цей лог і `var/` (`var/contract-before/`, `var/contract-after/` — бази, журнали,
вивід етапів, `results.json`, cookie сесій; `var/contract-*.console.txt`;
`var/full-pytest-after.txt`; `var/refactor-steps/`). Пропозиція для логу —
`log: record contract verification and refactoring session`.
