# Сценарії перевірки контракту REST API

Сценарії для `spec/openapi.yaml` (Лаб. 4, крок 4). Ті самі сценарії з тими самими ID лежать у
`tests/contract/scenarios.json`; їх проганяє `tests/contract/run_mock_scenarios.py`. Результат
прогону проти mock — `docs/api/mock-run.md`.

## Як читати

- **Шлях** — без префікса `/api/v1`: Prism віддає шляхи контракту без базової адреси сервера. Проти
  реального сервера (Лаб. 5) той самий файл запускають з базовою адресою
  `http://localhost:8000/api/v1` і `--target server`.
- **Сесія.** `Cookie: spm_session=mock-admin` — сесія адміністратора, `mock-manager` — менеджера.
  Prism перевіряє лише наявність cookie (схема `cookieAuth`), роль не розрізняє. Для реального
  сервера значення cookie беруть із `POST /sessions` і підставляють у розділ `sessions` файлу
  `scenarios.json`.
- **`Content-Type: application/json`** скрипт додає сам до кожного запиту з тілом JSON.
- **Що перевіряється:** статус HTTP; `Content-Type` відповіді (`application/json` для успіху,
  `application/problem+json` для помилки); поле `code` у помилці; пари `field`/`code` в `errors`;
  обов'язкові поля відповіді (шлях через крапку, `items.0.id` — поле першого запису); поля, яких
  бути не повинно; обов'язкові заголовки (`Location`, `Set-Cookie`).

Як mock відтворює сценарій:

| Спосіб | Що робить Prism |
|---|---|
| приклад за замовчуванням | коректний запит → найменший код 2xx операції і її перший приклад |
| `Prefer: code=…` | відповідь із вказаним кодом і її першим прикладом |
| `Prefer: example=…` | приклад з указаною назвою |
| `Prefer: code=…, example=…` | вказаний код і приклад з указаною назвою (потрібен, коли в коду кілька прикладів) |
| перевірка безпеки Prism | без cookie `spm_session` Prism відповідає 401 і бере приклад 401 з контракту |
| валідація запиту Prism | запит не відповідає схемі (тип, межі, шаблон, `Content-Type`) → Prism бере відповідь 422 чи 415 з контракту і її **перший** приклад |
| валідація запиту Prism + `Prefer: code=422, example=…` | запит некоректний, але потрібен не перший приклад 422; без `code=422` Prism `Prefer: example=…` для некоректного запиту ігнорує |
| маршрутизатор Prism | невідома адреса (404) чи метод (405): Prism відповідає у своєму форматі (`type: https://stoplight.io/prism/errors#…`, без `code`), не в моделі помилок контракту |

## Позитивні сценарії

Кожна з 28 операцій контракту має хоча б один позитивний сценарій; `listSuppliers`,
`putSupplierItemLink` і `createRun` — по два (дві ролі, два коди успіху).

| ID | Операція | REQ / BDD | Запит | Заголовки | Тіло | Очікується | Як відтворює mock |
|---|---|---|---|---|---|---|---|
| П-01 | `createSession` | REQ-F-001, REQ-NF-031, BDD-065 | `POST /sessions` | `Content-Type: application/json` | `{"login": "Admin", "password": "correct-password"}` | 201; заголовок `Set-Cookie` | приклад за замовчуванням |
| П-02 | `getCurrentSession` | REQ-F-071 | `GET /sessions/current` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-03 | `deleteCurrentSession` | REQ-F-002 | `DELETE /sessions/current` | `Cookie: spm_session=mock-admin` | — | 204 | приклад за замовчуванням |
| П-04 | `listSuppliers` | REQ-F-007, REQ-F-057 | `GET /suppliers` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-05 | `listSuppliers` | REQ-F-070, BDD-070 | `GET /suppliers` | `Cookie: spm_session=mock-manager`<br>`Prefer: example=manager` | — | 200; немає `items.0.catalog_url`, `items.0.parser` | `Prefer: example=…` |
| П-06 | `createSupplier` | REQ-F-007 | `POST /suppliers` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"name": "Альфа", "catalog_url": "http://localhost:8001/a", "parser": "table_layout", "active": true}` | 201 | приклад за замовчуванням |
| П-07 | `getSupplier` | REQ-F-007 | `GET /suppliers/1` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-08 | `updateSupplier` | REQ-F-010, REQ-F-011, BDD-044 | `PATCH /suppliers/4` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"active": false}` | 200 | приклад за замовчуванням |
| П-09 | `listParsers` | REQ-F-007, REQ-NF-006 | `GET /parsers` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-10 | `listMaterials` | REQ-F-008, REQ-F-057, BDD-070 | `GET /materials?q=лдсп` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-11 | `createMaterial` | REQ-F-008 | `POST /materials` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"name": "ЛДСП Білий 18 мм", "unit": "шт", "active": true}` | 201 | приклад за замовчуванням |
| П-12 | `getMaterial` | REQ-F-008 | `GET /materials/1` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-13 | `updateMaterial` | REQ-F-049, BDD-034 | `PATCH /materials/2` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"active": false}` | 200 | приклад за замовчуванням |
| П-14 | `listMaterialLinks` | REQ-F-069, BDD-063 | `GET /materials/1/links` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-15 | `getMaterialPriceHistory` | REQ-F-040, BDD-036 | `GET /materials/1/price-history?period=last_7_days` | `Cookie: spm_session=mock-manager` | — | 200 | приклад за замовчуванням |
| П-16 | `listUnlinkedItems` | REQ-F-012, BDD-019 | `GET /unlinked-items` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-17 | `listAttentionItems` | REQ-F-017, REQ-F-068, BDD-028 | `GET /attention-items` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-18 | `putSupplierItemLink` | REQ-F-013, REQ-F-014, BDD-019 | `PUT /supplier-items/29/link` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=201` | `{"material_id": 1}` | 201 | `Prefer: code=…` |
| П-19 | `putSupplierItemLink` | REQ-F-015, REQ-F-069, BDD-063 | `PUT /supplier-items/21/link` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"material_id": 2}` | 200 | приклад за замовчуванням |
| П-20 | `deleteSupplierItemLink` | REQ-F-015, BDD-056 | `DELETE /supplier-items/21/link` | `Cookie: spm_session=mock-admin` | — | 204 | приклад за замовчуванням |
| П-21 | `listMaterialComparisons` | REQ-F-035, REQ-F-059, BDD-025 | `GET /material-comparisons` | `Cookie: spm_session=mock-manager` | — | 200 | приклад за замовчуванням |
| П-22 | `getMaterialComparison` | REQ-F-036, REQ-F-038, BDD-023 | `GET /material-comparisons/1` | `Cookie: spm_session=mock-manager` | — | 200 | приклад за замовчуванням |
| П-23 | `listEvents` | REQ-F-042, REQ-F-058, BDD-045 | `GET /events?material_id=1` | `Cookie: spm_session=mock-manager` | — | 200 | приклад за замовчуванням |
| П-24 | `listSupplierUpdateStatuses` | REQ-F-034, BDD-035 | `GET /supplier-update-statuses` | `Cookie: spm_session=mock-manager` | — | 200 | приклад за замовчуванням |
| П-25 | `getSettings` | REQ-F-019, REQ-F-043 | `GET /settings` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-26 | `updateSettings` | REQ-F-019, REQ-F-043, BDD-068 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"notification_threshold": 2}` | 200 | приклад за замовчуванням |
| П-27 | `createRun` | REQ-F-020, REQ-F-032, BDD-043 | `POST /runs` | `Cookie: spm_session=mock-admin`<br>`Prefer: code=202` | — | 202; заголовок `Location` | `Prefer: code=…` |
| П-28 | `createRun` | REQ-F-063 | `POST /runs` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-29 | `getRun` | REQ-F-032, REQ-F-033, BDD-069 | `GET /runs/42` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-30 | `listRunLogEntries` | REQ-F-033, REQ-F-057, BDD-001 | `GET /run-log-entries` | `Cookie: spm_session=mock-admin` | — | 200 | приклад за замовчуванням |
| П-31 | `createVolumeAcceptance` | REQ-F-031, BDD-007 | `POST /volume-acceptances` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"run_id": 41, "supplier_id": 3}` | 201 | приклад за замовчуванням |

## Негативні сценарії

| ID | Операція | REQ / BDD | Запит | Заголовки | Тіло | Очікується | Як відтворює mock |
|---|---|---|---|---|---|---|---|
| Н-01 | `listMaterialComparisons` | REQ-NF-031, REQ-NF-021, BDD-068 | `GET /material-comparisons` | — | — | 401 `unauthenticated` | перевірка безпеки Prism (немає cookie) → відповідь 401 з контракту |
| Н-02 | `createSession` | REQ-F-001 | `POST /sessions` | `Content-Type: application/json`<br>`Prefer: code=401` | `{"login": "admin", "password": "wrong-password"}` | 401 `invalid_credentials` | `Prefer: code=…` |
| Н-03 | `updateSettings` | REQ-F-005, REQ-NF-031, BDD-068 | `PATCH /settings` | `Cookie: spm_session=mock-manager`<br>`Content-Type: application/json`<br>`Prefer: code=403` | `{"notification_threshold": 2}` | 403 `forbidden` | `Prefer: code=…` |
| Н-04 | `updateMaterial` | REQ-F-005, REQ-F-070, BDD-070 | `PATCH /materials/1` | `Cookie: spm_session=mock-manager`<br>`Content-Type: application/json`<br>`Prefer: code=403` | `{"name": "ЛДСП Білий 18 мм (Egger)"}` | 403 `forbidden` | `Prefer: code=…` |
| Н-05 | `getSupplier` | REQ-NF-031 | `GET /suppliers/999` | `Cookie: spm_session=mock-admin`<br>`Prefer: code=404` | — | 404 `not_found` | `Prefer: code=…` |
| Н-06 | `deleteSupplierItemLink` | REQ-F-015 | `DELETE /supplier-items/29/link` | `Cookie: spm_session=mock-admin`<br>`Prefer: code=404` | — | 404 `not_found` | `Prefer: code=…` |
| Н-07 | — | REQ-NF-031 | `GET /no-such-resource` | `Cookie: spm_session=mock-admin` | — | 404 `not_found` | маршрутизатор Prism, власний формат помилки — перевіряється лише статус |
| Н-08 | — | REQ-F-010, REQ-NF-031 | `DELETE /suppliers/1` | `Cookie: spm_session=mock-admin` | — | 405 `method_not_allowed` | маршрутизатор Prism, власний формат помилки — перевіряється лише статус |
| Н-09 | `createRun` | REQ-F-021, BDD-008 | `POST /runs` | `Cookie: spm_session=mock-admin`<br>`Prefer: code=409` | — | 409 `run_in_progress` | `Prefer: code=…` |
| Н-10 | `updateMaterial` | REQ-F-009 | `PATCH /materials/1` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=409, example=unit_locked` | `{"unit": "уп"}` | 409 `unit_locked`; errors: `unit`/`unit_locked` | `Prefer: code=…, example=…` |
| Н-11 | `createSupplier` | REQ-F-007 | `POST /suppliers` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=409` | `{"name": "альфа", "catalog_url": "http://localhost:8001/a3", "parser": "table_layout", "active": true}` | 409 `supplier_name_taken`; errors: `name`/`supplier_name_taken` | `Prefer: code=…` |
| Н-12 | `putSupplierItemLink` | REQ-F-014, BDD-027 | `PUT /supplier-items/29/link` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=409, example=link_units_differ` | `{"material_id": 3}` | 409 `link_units_differ` | `Prefer: code=…, example=…` |
| Н-13 | `putSupplierItemLink` | REQ-F-048 | `PUT /supplier-items/12/link` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=409, example=material_supplier_already_linked` | `{"material_id": 1}` | 409 `material_supplier_already_linked` | `Prefer: code=…, example=…` |
| Н-14 | `putSupplierItemLink` | REQ-F-050, BDD-037 | `PUT /supplier-items/29/link` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=409, example=material_inactive` | `{"material_id": 2}` | 409 `material_inactive` | `Prefer: code=…, example=…` |
| Н-15 | `createVolumeAcceptance` | REQ-F-031 | `POST /volume-acceptances` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=409` | `{"run_id": 40, "supplier_id": 3}` | 409 `volume_acceptance_unavailable` | `Prefer: code=…` |
| Н-16 | `updateSettings` | REQ-NF-031 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: text/plain` | `notification_threshold=2` | 415 `unsupported_media_type` | валідація запиту Prism → відповідь з контракту, перший приклад |
| Н-17 | `updateSettings` | REQ-F-019 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"notification_threshold": 0.05, "update_time": "3:30"}` | 422 `validation_failed`; errors: `notification_threshold`/`notification_threshold_out_of_range`, `update_time`/`update_time_invalid` | валідація запиту Prism → відповідь з контракту, перший приклад |
| Н-18 | `createSupplier` | REQ-F-007 | `POST /suppliers` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=422, example=validation_failed_catalog_url_invalid` | `{"name": "Дельта", "catalog_url": "ftp://localhost/a", "parser": "table_layout", "active": true}` | 422 `validation_failed`; errors: `catalog_url`/`catalog_url_invalid` | валідація запиту Prism + `Prefer: code=422, example=…` |
| Н-19 | `getSupplier` | REQ-NF-031 | `GET /suppliers/abc` | `Cookie: spm_session=mock-admin` | — | 422 `validation_failed`; errors: `supplier_id`/`invalid_type` | валідація запиту Prism → відповідь з контракту, перший приклад |

## Відомі обмеження mock

1. **404 на невідомій адресі і 405 на методі, якого адреса не має (Н-07, Н-08)**, Prism віддає у
   своєму форматі, а не в моделі помилок контракту. Проти mock скрипт перевіряє лише статус
   (позначка `prism_format` у `scenarios.json`); проти реального сервера — ще й `code`
   (`not_found`, `method_not_allowed`) і `Content-Type: application/problem+json`.
2. **Стан системи mock не моделює.** 403 для менеджера, 404 для неіснуючого ідентифікатора і всі 409
   mock відтворює лише через `Prefer`. Для реального сервера потрібні передумови: сесія менеджера
   (Н-03, Н-04), постачальник «Альфа» (Н-11), запуск, що триває (Н-09), матеріал з цінами (Н-10),
   позиції й матеріали з прикладів контракту (Н-12…Н-15). Заголовок `Prefer` реальний сервер
   ігнорує.
3. **Для некоректного запиту Prism бере перший приклад 422.** Н-17 збігається з першим прикладом
   `PATCH /settings` (поріг і час одночасно); Н-19 — з першим прикладом `GET /suppliers/{id}`. Для
   Н-18 потрібен `Prefer: code=422, example=validation_failed_catalog_url_invalid`.
4. **П-01 (`POST /sessions`) mock не відтворює** — див. `docs/api/mock-run.md`: приклад заголовка
   `Set-Cookie` у контракті містить кирилицю (`<значення>`), і Prism відповідає 500.
