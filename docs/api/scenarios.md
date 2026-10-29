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
| не відтворюється | mock такого запиту не обслуговує; скрипт проти mock його не надсилає і показує `SKIP` (позначка `unsupported` у `scenarios.json`), проти реального сервера — перевіряє як звичайно |

## Позитивні сценарії

Кожна з 28 операцій контракту має хоча б один позитивний сценарій; `listSuppliers`,
`putSupplierItemLink` і `createRun` — по два (дві ролі, два коди успіху), `updateSettings` — п'ять
(межові й проміжні значення порогу), `listMaterials` — три (дві ролі і відбір `active`).
Сценарії П-32…П-37 додано після REVISE на API-GATE (РА-15, РА-12, РА-14).

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
| П-32 | `updateSettings` | REQ-F-019 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"notification_threshold": 0.1}` | 200 | приклад за замовчуванням |
| П-33 | `updateSettings` | REQ-F-019 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"notification_threshold": 0.3}` | 200 | приклад за замовчуванням |
| П-34 | `updateSettings` | REQ-F-019 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"notification_threshold": 0.5}` | 200 | приклад за замовчуванням |
| П-35 | `updateSettings` | REQ-F-019 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"notification_threshold": 50}` | 200 | приклад за замовчуванням |
| П-36 | `listMaterials` | REQ-F-070, BDD-070 | `GET /materials` | `Cookie: spm_session=mock-manager`<br>`Prefer: example=manager` | — | 200; є `items.0.id`, `name`, `active`; немає `items.0.unit`, `items.0.linked_items_count` | `Prefer: example=…` |
| П-37 | `listMaterials` | REQ-F-040, REQ-F-049, REQ-F-070 | `GET /materials?active=true` | `Cookie: spm_session=mock-manager`<br>`Prefer: example=manager` | — | 200 | `Prefer: example=…` |

Після REVISE П-01, П-06, П-11 і П-18 перевіряють і заголовок `Location` (РА-10), а П-05 — що в
постачальника для менеджера немає й `last_update_date` (РА-12).

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
| Н-20 | `updateSettings` | REQ-F-019 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=422, example=validation_failed_threshold_out_of_range` | `{"notification_threshold": 50.1}` | 422 `validation_failed`; errors: `notification_threshold`/`notification_threshold_out_of_range` | валідація запиту Prism + `Prefer: code=422, example=…` |
| Н-21 | `updateSettings` | REQ-F-019 | `PATCH /settings` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=422, example=validation_failed_threshold_step` | `{"notification_threshold": 1.25}` | 422 `validation_failed`; errors: `notification_threshold`/`notification_threshold_out_of_range` | `Prefer: code=…, example=…` (крок перевіряє сервер, схема 1.25 пропускає) |
| Н-22 | `getMaterialPriceHistory` | REQ-F-040 | `GET /materials/1/price-history` | `Cookie: spm_session=mock-manager` | — | 422 `validation_failed`; errors: `period`/`required` | валідація запиту Prism → відповідь з контракту, перший приклад |
| Н-23 | `listEvents` | REQ-F-058 | `GET /events?kind=price_drop` | `Cookie: spm_session=mock-manager` | — | 422 `validation_failed`; errors: `kind`/`kind_invalid` | валідація запиту Prism → відповідь з контракту, перший приклад |
| Н-24 | `listSuppliers` | REQ-F-057 | `GET /suppliers?page=abc` | `Cookie: spm_session=mock-admin` | — | 422 `validation_failed`; errors: `page`/`page_invalid` | валідація запиту Prism → відповідь з контракту, перший приклад |
| Н-25 | `createMaterial` | REQ-F-008 | `POST /materials` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=422, example=validation_failed_unknown_field` | `{"name": "Кромка біла 2 мм", "unit": "п.м.", "active": true, "colour": "білий"}` | 422 `validation_failed`; errors: `colour`/`unknown_field` | валідація запиту Prism + `Prefer: code=422, example=…` |
| Н-26 | `updateSupplier` | REQ-F-007 | `PATCH /suppliers/1` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=422, example=validation_failed_read_only_field` | `{"last_update_date": "2026-10-05"}` | 422 `validation_failed`; errors: `last_update_date`/`read_only_field` | валідація запиту Prism + `Prefer: code=422, example=…` |
| Н-27 | `createMaterial` | REQ-NF-031 | `POST /materials` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json` | `{"name": ` (не JSON) | 422 `validation_failed`; errors: `null`/`malformed_json` | не відтворюється (обмеження 4) |
| Н-28 | `createMaterial` | REQ-F-008 | `POST /materials` | `Cookie: spm_session=mock-admin`<br>`Content-Type: application/json`<br>`Prefer: code=409` | `{"name": "лдсп білий 18 мм", "unit": "шт", "active": true}` | 409 `material_name_taken`; errors: `name`/`material_name_taken` | `Prefer: code=…` |
| Н-29 | `createSupplier` | REQ-F-003, REQ-F-005 | `POST /suppliers` | `Cookie: spm_session=mock-manager`<br>`Content-Type: application/json`<br>`Prefer: code=403` | `{"name": "Дельта", "catalog_url": "http://localhost:8001/e", "parser": "table_layout", "active": true}` | 403 `forbidden` | `Prefer: code=…` |
| Н-30 | `getSupplier` | REQ-F-003, REQ-F-005 | `GET /suppliers/1` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-31 | `updateSupplier` | REQ-F-003, REQ-F-005, REQ-F-070, BDD-070 | `PATCH /suppliers/1` | `Cookie: spm_session=mock-manager`<br>`Content-Type: application/json`<br>`Prefer: code=403` | `{"active": false}` | 403 `forbidden` | `Prefer: code=…` |
| Н-32 | `listParsers` | REQ-F-003, REQ-F-005 | `GET /parsers` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-33 | `createMaterial` | REQ-F-003, REQ-F-005 | `POST /materials` | `Cookie: spm_session=mock-manager`<br>`Content-Type: application/json`<br>`Prefer: code=403` | `{"name": "Кромка біла 2 мм", "unit": "п.м.", "active": true}` | 403 `forbidden` | `Prefer: code=…` |
| Н-34 | `getMaterial` | REQ-F-003, REQ-F-005 | `GET /materials/1` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-35 | `listMaterialLinks` | REQ-F-003, REQ-F-005 | `GET /materials/1/links` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-36 | `listUnlinkedItems` | REQ-F-003, REQ-F-005 | `GET /unlinked-items` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-37 | `listAttentionItems` | REQ-F-003, REQ-F-005 | `GET /attention-items` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-38 | `putSupplierItemLink` | REQ-F-003, REQ-F-005 | `PUT /supplier-items/29/link` | `Cookie: spm_session=mock-manager`<br>`Content-Type: application/json`<br>`Prefer: code=403` | `{"material_id": 1}` | 403 `forbidden` | `Prefer: code=…` |
| Н-39 | `deleteSupplierItemLink` | REQ-F-003, REQ-F-005 | `DELETE /supplier-items/21/link` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-40 | `getSettings` | REQ-F-003, REQ-F-005 | `GET /settings` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-41 | `createRun` | REQ-F-003, REQ-F-005, BDD-030 | `POST /runs` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-42 | `getRun` | REQ-F-003, REQ-F-005 | `GET /runs/42` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-43 | `listRunLogEntries` | REQ-F-003, REQ-F-005 | `GET /run-log-entries` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=403` | — | 403 `forbidden` | `Prefer: code=…` |
| Н-44 | `createVolumeAcceptance` | REQ-F-003, REQ-F-005 | `POST /volume-acceptances` | `Cookie: spm_session=mock-manager`<br>`Content-Type: application/json`<br>`Prefer: code=403` | `{"run_id": 41, "supplier_id": 3}` | 403 `forbidden` | `Prefer: code=…` |
| Н-45 | `listMaterialComparisons` | REQ-NF-018, REQ-NF-031 | `GET /material-comparisons` | `Cookie: spm_session=mock-manager`<br>`Prefer: code=500` | — | 500 `internal_error`; без `errors` | `Prefer: code=…` |

Н-20…Н-45 додано після REVISE на API-GATE (РА-15). З Н-03, Н-04 і Н-29…Н-44 403 перевірено на
кожній з 18 операцій «адмін»: на mock — що контракт описує 403 `forbidden` для цієї операції.

## Відомі обмеження mock

1. **404 на невідомій адресі і 405 на методі, якого адреса не має (Н-07, Н-08)**, Prism віддає у
   своєму форматі, а не в моделі помилок контракту. Проти mock скрипт перевіряє лише статус
   (позначка `prism_format` у `scenarios.json`); проти реального сервера — ще й `code`
   (`not_found`, `method_not_allowed`) і `Content-Type: application/problem+json`.
2. **Стан системи mock не моделює.** 403 для менеджера, 404 для неіснуючого ідентифікатора і всі 409
   mock відтворює лише через `Prefer`. Для реального сервера потрібні передумови: сесія менеджера
   (Н-03, Н-04), постачальник «Альфа» (Н-11), запуск, що триває (Н-09), матеріал з цінами (Н-10),
   позиції й матеріали з прикладів контракту (Н-12…Н-15), матеріал «ЛДСП Білий 18 мм» (Н-28),
   сесія менеджера (Н-29…Н-44). Заголовок `Prefer` реальний сервер ігнорує.
3. **Для некоректного запиту Prism бере перший приклад 422.** Н-17 збігається з першим прикладом
   `PATCH /settings` (поріг і час одночасно); Н-19 — з першим прикладом `GET /suppliers/{id}`. Для
   Н-18 потрібен `Prefer: code=422, example=validation_failed_catalog_url_invalid`.
4. **Тіло, що не є JSON (Н-27), mock не обслуговує.** На `POST /materials` з
   `Content-Type: application/json` і тілом `{"name": ` Prism 5.16.0 не відповідає зовсім:
   з'єднання висить до тайм-ауту клієнта, навіть із `Prefer: code=422`. Скрипт проти mock Н-27 не
   надсилає і показує `SKIP`; проти реального сервера перевіряє 422 `malformed_json`.
5. **Крок порогу mock не перевіряє.** Схема задає лише межі 0,1…50, тож 1.25 (Н-21) Prism
   пропускає, і 422 відтворюється лише через `Prefer`; кратність 0,1 перевіряє сервер (РА-01).
   0.3 (П-33), який до REVISE mock відхиляв через `multipleOf`, тепер проходить.
6. **500 (Н-45) mock віддає лише через `Prefer`.** Для реального сервера потрібен штучний збій
   (як у критерії REQ-NF-016); `Prefer` сервер ігнорує.
