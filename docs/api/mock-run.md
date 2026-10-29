# Прогін сценаріїв проти mock-сервера

Лаб. 4, крок 4. Сценарії — `docs/api/scenarios.md`, `tests/contract/scenarios.json`.

**Інструменти:** `@stoplight/prism-cli` 5.16.0, Node.js 24.14.1, Python 3.14.3 (скрипт — лише
стандартна бібліотека, сумісний з Python 3.12).

Прогонів три: перший виявив дефект контракту (П-01), другий — після його виправлення, третій —
повторна перевірка після REVISE на API-GATE (розділ «Повторна перевірка після REVISE»).

## Команди

Однакові для обох прогонів:

```
npm run api:mock                                  # у фоні: prism mock -p 4010 spec/openapi.yaml
python tests/contract/run_mock_scenarios.py       # база http://127.0.0.1:4010, --target mock
```

## Підсумок

| Прогін | Дата | Контракт | Пройшли | Не пройшли | Код виходу |
|---|---|---|---|---|---|
| 1 | 2026-10-28, 18:34 (EET) | з правками кроку 4 (`docs/api/validation.md`) | 49 з 50 | П-01 | 1 |
| 2 | 2026-10-29, 13:07 (EET) | + приклад `Set-Cookie` в ASCII | 50 з 50 | — | 0 |
| 3 | 2026-10-29, 13:35 (EET) | після REVISE (РА-01…РА-16) | 81 з 82, 1 пропущено (Н-27) | — | 0 |

У прогонах 1 і 2 — 50 сценаріїв: 31 позитивний, 19 негативних. У прогоні 3 — 82: 37 позитивних,
45 негативних. Н-07 і Н-08 пройшли з перевіркою лише
статусу: 404 на невідомій адресі і 405 на методі, якого адреса не має, Prism віддає у своєму
форматі (`docs/api/scenarios.md`, «Відомі обмеження mock»).

## Прогін 1 — 2026-10-28: 49 з 50

Вивід скрипту: `50 scenarios: 49 passed, 1 failed`.

### Чому не пройшов П-01

`POST /sessions` з коректним тілом Prism відповів 500:

```
{"type":"TypeError","title":"Invalid character in header content [\"Set-Cookie\"]","status":500,"detail":""}
```

Причина — дефект контракту. Приклад заголовка відповіді 201 був
`Set-Cookie: spm_session=<значення>; SameSite=Lax` — з кирилицею. Значення заголовка HTTP може
містити лише символи ISO-8859-1, тож Node.js (на ньому працює Prism) такого значення не
відправляє. `Prefer: dynamic=true` не допоміг: Prism усе одно бере приклад заголовка. Лінтер
Redocly цього не ловить — він перевіряє приклад на відповідність схемі (`type: string`), а не на
допустимість у заголовку HTTP. Агент контракт сам не змінив; людина підтвердила дефект і вирішила
замінити приклад на ASCII.

### Результати

| ID | Запит | Очікується | Отримано | Результат | Примітка |
|---|---|---|---|---|---|
| П-01 | `POST /sessions` | 201 | 500 | ❌ FAIL | статус 500 замість 201 |
| П-02 | `GET /sessions/current` | 200 | 200 | ✅ PASS |  |
| П-03 | `DELETE /sessions/current` | 204 | 204 | ✅ PASS |  |
| П-04 | `GET /suppliers` | 200 | 200 | ✅ PASS |  |
| П-05 | `GET /suppliers` | 200 | 200 | ✅ PASS |  |
| П-06 | `POST /suppliers` | 201 | 201 | ✅ PASS |  |
| П-07 | `GET /suppliers/1` | 200 | 200 | ✅ PASS |  |
| П-08 | `PATCH /suppliers/4` | 200 | 200 | ✅ PASS |  |
| П-09 | `GET /parsers` | 200 | 200 | ✅ PASS |  |
| П-10 | `GET /materials?q=лдсп` | 200 | 200 | ✅ PASS |  |
| П-11 | `POST /materials` | 201 | 201 | ✅ PASS |  |
| П-12 | `GET /materials/1` | 200 | 200 | ✅ PASS |  |
| П-13 | `PATCH /materials/2` | 200 | 200 | ✅ PASS |  |
| П-14 | `GET /materials/1/links` | 200 | 200 | ✅ PASS |  |
| П-15 | `GET /materials/1/price-history?period=last_7_days` | 200 | 200 | ✅ PASS |  |
| П-16 | `GET /unlinked-items` | 200 | 200 | ✅ PASS |  |
| П-17 | `GET /attention-items` | 200 | 200 | ✅ PASS |  |
| П-18 | `PUT /supplier-items/29/link` | 201 | 201 | ✅ PASS |  |
| П-19 | `PUT /supplier-items/21/link` | 200 | 200 | ✅ PASS |  |
| П-20 | `DELETE /supplier-items/21/link` | 204 | 204 | ✅ PASS |  |
| П-21 | `GET /material-comparisons` | 200 | 200 | ✅ PASS |  |
| П-22 | `GET /material-comparisons/1` | 200 | 200 | ✅ PASS |  |
| П-23 | `GET /events?material_id=1` | 200 | 200 | ✅ PASS |  |
| П-24 | `GET /supplier-update-statuses` | 200 | 200 | ✅ PASS |  |
| П-25 | `GET /settings` | 200 | 200 | ✅ PASS |  |
| П-26 | `PATCH /settings` | 200 | 200 | ✅ PASS |  |
| П-27 | `POST /runs` | 202 | 202 | ✅ PASS |  |
| П-28 | `POST /runs` | 200 | 200 | ✅ PASS |  |
| П-29 | `GET /runs/42` | 200 | 200 | ✅ PASS |  |
| П-30 | `GET /run-log-entries` | 200 | 200 | ✅ PASS |  |
| П-31 | `POST /volume-acceptances` | 201 | 201 | ✅ PASS |  |
| Н-01 | `GET /material-comparisons` | 401 unauthenticated | 401 | ✅ PASS |  |
| Н-02 | `POST /sessions` | 401 invalid_credentials | 401 | ✅ PASS |  |
| Н-03 | `PATCH /settings` | 403 forbidden | 403 | ✅ PASS |  |
| Н-04 | `PATCH /materials/1` | 403 forbidden | 403 | ✅ PASS |  |
| Н-05 | `GET /suppliers/999` | 404 not_found | 404 | ✅ PASS |  |
| Н-06 | `DELETE /supplier-items/29/link` | 404 not_found | 404 | ✅ PASS |  |
| Н-07 | `GET /no-such-resource` | 404 not_found | 404 | ✅ PASS | лише статус (формат помилки Prism) |
| Н-08 | `DELETE /suppliers/1` | 405 method_not_allowed | 405 | ✅ PASS | лише статус (формат помилки Prism) |
| Н-09 | `POST /runs` | 409 run_in_progress | 409 | ✅ PASS |  |
| Н-10 | `PATCH /materials/1` | 409 unit_locked | 409 | ✅ PASS |  |
| Н-11 | `POST /suppliers` | 409 supplier_name_taken | 409 | ✅ PASS |  |
| Н-12 | `PUT /supplier-items/29/link` | 409 link_units_differ | 409 | ✅ PASS |  |
| Н-13 | `PUT /supplier-items/12/link` | 409 material_supplier_already_linked | 409 | ✅ PASS |  |
| Н-14 | `PUT /supplier-items/29/link` | 409 material_inactive | 409 | ✅ PASS |  |
| Н-15 | `POST /volume-acceptances` | 409 volume_acceptance_unavailable | 409 | ✅ PASS |  |
| Н-16 | `PATCH /settings` | 415 unsupported_media_type | 415 | ✅ PASS |  |
| Н-17 | `PATCH /settings` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-18 | `POST /suppliers` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-19 | `GET /suppliers/abc` | 422 validation_failed | 422 | ✅ PASS |  |

## Прогін 2 — 2026-10-29: 50 з 50

Після виправлення в `spec/openapi.yaml` лише одного рядка — приклад заголовка `Set-Cookie` у
відповіді 201 `POST /sessions`:

```
-              example: spm_session=<значення>; SameSite=Lax
+              example: spm_session=3f9c2a7e; SameSite=Lax
```

`npm run api:lint` після виправлення — 0 помилок, 0 попереджень. Prism на `POST /sessions`
відповідає 201 з `Set-Cookie: spm_session=3f9c2a7e; SameSite=Lax` і тілом
`{"account":{"login":"admin","role":"admin"}}`.

Вивід скрипту: `50 scenarios: 50 passed, 0 failed`.

### Результати

| ID | Запит | Очікується | Отримано | Результат | Примітка |
|---|---|---|---|---|---|
| П-01 | `POST /sessions` | 201 | 201 | ✅ PASS |  |
| П-02 | `GET /sessions/current` | 200 | 200 | ✅ PASS |  |
| П-03 | `DELETE /sessions/current` | 204 | 204 | ✅ PASS |  |
| П-04 | `GET /suppliers` | 200 | 200 | ✅ PASS |  |
| П-05 | `GET /suppliers` | 200 | 200 | ✅ PASS |  |
| П-06 | `POST /suppliers` | 201 | 201 | ✅ PASS |  |
| П-07 | `GET /suppliers/1` | 200 | 200 | ✅ PASS |  |
| П-08 | `PATCH /suppliers/4` | 200 | 200 | ✅ PASS |  |
| П-09 | `GET /parsers` | 200 | 200 | ✅ PASS |  |
| П-10 | `GET /materials?q=лдсп` | 200 | 200 | ✅ PASS |  |
| П-11 | `POST /materials` | 201 | 201 | ✅ PASS |  |
| П-12 | `GET /materials/1` | 200 | 200 | ✅ PASS |  |
| П-13 | `PATCH /materials/2` | 200 | 200 | ✅ PASS |  |
| П-14 | `GET /materials/1/links` | 200 | 200 | ✅ PASS |  |
| П-15 | `GET /materials/1/price-history?period=last_7_days` | 200 | 200 | ✅ PASS |  |
| П-16 | `GET /unlinked-items` | 200 | 200 | ✅ PASS |  |
| П-17 | `GET /attention-items` | 200 | 200 | ✅ PASS |  |
| П-18 | `PUT /supplier-items/29/link` | 201 | 201 | ✅ PASS |  |
| П-19 | `PUT /supplier-items/21/link` | 200 | 200 | ✅ PASS |  |
| П-20 | `DELETE /supplier-items/21/link` | 204 | 204 | ✅ PASS |  |
| П-21 | `GET /material-comparisons` | 200 | 200 | ✅ PASS |  |
| П-22 | `GET /material-comparisons/1` | 200 | 200 | ✅ PASS |  |
| П-23 | `GET /events?material_id=1` | 200 | 200 | ✅ PASS |  |
| П-24 | `GET /supplier-update-statuses` | 200 | 200 | ✅ PASS |  |
| П-25 | `GET /settings` | 200 | 200 | ✅ PASS |  |
| П-26 | `PATCH /settings` | 200 | 200 | ✅ PASS |  |
| П-27 | `POST /runs` | 202 | 202 | ✅ PASS |  |
| П-28 | `POST /runs` | 200 | 200 | ✅ PASS |  |
| П-29 | `GET /runs/42` | 200 | 200 | ✅ PASS |  |
| П-30 | `GET /run-log-entries` | 200 | 200 | ✅ PASS |  |
| П-31 | `POST /volume-acceptances` | 201 | 201 | ✅ PASS |  |
| Н-01 | `GET /material-comparisons` | 401 unauthenticated | 401 | ✅ PASS |  |
| Н-02 | `POST /sessions` | 401 invalid_credentials | 401 | ✅ PASS |  |
| Н-03 | `PATCH /settings` | 403 forbidden | 403 | ✅ PASS |  |
| Н-04 | `PATCH /materials/1` | 403 forbidden | 403 | ✅ PASS |  |
| Н-05 | `GET /suppliers/999` | 404 not_found | 404 | ✅ PASS |  |
| Н-06 | `DELETE /supplier-items/29/link` | 404 not_found | 404 | ✅ PASS |  |
| Н-07 | `GET /no-such-resource` | 404 not_found | 404 | ✅ PASS | лише статус (формат помилки Prism) |
| Н-08 | `DELETE /suppliers/1` | 405 method_not_allowed | 405 | ✅ PASS | лише статус (формат помилки Prism) |
| Н-09 | `POST /runs` | 409 run_in_progress | 409 | ✅ PASS |  |
| Н-10 | `PATCH /materials/1` | 409 unit_locked | 409 | ✅ PASS |  |
| Н-11 | `POST /suppliers` | 409 supplier_name_taken | 409 | ✅ PASS |  |
| Н-12 | `PUT /supplier-items/29/link` | 409 link_units_differ | 409 | ✅ PASS |  |
| Н-13 | `PUT /supplier-items/12/link` | 409 material_supplier_already_linked | 409 | ✅ PASS |  |
| Н-14 | `PUT /supplier-items/29/link` | 409 material_inactive | 409 | ✅ PASS |  |
| Н-15 | `POST /volume-acceptances` | 409 volume_acceptance_unavailable | 409 | ✅ PASS |  |
| Н-16 | `PATCH /settings` | 415 unsupported_media_type | 415 | ✅ PASS |  |
| Н-17 | `PATCH /settings` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-18 | `POST /suppliers` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-19 | `GET /suppliers/abc` | 422 validation_failed | 422 | ✅ PASS |  |

## Повторна перевірка після REVISE

### Прогін 3 — 2026-10-29: 81 з 82, 1 пропущено

Контракт — після виправлень за зауваженнями РА-01…РА-16 (`docs/api/validation.md`, розділ
«Повторна перевірка після REVISE»); `npm run api:lint` — 0 помилок, 0 попереджень. Сценарії —
82: до 50 попередніх додано П-32…П-37 і Н-20…Н-45 (РА-15, а також РА-12 і РА-14); у П-01, П-06,
П-11, П-18 додано перевірку `Location` (РА-10), у П-05 — відсутність `last_update_date` (РА-12).

Команди ті самі; mock запущено заново, щоб він прочитав виправлений контракт:

```
npm run api:mock                                  # у фоні: prism mock -p 4010 spec/openapi.yaml
python tests/contract/run_mock_scenarios.py       # база http://127.0.0.1:4010, --target mock
```

Prism зареєстрував 28 операцій. Вивід скрипту: `82 scenarios: 81 passed, 0 failed, 1 skipped`,
код виходу 0.

**Пропущено — Н-27 (`malformed_json`).** Перед прогоном перевірено вручну: на `POST /materials` з
`Content-Type: application/json` і тілом `{"name": ` Prism 5.16.0 не відповідає зовсім (`curl -m
10` — тайм-аут без відповіді), так само з `Prefer: code=422, example=validation_failed_malformed_json`
і з тілом `not json`. Після такого запиту mock далі обслуговує інші запити. Це обмеження mock, а
не контракту: відповідь 422 з прикладом `validation_failed_malformed_json` у контракті є. Щоб
сценарій не висів до тайм-ауту, у `scenarios.json` він має позначку `unsupported`, і скрипт проти
mock його не надсилає (`SKIP`); проти реального сервера Н-27 перевіряється як звичайно.

Що показує прогін щодо зауважень:
- РА-01: поріг 0.1, 0.3, 0.5, 50 (П-32…П-35) — 200; до REVISE 0.3 mock відхиляв з
  `must be multiple of 0.1`. 50.1 (Н-20) відхиляє схема; 1.25 (Н-21) схема пропускає — крок
  перевіряє сервер, тож на mock 422 лише через `Prefer`.
- РА-02: Н-45 — 500 `internal_error` у моделі помилок, `application/problem+json`, без `errors`.
- РА-03: 403 `forbidden` відтворюється на кожній з 18 операцій «адмін» (Н-03, Н-04, Н-29…Н-44).
- РА-05: `page=abc` (Н-24) — `page_invalid`.
- РА-10: `Location` є в 201 `POST /sessions`, `POST /suppliers`, `POST /materials`,
  `PUT …/link`.
- РА-12: менеджер отримує постачальника і матеріал без полів, крім `id`, `name`, `active`
  (П-05, П-36).

### Результати

| ID | Запит | Очікується | Отримано | Результат | Примітка |
|---|---|---|---|---|---|
| П-01 | `POST /sessions` | 201 | 201 | ✅ PASS |  |
| П-02 | `GET /sessions/current` | 200 | 200 | ✅ PASS |  |
| П-03 | `DELETE /sessions/current` | 204 | 204 | ✅ PASS |  |
| П-04 | `GET /suppliers` | 200 | 200 | ✅ PASS |  |
| П-05 | `GET /suppliers` | 200 | 200 | ✅ PASS |  |
| П-06 | `POST /suppliers` | 201 | 201 | ✅ PASS |  |
| П-07 | `GET /suppliers/1` | 200 | 200 | ✅ PASS |  |
| П-08 | `PATCH /suppliers/4` | 200 | 200 | ✅ PASS |  |
| П-09 | `GET /parsers` | 200 | 200 | ✅ PASS |  |
| П-10 | `GET /materials?q=лдсп` | 200 | 200 | ✅ PASS |  |
| П-11 | `POST /materials` | 201 | 201 | ✅ PASS |  |
| П-12 | `GET /materials/1` | 200 | 200 | ✅ PASS |  |
| П-13 | `PATCH /materials/2` | 200 | 200 | ✅ PASS |  |
| П-14 | `GET /materials/1/links` | 200 | 200 | ✅ PASS |  |
| П-15 | `GET /materials/1/price-history?period=last_7_days` | 200 | 200 | ✅ PASS |  |
| П-16 | `GET /unlinked-items` | 200 | 200 | ✅ PASS |  |
| П-17 | `GET /attention-items` | 200 | 200 | ✅ PASS |  |
| П-18 | `PUT /supplier-items/29/link` | 201 | 201 | ✅ PASS |  |
| П-19 | `PUT /supplier-items/21/link` | 200 | 200 | ✅ PASS |  |
| П-20 | `DELETE /supplier-items/21/link` | 204 | 204 | ✅ PASS |  |
| П-21 | `GET /material-comparisons` | 200 | 200 | ✅ PASS |  |
| П-22 | `GET /material-comparisons/1` | 200 | 200 | ✅ PASS |  |
| П-23 | `GET /events?material_id=1` | 200 | 200 | ✅ PASS |  |
| П-24 | `GET /supplier-update-statuses` | 200 | 200 | ✅ PASS |  |
| П-25 | `GET /settings` | 200 | 200 | ✅ PASS |  |
| П-26 | `PATCH /settings` | 200 | 200 | ✅ PASS |  |
| П-27 | `POST /runs` | 202 | 202 | ✅ PASS |  |
| П-28 | `POST /runs` | 200 | 200 | ✅ PASS |  |
| П-29 | `GET /runs/42` | 200 | 200 | ✅ PASS |  |
| П-30 | `GET /run-log-entries` | 200 | 200 | ✅ PASS |  |
| П-31 | `POST /volume-acceptances` | 201 | 201 | ✅ PASS |  |
| П-32 | `PATCH /settings` | 200 | 200 | ✅ PASS |  |
| П-33 | `PATCH /settings` | 200 | 200 | ✅ PASS |  |
| П-34 | `PATCH /settings` | 200 | 200 | ✅ PASS |  |
| П-35 | `PATCH /settings` | 200 | 200 | ✅ PASS |  |
| П-36 | `GET /materials` | 200 | 200 | ✅ PASS |  |
| П-37 | `GET /materials?active=true` | 200 | 200 | ✅ PASS |  |
| Н-01 | `GET /material-comparisons` | 401 unauthenticated | 401 | ✅ PASS |  |
| Н-02 | `POST /sessions` | 401 invalid_credentials | 401 | ✅ PASS |  |
| Н-03 | `PATCH /settings` | 403 forbidden | 403 | ✅ PASS |  |
| Н-04 | `PATCH /materials/1` | 403 forbidden | 403 | ✅ PASS |  |
| Н-05 | `GET /suppliers/999` | 404 not_found | 404 | ✅ PASS |  |
| Н-06 | `DELETE /supplier-items/29/link` | 404 not_found | 404 | ✅ PASS |  |
| Н-07 | `GET /no-such-resource` | 404 not_found | 404 | ✅ PASS | лише статус (формат помилки Prism) |
| Н-08 | `DELETE /suppliers/1` | 405 method_not_allowed | 405 | ✅ PASS | лише статус (формат помилки Prism) |
| Н-09 | `POST /runs` | 409 run_in_progress | 409 | ✅ PASS |  |
| Н-10 | `PATCH /materials/1` | 409 unit_locked | 409 | ✅ PASS |  |
| Н-11 | `POST /suppliers` | 409 supplier_name_taken | 409 | ✅ PASS |  |
| Н-12 | `PUT /supplier-items/29/link` | 409 link_units_differ | 409 | ✅ PASS |  |
| Н-13 | `PUT /supplier-items/12/link` | 409 material_supplier_already_linked | 409 | ✅ PASS |  |
| Н-14 | `PUT /supplier-items/29/link` | 409 material_inactive | 409 | ✅ PASS |  |
| Н-15 | `POST /volume-acceptances` | 409 volume_acceptance_unavailable | 409 | ✅ PASS |  |
| Н-16 | `PATCH /settings` | 415 unsupported_media_type | 415 | ✅ PASS |  |
| Н-17 | `PATCH /settings` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-18 | `POST /suppliers` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-19 | `GET /suppliers/abc` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-20 | `PATCH /settings` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-21 | `PATCH /settings` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-22 | `GET /materials/1/price-history` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-23 | `GET /events?kind=price_drop` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-24 | `GET /suppliers?page=abc` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-25 | `POST /materials` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-26 | `PATCH /suppliers/1` | 422 validation_failed | 422 | ✅ PASS |  |
| Н-27 | `POST /materials` | 422 validation_failed | — | ⏭️ SKIP | mock не відповідає на тіло, що не є JSON (обмеження 4 `docs/api/scenarios.md`) |
| Н-28 | `POST /materials` | 409 material_name_taken | 409 | ✅ PASS |  |
| Н-29 | `POST /suppliers` | 403 forbidden | 403 | ✅ PASS |  |
| Н-30 | `GET /suppliers/1` | 403 forbidden | 403 | ✅ PASS |  |
| Н-31 | `PATCH /suppliers/1` | 403 forbidden | 403 | ✅ PASS |  |
| Н-32 | `GET /parsers` | 403 forbidden | 403 | ✅ PASS |  |
| Н-33 | `POST /materials` | 403 forbidden | 403 | ✅ PASS |  |
| Н-34 | `GET /materials/1` | 403 forbidden | 403 | ✅ PASS |  |
| Н-35 | `GET /materials/1/links` | 403 forbidden | 403 | ✅ PASS |  |
| Н-36 | `GET /unlinked-items` | 403 forbidden | 403 | ✅ PASS |  |
| Н-37 | `GET /attention-items` | 403 forbidden | 403 | ✅ PASS |  |
| Н-38 | `PUT /supplier-items/29/link` | 403 forbidden | 403 | ✅ PASS |  |
| Н-39 | `DELETE /supplier-items/21/link` | 403 forbidden | 403 | ✅ PASS |  |
| Н-40 | `GET /settings` | 403 forbidden | 403 | ✅ PASS |  |
| Н-41 | `POST /runs` | 403 forbidden | 403 | ✅ PASS |  |
| Н-42 | `GET /runs/42` | 403 forbidden | 403 | ✅ PASS |  |
| Н-43 | `GET /run-log-entries` | 403 forbidden | 403 | ✅ PASS |  |
| Н-44 | `POST /volume-acceptances` | 403 forbidden | 403 | ✅ PASS |  |
| Н-45 | `GET /material-comparisons` | 500 internal_error | 500 | ✅ PASS |  |
