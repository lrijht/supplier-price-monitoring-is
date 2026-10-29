# Автоматична валідація контракту REST API

Перевірка `spec/openapi.yaml` лінтером Redocly (Лаб. 4, крок 4): 2026-10-28 і повторно
2026-10-29 після виправлення прикладу `Set-Cookie`.

## Інструменти

| Інструмент | Версія | Звідки |
|---|---|---|
| `@redocly/cli` | 2.72.0 | `devDependencies` у `package.json`, точна версія; `package-lock.json` у репозиторії |
| `@stoplight/prism-cli` | 5.16.0 | те саме |
| Node.js | 24.14.1 | локально |
| npm | 11.11.0 | локально |

`npm install` попередив: `@stoplight/prism-http-server@5.16.0` вимагає Node.js ≥ 24.18.0
(`EBADENGINE`). Встановлення пройшло, і mock на 24.14.1 працював без помилок, але для Лаб. 5 варто
оновити Node.js до 24.18 чи новішої.

## Налаштування лінтера

`redocly.yaml`: набір правил `recommended`, вимкнено два правила:

| Правило | Чому вимкнено |
|---|---|
| `info-license` | навчальний репозиторій без ліцензії; ліцензувати в контракті нічого |
| `no-server-example.com` | єдиний сервер — локальне розгортання `http://localhost:8000/api/v1` (REQ-NF-014), а правило вважає `localhost` прикладом-заглушкою |

## Команда

```
npm run api:lint
```

що виконує `redocly lint spec/openapi.yaml`.

## Результат до правок контракту

0 помилок, 2 попередження `no-unused-components`: відповіді `components/responses/MethodNotAllowed`
і `components/responses/Conflict` ніде не використано.

## Правки контракту

- Прибрано відповіді `MethodNotAllowed` і `Conflict`. Після цього лінтер знайшов невикористаний
  приклад `components/examples/method_not_allowed` — його теж прибрано, а тіло відповіді 405
  перенесено прикладом в `info.description`, розділ «Відповідь 405».
- Ідентифікатор у шляху, що не є цілим числом (`/suppliers/abc`), — 422 `validation_failed` з
  `errors[].code: invalid_type` (як у розділі 4 `docs/api/resources.md`). Відповідь 422 додано
  операціям `getSupplier`, `getMaterial`, `deleteSupplierItemLink`, `getMaterialComparison`,
  `getRun`; операціям з 422 (`updateSupplier`, `updateMaterial`, `listMaterialLinks`,
  `getMaterialPriceHistory`, `putSupplierItemLink`) додано приклад `validation_failed_invalid_type`.
  Нові приклади: `validation_failed_supplier_id_invalid_type`,
  `validation_failed_material_id_invalid_type`, `validation_failed_supplier_item_id_invalid_type`,
  `validation_failed_run_id_invalid_type`.

Після цих правок (2026-10-28) — 0 помилок, 0 попереджень.

## Виправлення після першого прогону mock

Перший прогін сценаріїв (`docs/api/mock-run.md`) виявив дефект, якого лінтер не ловить: приклад
заголовка `Set-Cookie` у відповіді 201 `POST /sessions` був `spm_session=<значення>; SameSite=Lax`.
Кирилиця в значенні заголовка HTTP недопустима (лише ISO-8859-1), і Prism відповідав 500. Лінтер
перевіряє приклади лише на відповідність схемі (`type: string`), тому дефект пропустив.

За рішенням людини приклад замінено на ASCII — `spm_session=3f9c2a7e; SameSite=Lax`. Більше в
контракті нічого не змінено.

## Результат — 2026-10-29

`npm run api:lint` після виправлення: 0 помилок, 0 попереджень. Вивід:

```
> api:lint
> redocly lint spec/openapi.yaml

validating spec\openapi.yaml...
spec\openapi.yaml: validated in 141ms

Woohoo! Your API description is valid. 🎉
```

Код виходу — 0. Повторний прогін сценаріїв проти mock — 50 з 50 (`docs/api/mock-run.md`,
прогін 2).

## Повторна перевірка після REVISE

**Дата:** 2026-10-29. Перша перевірка на API-GATE дала REVISE (`logs/2026-10-29-api-review.md`,
РА-01…РА-16); рішення людини внесено в контракт без зміни SRS 1.9. Перелік правок —
`docs/api/resources.md`, розділ 6.1, і `logs/2026-10-29-api-revise.md`. Інструменти й налаштування
лінтера ті самі (`redocly.yaml` не змінювався).

### Що змінено в контракті

- РА-01: з `Settings` і `SettingsUpdate` прибрано `multipleOf: 0.1`; межі `minimum: 0.1`,
  `maximum: 50` лишилися; крок перевіряє сервер (опис поля), приклад 422 для 1.25 —
  `validation_failed_threshold_step`.
- РА-02: відповідь `components/responses/InternalServerError` (500, `internal_error`) у всіх 28
  операціях; `ProblemCode` і `Problem.title` доповнено; приклад `internal_error`.
- РА-03, РА-07: REQ-F-003, REQ-F-004, REQ-F-005 у `x-req-ids` 18 операцій «адмін»; REQ-F-070 і
  BDD-070 — на `updateSupplier`.
- РА-04, РА-05: порядок перевірок і правило `page_invalid` в `info.description` і описі `page`.
- РА-09: схеми `Price` (більше 0) і `Amount` (не менше 0, для `difference_from_cheapest.amount`);
  `parsed_items_count` з `minimum: 1`; `Material` з `additionalProperties: false`.
- РА-10: заголовок `Location` у відповідях 201 `createSession`, `createSupplier`,
  `createMaterial`, `putSupplierItemLink`; `createVolumeAcceptance` — без нього (рішення людини).
- РА-11: опис `error_reason` для `write_failed`.
- РА-12: `SupplierForManager` — лише `id`, `name`, `active`; нова `MaterialForManager`;
  `MaterialPage.items` — `oneOf`; приклади `admin` і `manager` у `listSuppliers`, `listMaterials`.
- РА-14: параметр `components/parameters/active` у `listSuppliers` і `listMaterials`; ці операції
  мають власну відповідь 422 з прикладами `page_invalid` і `invalid_type` для `active` (приклад
  `validation_failed_active_invalid_type`).

### Результат

`npm run api:lint`: 0 помилок, 0 попереджень, код виходу 0. Вивід:

```
> api:lint
> redocly lint spec/openapi.yaml

validating spec\openapi.yaml...
spec\openapi.yaml: validated in 137ms

Woohoo! Your API description is valid. 🎉
```

Додатково скриптом перевірено (лінтер цього не ловить): 500 є в усіх 28 операціях; REQ-F-003,
REQ-F-004, REQ-F-005 є в `x-req-ids` усіх 18 операцій з відповіддю 403; `Location` є в 4 з 5
відповідей 201 (крім `createVolumeAcceptance`); `multipleOf` у схемах немає. Прогін сценаріїв —
`docs/api/mock-run.md`, прогін 3.
