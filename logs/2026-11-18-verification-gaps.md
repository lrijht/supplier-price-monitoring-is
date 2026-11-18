# 2026-11-18 — Закриття розбіжностей незалежної верифікації (Р-01…Р-07)

- Агент: claude-code (Opus 5.5). Гілка `agent/verification-gaps` від `main` (`239e43f`).
- Вхід: `logs/2026-11-18-verification.md`, розд. 5. Тести — лише через `.venv` (Python 3.12.15).
- Код `src/` і SRS не змінювались. Нових залежностей немає.

## Підсумок по знахідках

| № | Що було | Що зроблено | Стан |
|---|---|---|---|
| Р-01 | Немає тестів швидкодії REQ-NF-008, REQ-NF-009 (T-45) | `tests/test_performance.py` з міткою `performance`; прогін, протокол `logs/2026-11-18-performance.md` | закрито: обидві вимоги вкладаються |
| Р-02 | Немає протоколу ручної перевірки в Chrome і Firefox (REQ-NF-002, T-48) | — | **відкрито**: ручна перевірка — справа людини (T-48) |
| Р-03 | `spm/auth/cli.py` імпортує `spm.config` всупереч букві правила залежностей | — | **відкрито**: потрібне рішення людини — уточнити правило в `docs/architecture.md` («точки входу читають config») чи змінити код |
| Р-04 | Слабкі асерти REQ-F-005, REQ-NF-003, REQ-NF-032, REQ-F-036 | 4 тести посилено, кожне посилення перевірено мутацією | закрито |
| Р-05 | Дрібні прогалини тестів REQ-F-028, REQ-F-035, REQ-NF-033 | — | відкрито, поза цим завданням (не входило до чотирьох тестів) |
| Р-06 | REQ-F-042 «не надсилає e-mail / push» без тесту | — | інформативно; перевіряється інспекцією |
| Р-07 | Немає інструкції T-46; `resources.md` розд. 0 без винятку `text/csv`; `architecture.md` без REQ-F-072 | `docs/run.md`, посилання з `README.md`; обидві правки в `docs/` | закрито |

## 1. Р-01 — тести швидкодії (T-45)

`tests/test_performance.py`, `pytestmark = pytest.mark.performance`. У `pyproject.toml` мітку
зареєстровано (`markers`) і виключено зі звичайного прогону (`addopts = "-ra -m 'not
performance'"`); окрема команда — `python -m pytest -m performance -s tests/test_performance.py`
(ключ `-m` з командного рядка перекриває `addopts`). Перевірено: звичайний
`python -m pytest tests/test_performance.py` — «2 deselected».

- `test_run_of_all_simulator_suppliers_within_5_minutes` (REQ-NF-008): імітатор зі штатним файлом
  даних (копія) на `127.0.0.1` через uvicorn, система на системному годиннику, 3 постачальники
  через API, ручний запуск, різниця `finished_at − started_at` запуску ≤ 5 хв; статус «успіх» у
  всіх постачальників.
- `test_screens_on_test_volume_within_2_seconds` (REQ-NF-009): обсяг SRS напряму в SQLite
  (1 000 × 10 позицій, 3 650 000 цін дня, 10 000 подій), чотири екрани менеджера по 3 рази,
  `time.perf_counter`, найгірший ≤ 2 с. Рядок `PERFORMANCE` з вимірами і характеристиками машини
  (процесор, пам'ять, ОС, Python) — для протоколу.

Виміри (деталі — у протоколі): REQ-NF-008 — 0 с за журналом (0,16 с за годинником тесту);
REQ-NF-009 — список порівняння 0,657 с, порівняння матеріалу 0,018 с, історія за весь період
0,246 с, стрічка 0,090 с. Усе в межах; оптимізувати не довелося.

Під час написання: перший запуск тесту REQ-NF-008 упав на помилці самого тесту (`run["suppliers"]`
замість поля контракту `supplier_run_statuses`); виправлено в тесті.

## 2. Р-04 — посилені тести

Старі перевірки не прибиралися; нові додано поруч. Допоміжні функції — у `tests/helpers_b3.py`:
`screen_content` (комірки таблиць без заголовків і значення видимих полів форм), `shows` (значення
як окреме слово), `nav_links` (адреси посилань `<nav>`).

| REQ | Тест | Що додано |
|---|---|---|
| REQ-F-005 | `test_screens_roles::test_manager_other_screens_no_access` (6 екранів) | вміст того самого екрана в адміністратора (дати, статуси, назви, налаштування) не з'являється на сторінці «немає доступу» менеджера; вміст не порожній |
| REQ-F-005 | `test_screens_updates::test_manager_no_access_to_log` | журнал має два запуски Альфи й Бети; на сторінці менеджера немає «не знайдено», жодного значення журналу адміністратора і жодного слова статусу |
| REQ-NF-003 | `test_screens_roles::test_admin_navigation`, `::test_manager_navigation` | меню `<nav>` дорівнює рівно 10 (адміністратор) і рівно 4 (менеджер) екранам без id запису, а не містить їх |
| REQ-NF-032 | `test_action_log_b3::test_views_do_not_return_action_log` | перелік адрес: з 10 до 29 — усі 11 екранів і всі читальні операції контракту (зокрема `sessions/current`, `runs/{id}`, `run-log-entries`, вивантаження CSV); перед читанням — зміни, запуск і відмова менеджеру, тож у журналі є різні записи; усі відповіді 200 |
| REQ-F-036 | `test_comparison::test_stale_boundary` | на екрані порівняння в рядку застарілої ціни обидві колонки різниці — «—», коли ціна Бети придатна; свіжа найдешевша — «0,0 %» |

Усі посилені тести проходять на поточному коді — розбіжностей реалізації не виявлено.

### Мутаційна перевірка

Копія `src`, `tests`, `simulator`, `pyproject.toml` у скретчпаді сесії (поза репозиторієм);
перевірено, що тести копії імпортують `spm` з копії. Для кожної мутації: нові тести без мутації,
старі тести (версія з `HEAD`) з мутацією, нові з мутацією, нові після відновлення файла.
`src/` репозиторію не змінювався (`git status` — без змін у `src`).

| № | REQ | Мутація | Нові, без мутації | Старі, з мутацією | Нові, з мутацією | Нові, після відновлення |
|---|---|---|---|---|---|---|
| M1 | REQ-F-005 | `/run-log-entries` для менеджера: 403 і «немає доступу», але з таблицею журналу | 7 passed | 7 passed | **2 failed**, 5 passed | 7 passed |
| M2 | REQ-NF-003 | 12-й пункт меню адміністратора (`/volume-acceptances`) у `base.html` | 11 passed | 11 passed | **11 failed** | 11 passed |
| M3 | REQ-NF-032 | екран «налаштування» дописує в HTML ідентифікатор запиту з журналу дій | 1 passed | 1 passed | **1 failed** | 1 passed |
| M4 | REQ-F-036 | на екрані для застарілої ціни різниця «0,0 %» замість «—» | 2 passed | 2 passed | **1 failed**, 1 passed | 2 passed |

M1 ламає лише журнал оновлень, тому падають рівно два тести (параметр `/run-log-entries` і
`test_manager_no_access_to_log`); M4 — лише випадок застарілої ціни. Кожну мутацію старі тести
пропускають, а нові ловлять.

## 3. Р-07 — T-46 і документація

`docs/run.md` (українською): встановлення, конфігурація (усі 4 параметри `spm/config.py`),
облікові записи, імітатор і його режими, запуск системи, база і журнали, тести (звичайні, покриття,
швидкодія, ruff), контрактний прогін проти mock і сервера. Посилання — з `README.md`, розділ
«Running».

Перевірка команд (2026-11-18):

| Команда | Як перевірено | Результат |
|---|---|---|
| `python -m pip install -e ".[dev]"` | `--dry-run` у `.venv` | залежності задоволені, «Would install supplier-price-monitoring-is-0.1.0» |
| `uvicorn spm.app:create_service --factory --no-access-log` без `SPM_SESSION_SECRET` | тимчасовий каталог без `.env` | код виходу 1, повідомлення називає `SPM_SESSION_SECRET` |
| `python -m spm.auth.cli <логін> admin` | тимчасовий каталог з `.env`; та сама `main()` з поданим паролем | запис створено, «…з роллю admin створено.» |
| `python -m spm.auth.cli --help` | запуск | код 0, текст довідки збігається з `docs/run.md` |
| `python -m simulator` | запуск, `GET /catalog/alfa` | 200 на `127.0.0.1:8001` |
| `uvicorn spm.app:create_service --factory --no-access-log --port 8010` | запуск з `.env`, `GET /login`, `POST /api/v1/sessions` | 200; вхід створеним записом — 201 |
| база і журнали у `var/` | вміст `var/` тимчасового каталогу | `spm.db`, `actions.log`; `technical.log` з'являється з першим записом (так і написано) |
| `python -m pytest --cov=spm --cov-report=term` | на `tests/test_skeleton.py` | працює, рядок `TOTAL` |
| `python -m pytest -m performance -s tests/test_performance.py` | повний прогін | 2 passed (розд. 1) |
| `npx prism mock -p 4010 spec/openapi.yaml` + `python tests/contract/run_mock_scenarios.py` | повний прогін | 85 passed, 0 failed, 1 skipped (Н-27) |
| `python tests/contract/server_run.py <мітка>` | мітка `docs-run-check` | 86 passed, 0 failed; `var/contract-docs-run-check/results.json` |
| `ruff format --check`, `ruff check` по `src simulator tests` | запуск | розд. 5 |

Обмеження перевірки: інтерактивне введення пароля (`getpass`) у Windows не подається через канал,
тому команду створення запису перевірено викликом тієї самої `main()` з функцією введення пароля
(як у тестах `run_account_command`). Активацію `.venv\Scripts\activate` і `npm install` окремо не
перевіряли: середовище й `node_modules` уже були; `py -3.12 -m venv` не запускали, щоб не
перестворювати `.venv`.

Інші документаційні залишки:

- `docs/api/resources.md`, розд. 0: «Дані — JSON (REQ-NF-031)» доповнено винятком — операція 29
  (REQ-F-072) відповідає `text/csv`, помилки — у моделі помилок API (як у REQ-NF-031 SRS).
- `docs/architecture.md`, розд. 4, рядок `services`: додано «вивантаження загального списку
  порівняння в CSV» і REQ-F-072.

### Матриця трасування

`tests/test_performance.py` цитує REQ-NF-008 і REQ-NF-009, а `docs/architecture.md` — тепер і
REQ-F-072, тож згенерована матриця змінилась, і без регенерації `test_traceability` падав би
(`--check` показав розбіжність). Матрицю перегенеровано генератором без змін у ньому; змінилися
три рядки: REQ-NF-008 і REQ-NF-009 — «Тест» `test_performance.py` замість приміток про T-45;
REQ-F-072 — у «Документації» додано `docs/architecture.md`. Це окрема, четверта група індексу
(`spec:`), бо `spec/` з `docs/` в одному коміті не комітиться.

## 4. Що лишається

- Р-02 — ручна перевірка в Chrome і Firefox і протокол (T-48), людина.
- Р-03 — рішення щодо `spm/auth/cli.py` і правила залежностей.
- Р-05 — три дрібні посилення тестів (REQ-F-028: немає ціни за 10-06; REQ-F-035: «грн» на екрані;
  REQ-NF-033: порівняння з відповіддю без збою).
- Перевірка команди покриття на одному модулі записала файл `.coverage` (ігнорується git) поверх
  того, що міг лишитися від прогону A-06; файл потім видалено. Підсумок покриття A-06 (97 %) — у
  `logs/2026-11-18-a06-feature.md` і `var/a06-full-pytest-cov.txt`.
- Каталог `var/contract-docs-run-check/` (ігнорується git) — результати контрактного прогону для
  перевірки інструкції.

## 5. Прогін нових і змінених тестів

Повний pytest не запускався. Запущено змінені модулі, усі модулі, що імпортують змінений
`tests/helpers_b3.py`, і нові тести:

| Що | Команда | Результат |
|---|---|---|
| `test_api_views`, `test_attention_items`, `test_comparison`, `test_deactivation`, `test_export_csv`, `test_screens_feed`, `test_screens_history`, `test_screens_roles`, `test_screens_updates`, `test_action_log_b3`, `test_traceability` | `.venv/Scripts/python.exe -m pytest -q <модулі>` | 270 passed, 7 хв 01 с |
| `test_performance` | `.venv/Scripts/python.exe -m pytest -q -m performance tests/test_performance.py` | 2 passed |
| стиль | `ruff format --check src simulator tests`; `ruff check src simulator tests` | 79 files already formatted; All checks passed |

## Стан індексу

Чотири групи для чотирьох окремих комітів; протокол швидкодії і цей лог — не в індексі.

1. `test:` (тести швидкодії) — `tests/test_performance.py`, `pyproject.toml`; наприклад
   `test: add performance tests for REQ-NF-008 and REQ-NF-009`.
2. `test:` (посилені тести) — `tests/helpers_b3.py`, `tests/test_screens_roles.py`,
   `tests/test_screens_updates.py`, `tests/test_action_log_b3.py`, `tests/test_comparison.py`;
   наприклад `test: strengthen role, navigation, action log and stale tests`.
3. `docs:` — `docs/run.md`, `README.md`, `docs/api/resources.md`, `docs/architecture.md`;
   наприклад `docs: add run instructions and fix CSV notes in API and design`.
4. `spec:` — `spec/traceability.md`; наприклад
   `spec: regenerate traceability after performance tests`.

Порядок: 1, 2, 3, потім 4 (матриця згенерована після тестів і документації). Індекс спільний,
тому кожен коміт — з переліком файлів: `git commit -- <файли>`.
