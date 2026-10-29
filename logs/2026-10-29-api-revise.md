# 2026-10-29 — Сесія агента: виправлення контракту API після REVISE (Лаб. 4, API-GATE)

**Задача:** закрити зауваження РА-01…РА-16 першої перевірки на API-GATE
(`logs/2026-10-29-api-review.md`, рішення REVISE у `logs/gates.md`) за рішеннями людини. Гілка
`agent/api-revise`. SRS 1.9 не змінювали: усі виправлення — у контракті й документах API.
Серверного коду не писали, `/src` не змінено.

## Промпт (суть)

Людина дала рішення щодо кожного РА (коротко — у колонці «Рішення» таблиці нижче) і попросила:
після правок — `npm run api:lint` (0 помилок, 0 попереджень) і прогін усіх сценаріїв проти mock;
результати — новим розділом «Повторна перевірка після REVISE» у `docs/api/validation.md` і
`docs/api/mock-run.md`, попередні прогони лишити; у `docs/api/resources.md`, розділ 6, — що закрито
якими РА; лог з таблицею «РА → що зроблено → файл». Якщо рішення суперечить SRS 1.9 або доводиться
вигадувати нове — стоп і питання. Нічого не додавати в індекс і не комітити.

## Звірка з SRS 1.9

Перед правками рішення звірено з текстом SRS: REQ-F-003…REQ-F-005, REQ-F-019, REQ-F-034,
REQ-F-040, REQ-F-049, REQ-F-070, REQ-NF-016, REQ-NF-018, REQ-NF-031, Д.5, Д.6, Д.8, Д.9, BDD-070.
Суперечностей не знайдено:
- РА-12: REQ-F-070 забороняє менеджерові лише адресу каталогу й розбирач, а поля, яких менеджер
  тепер не отримує, видно на його екранах іншими шляхами (дата останнього оновлення — REQ-F-034,
  `GET /supplier-update-statuses`) або не потрібні жодному його екрану (одиниця і кількість
  прив'язок — колонки адміністративного екрана, REQ-F-068). Критерій REQ-F-070 і BDD-070 (М2 і В у
  списках, немає адреси каталогу й розбирача) виконується.
- РА-11: Д.8 і REQ-NF-016 вимагають «текст збою запису»; коротка українська фраза — такий текст, а
  подробиці йдуть у технічний журнал REQ-NF-018. Рецензент теж не вважав це суперечністю.
- РА-09: «більше 0» для ціни дня й цін події — з Д.5 і Д.6. Рішення людини називало ціну дня і
  стару/нову ціну події; схему `Price` (більше 0) застосовано до всіх цін, бо Д.6 і для ціни події
  «з'явився» задає «більше 0», а ціни в історії й загальному списку — це ціни дня. Нулем може бути
  лише `difference_from_cheapest.amount` — схема `Amount`.

## Питання до людини під час сесії

**РА-10, `Location` для `POST /volume-acceptances`.** Рішення — «`Location` у всіх 201», але
окремої адреси прийняття нового обсягу ні в контракті, ні в `resources.md` немає; дати їй адресу
означало б вигадати новий URI. Агент зупинився і запитав. Варіанти: `/volume-acceptances/{id}` без
операцій; без `Location`; `/run-log-entries`. **Рішення людини: без `Location`** — виняток
записано в `info.description`, в описі відповіді 201 і в розділі 0 `resources.md`.

## Що зроблено

| РА | Рішення людини | Що зроблено | Файл |
|---|---|---|---|
| РА-01 | прибрати `multipleOf`, лишити межі 0,1 і 50; крок перевіряє сервер, інакше 422 `notification_threshold_out_of_range` | `multipleOf: 0.1` прибрано з `Settings` і `SettingsUpdate`; опис поля: крок перевіряє сервер і чому `multipleOf` немає. Прикладу 422 саме для 1.25 у контракті не було (`validation_failed_threshold_out_of_range` — для 50,1) — додано `validation_failed_threshold_step` в `updateSettings` | `spec/openapi.yaml`; `docs/api/resources.md` (розділи 0, 2.1, 4) |
| РА-02 | 500 `internal_error`, «Внутрішня помилка сервера», «Сталася внутрішня помилка. Спробуйте пізніше.»; спільна відповідь у всіх 28 операціях | `components/responses/InternalServerError`, приклад `internal_error`; `'500'` у всіх 28 операціях; `internal_error` у `ProblemCode`, «Внутрішня помилка сервера» в `Problem.title`; `info.description` і опис `Problem` — «кожна відповідь з помилкою, зокрема 500» | `spec/openapi.yaml`; `docs/api/resources.md` (розділи 3, 4: «кожна відповідь з помилкою — і 4xx, і 5xx», `title` 500, код `internal_error`, правило про 500) |
| РА-03 | REQ-F-003, REQ-F-004, REQ-F-005 в `x-req-ids` усіх операцій адміністратора | додано скриптом в усі операції з відповіддю 403. Їх **18**, а не 17, як у рецензії: `createSupplier`, `getSupplier`, `updateSupplier`, `listParsers`, `createMaterial`, `getMaterial`, `updateMaterial`, `listMaterialLinks`, `listUnlinkedItems`, `listAttentionItems`, `putSupplierItemLink`, `deleteSupplierItemLink`, `getSettings`, `updateSettings`, `createRun`, `getRun`, `listRunLogEntries`, `createVolumeAcceptance` | `spec/openapi.yaml`; `docs/api/resources.md` (розділ 1) |
| РА-04 | 401 → 403 → 422 (шлях і запит) → 404 → 415 → 422 (тіло) → 409 → 500 у будь-який момент | `info.description`; таблиця кроків у розділі 0 `resources.md` (7 кроків і рядок 500) | `spec/openapi.yaml`; `docs/api/resources.md` |
| РА-05 | `page=abc` і `page=0` — лише `page_invalid`; `invalid_type` — для всіх параметрів, крім `page` | `info.description`, опис параметра `page`, `summary` прикладу `validation_failed_page_invalid` («0 або abc»); рядки `invalid_type` і `page_invalid` у таблиці кодів `errors` | `spec/openapi.yaml`; `docs/api/resources.md` (розділ 4) |
| РА-06 | лишити; пояснити, що OpenAPI не описує методів, яких немає | контракт не змінено; пояснення в розділі 0 і в спільних кодах розділу 3 | `docs/api/resources.md` |
| РА-07 | REQ-F-070 і BDD-070 також на `updateSupplier` | `x-req-ids`, `x-bdd` операції; рядок 7 таблиці операцій і рядок REQ-F-070 розділу 1 | `spec/openapi.yaml`; `docs/api/resources.md` |
| РА-08 | відступ затверджено; правило в розділ 0; глосарій не змінювати | правило «шлях колекції — за елементом, назва цілого — у тегах, `summary`, назвах схеми» з прикладами `/events` і `/material-comparisons`; `glossary.md` не змінено | `docs/api/resources.md` (розділ 0) |
| РА-09 | окрема схема для ціни > 0 і для суми, де 0 можливий; `parsed_items_count` ≥ 1; `Material` з `additionalProperties: false` | `Price` — шаблон без `0.00` і без провідних нулів; нова `Amount` для `difference_from_cheapest.amount`; `parsed_items_count` з `minimum: 1`; `Material.additionalProperties: false` (див. «Звірка з SRS» щодо обсягу `Price`) | `spec/openapi.yaml`; `docs/api/resources.md` (розділи 0, 2.1) |
| РА-10 | `Location` у всіх 201; `GET` для `link` не додавати | `Location` у 201 `createSession` (`/api/v1/sessions/current`), `createSupplier`, `createMaterial`, `putSupplierItemLink`; в описі заголовка прив'язки — чому `GET` немає. `createVolumeAcceptance` — без `Location` (рішення людини, див. питання вище) | `spec/openapi.yaml`; `docs/api/resources.md` (розділи 0, 3) |
| РА-11 | для `write_failed` `error_reason` — коротка українська фраза без внутрішніх подробиць | опис `error_reason` у `SupplierRunStatus`; примітка в 2.1 | `spec/openapi.yaml`; `docs/api/resources.md` |
| РА-12 | менеджер у `GET /materials` і `GET /suppliers` — лише `id`, `name`, `active`; дві схеми, `oneOf`, іменовані приклади для обох ролей | `SupplierForManager` без `last_update_date`; нова `MaterialForManager`; `MaterialPage.items` — `oneOf` (`Supplier` і `Material` обидві з `additionalProperties: false`, тож `oneOf` однозначний); приклади `admin`, `manager` в обох операціях (у `listMaterials` приклад `with_inactive` перейменовано на `admin`); описи операцій | `spec/openapi.yaml`; `docs/api/resources.md` (розділи 0, 2, 2.1, 2.2, 3, уточнення №14) |
| РА-13 | затверджено на гейті, нічого не міняти | не змінено | — |
| РА-14 | необов'язковий `active` (`true`/`false`) у `GET /materials` і `GET /suppliers`; без параметра — усі | `components/parameters/active` в обох операціях. Ці операції отримали власну відповідь 422 з прикладами `page_invalid` і нового `validation_failed_active_invalid_type`: прогін показав, що спільна `ValidationFailed` для `?active=yes` дає лише приклад `page_invalid` | `spec/openapi.yaml`; `docs/api/resources.md` (розділи 0, 1, 3) |
| РА-15 | сценарії: поріг 0.1, 0.3, 0.5, 50 і 50.1, 1.25; `period` відсутній; `kind_invalid`; `page_invalid`; `unknown_field`; `read_only_field`; `malformed_json`; `material_name_taken`; 403 на кожній операції адміністратора; 500 хоча б на одній | П-32…П-35 (поріг), Н-20, Н-21 (поріг), Н-22…Н-28, Н-29…Н-44 (403 на 16 операціях «адмін», яких не покривали Н-03 і Н-04), Н-45 (500). Понад перелік — П-36 (матеріали для менеджера, РА-12), П-37 (`active=true`, РА-14); у П-01, П-06, П-11, П-18 — перевірка `Location`, у П-05 — відсутність `last_update_date`. Ті самі ID в обох файлах (звірено скриптом: 82 = 82) | `docs/api/scenarios.md`; `tests/contract/scenarios.json` |
| РА-16 | прибрати застаріле обмеження 4 про П-01 | прибрано; на його місці — нові обмеження 4…6 (тіло не JSON, крок порогу, 500 на сервері) | `docs/api/scenarios.md` |

## Зміна скрипту прогону

Н-27 (`malformed_json`) mock не обслуговує: на тіло, що не є JSON, Prism 5.16.0 не відповідає
зовсім, і запит висить до тайм-ауту (перевірено `curl -m 10`, з `Prefer` і без). Щоб прогін не
висів і не падав на обмеженні mock, у `tests/contract/run_mock_scenarios.py` додано позначку
`mock.unsupported`: проти mock такий сценарій не надсилається і показується як `SKIP`, а підсумок
має третє число — `skipped`; проти сервера сценарій перевіряється як звичайно. Код виходу — 1 лише
за `FAIL`. Після правки — `ruff format` (1 файл переформатовано) і `ruff check`: без зауважень.

## Перевірки

- `npm run api:lint`: 0 помилок, 0 попереджень, код виходу 0.
- Скрипт звірки контракту: 500 — у 28 з 28 операцій; REQ-F-003/004/005 — у 18 з 18 операцій
  «адмін»; `Location` — у 4 з 5 відповідей 201 (крім `createVolumeAcceptance`); `multipleOf` немає.
- Mock (`npm run api:mock`, порт 4010, запущено заново після правок) і
  `python tests/contract/run_mock_scenarios.py`: `82 scenarios: 81 passed, 0 failed, 1 skipped`,
  код виходу 0. Пропущено Н-27 (обмеження mock). Після прогону свій процес Prism зупинено.

## Файли

Змінені: `spec/openapi.yaml`, `docs/api/resources.md`, `docs/api/scenarios.md`,
`docs/api/validation.md`, `docs/api/mock-run.md`, `tests/contract/scenarios.json`,
`tests/contract/run_mock_scenarios.py`. Новий: цей лог. В індекс нічого не додано, комітів немає.
`spec/srs.md`, `spec/glossary.md`, `/src` не змінено.
