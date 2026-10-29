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
