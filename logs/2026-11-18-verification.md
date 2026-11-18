# 2026-11-18 — Незалежна верифікація реалізації (лаба 5, крок 7; T-47, T-49)

- Агент: claude-code (Opus 5.5), роль — сторонній рецензент: тестів і коду системи не писав.
- Гілка: `agent/verification` від `main` (`d6956ab`).
- Еталон: `spec/srs.md` (SRS 1.11: 72 REQ-F, 33 REQ-NF, 72 BDD, 16 UC), `spec/openapi.yaml`
  (29 операцій), `spec/addendum-A06.md` (REQ-F-072, BDD-072, операція `exportMaterialComparisons`).
- Код і тести системи не змінювались. Повний pytest не запускався (902 passed, покриття 97 % —
  `logs/2026-11-18-a06-feature.md`); запускались лише `tests/test_traceability.py` (4 passed) і
  `ruff format` / `ruff check` змінених файлів `tests/` (без зауважень).

## Як перевіряли

1. Трасування — скриптом поза репозиторієм (скретчпад сесії): ID вимог і BDD у коментарях,
   докстрінгах і назвах тестів (`tests/**/test_*.py`, `tests/contract/scenarios.json`), ID вимог у
   `src/spm` (зокрема шаблонах) і `simulator/`; для BDD — блок коментарів безпосередньо над
   тестовою функцією або її докстрінг. Операції — маршрути `@router.<метод>("<адреса>")` у
   `src/spm/api/routes.py`, виклики адрес у тестах і поле `operation` у `scenarios.json`.
2. Вибіркова перевірка критеріїв — 21 вимога з найвищою ціною помилки: критерій прийняття SRS і BDD
   прочитано повністю й звірено з асертами тестів. Частину читання виконали три субагенти-рецензенти
   паралельно; кожну знахідку «частково» агент перевірив сам за кодом тестів, одну знахідку
   субагента відхилив (див. нижче, REQ-F-013).
3. Правило залежностей — AST-розбір імпортів `src/spm` проти `docs/architecture.md`, розд. 5.
4. REQ-NF-012 і REQ-NF-023 — за історією git; адреси реальних сайтів — `git grep` по `src`,
   `simulator`, `tests`.

## 1. Трасування

### 1.1. Вимоги → тести і код

Повний перелік — у колонках «Тест», «Код», «Документація» `spec/traceability.md` (згенеровано, див.
розд. 4). Підсумок:

| Що | Результат |
|---|---|
| REQ-F з тестом | 72 з 72 |
| REQ-NF з автоматичним тестом | 27 з 33 |
| REQ з кодом, що цитує ID | 86 з 105 |
| REQ з кодом, знайденим за поведінкою (ID у коді немає) | 10: REQ-F-004, REQ-F-013, REQ-F-025, REQ-F-027, REQ-F-053, REQ-F-071, REQ-NF-003, REQ-NF-019; REQ-NF-011 і REQ-NF-025 — `pyproject.toml` |

Код, знайдений за поведінкою (перевірено за джерелом):

| REQ | Модулі | Доказ |
|---|---|---|
| REQ-F-004 | `spm/api/requests.py`, `spm/auth/service.py`, `spm/web/routes.py` | `require_admin`, `Account.is_admin`, `admin_screen` |
| REQ-F-013 | `spm/services/directories.py`, `spm/storage/schema.py` | `link_item`, `_check_link`; одна колонка `supplier_items.material_id` |
| REQ-F-025 | `spm/update/runner.py`, `spm/update/fetch.py`, `spm/update/parsers.py` | `_execute` → `fetch_page` → `read_page(supplier.parser, …)` |
| REQ-F-027 | `spm/update/parsers.py`, `spm/storage/updates.py` | `parse_price` / `read_price` без перерахунків; `put_daily_price` |
| REQ-F-053 | `spm/update/runner.py`, `spm/storage/updates.py` | `_price_event` порівнює з `feed_base`; повторна дата видаляє лише ціну дня |
| REQ-F-071 | `spm/api/routes.py` | `get_current_session` → `{"account": {"login", "role"}}` |
| REQ-NF-003 | `spm/web/routes.py`, `spm/web/templates/base.html` | `user_screen` (5 екранів), `admin_screen` (6), меню під `account.is_admin` |
| REQ-NF-019 | `spm/storage/updates.py`, `spm/services/runs.py` | для `run_log_entries` лише вставлення і читання; маршруту видалення немає |

Вимоги без автоматичного тесту:

| REQ | Причина | Оцінка |
|---|---|---|
| REQ-NF-010 | ціль проєктування без приймання (критерій «Не приймається») | очікувано |
| REQ-NF-012 | правило розробки, перевіряється історією git | виконано (розд. 3.2) |
| REQ-NF-023 | правило розробки, перевіряється історією git | виконано (розд. 3.2) |
| REQ-NF-002 | критерій — ручний протокол у Chrome і Firefox (T-48) | **протоколу немає** — Р-02 |
| REQ-NF-008 | критерій вимагає виміру тривалості запуску на імітаторі (T-45) | **тесту і протоколу немає** — Р-01 |
| REQ-NF-009 | критерій вимагає окремого тесту швидкодії з міткою pytest (T-45) | **тесту немає** — Р-01 |

### 1.2. BDD → тести

Усі 72 сценарії мають щонайменше одну тестову функцію, що цитує BDD безпосередньо (над функцією,
у докстрінгу або в назві). Колонка «К-сть» — кількість таких функцій; показано до трьох.

| BDD | К-сть | Тести |
|---|---|---|
| BDD-001 | 2 | `test_scheduler::test_scheduled_run_at_0330`, `test_update_run::test_each_active_supplier_fetched_once_and_parsed` |
| BDD-002 | 2 | `test_simulator::test_mode_unavailable`, `test_update_run::test_unavailable_page` |
| BDD-003 | 3 | `test_action_log_b2::test_timeout_in_technical_log`, `test_simulator::test_mode_slow_times_out_quickly`, `test_update_run::test_slow_page_times_out` |
| BDD-004 | 3 | `test_screens_roles::test_admin_opens_all_11_screens`, `test_screens_roles::test_all_screens_open_after_failed_run`, `test_screens_updates::test_screens_work_during_and_after_failed_run` |
| BDD-005 | 2 | `test_feed_assortment::test_no_disappeared_in_partial_run`, `test_simulator::test_mode_reduced_assortment` |
| BDD-006 | 1 | `test_update_statuses::test_incomplete_crawl_threshold` |
| BDD-007 | 3 | `test_feed_assortment::test_disappeared_after_accepting_volume`, `test_screens_updates::test_accept_button`, `test_update_statuses::test_accept_new_volume` |
| BDD-008 | 2 | `test_api_runs::test_manual_run_while_running`, `test_screens_updates::test_manual_run_button_while_running` |
| BDD-009 | 1 | `test_scheduler::test_skipped_counts_as_scheduled` |
| BDD-010 | 2 | `test_feed_price_change::test_same_date_rerun_creates_event`, `test_update_run::test_second_run_same_date_replaces_price` |
| BDD-011 | 1 | `test_scheduler::test_interrupted_run_and_catch_up` |
| BDD-012 | 1 | `test_scheduler::test_catch_up_once_after_days_off` |
| BDD-013 | 2 | `test_feed_price_change::test_small_change_no_event`, `test_screens_history::test_change_below_threshold_in_history_not_in_feed` |
| BDD-014 | 1 | `test_feed_price_change::test_small_changes_accumulate` |
| BDD-015 | 1 | `test_feed_price_change::test_opposite_changes_cancel` |
| BDD-016 | 1 | `test_feed_price_change::test_drop_by_threshold` |
| BDD-017 | 1 | `test_feed_price_change::test_new_threshold_from_next_run` |
| BDD-018 | 1 | `test_feed_price_change::test_no_price_keeps_base` |
| BDD-019 | 1 | `test_feed_assortment::test_appeared_after_link` |
| BDD-020 | 1 | `test_feed_assortment::test_disappeared_after_two_dates` |
| BDD-021 | 1 | `test_feed_assortment::test_return_after_disappeared` |
| BDD-022 | 1 | `test_feed_assortment::test_error_or_partial_run_does_not_break_sequence` |
| BDD-023 | 1 | `test_comparison::test_stale_boundary` |
| BDD-024 | 1 | `test_comparison::test_stale_boundary` |
| BDD-025 | 2 | `test_comparison::test_cheapest_and_difference_bdd025`, `test_comparison::test_cheapest_and_difference_on_screens` |
| BDD-026 | 3 | `test_feed_assortment::test_appeared_for_new_material_after_relink`, `test_screens_history::test_relink_does_not_rewrite_history_bdd026`, `test_update_run::test_relink_keeps_history` |
| BDD-027 | 2 | `test_api_directories::test_link_units_differ`, `test_screens_links::test_link_units_differ_on_screen` |
| BDD-028 | 2 | `test_attention_items::test_item_with_other_unit_in_list_bdd028`, `test_comparison::test_only_mismatched_price_shown_with_dash` |
| BDD-029 | 2 | `test_auth::test_comparison_screen_without_login_shows_login_form`, `test_screens_roles::test_b3_screens_need_login` |
| BDD-030 | 5 | `test_api_runs::test_manager_cannot_start_run`, `test_screens_roles::test_manager_other_screens_no_access`, `test_screens_roles::test_manager_actions_no_access` (+2) |
| BDD-031 | 1 | `test_screens_roles::test_admin_opens_all_11_screens` |
| BDD-032 | 2 | `test_api_directories::test_link_second_item_same_supplier`, `test_screens_links::test_second_item_same_supplier_on_screen` |
| BDD-033 | 1 | `test_feed_assortment::test_same_date_counts_once` |
| BDD-034 | 2 | `test_deactivation::test_deactivated_material_comparison_bdd034`, `test_deactivation::test_deactivated_material_prices_no_events_bdd034` |
| BDD-035 | 2 | `test_api_runs::test_update_statuses_for_manager`, `test_update_statuses::test_last_update_counts_partial_not_error` |
| BDD-036 | 1 | `test_screens_history::test_history_shows_only_changes_bdd036` |
| BDD-037 | 2 | `test_api_directories::test_link_inactive_material`, `test_screens_links::test_link_inactive_material_on_screen` |
| BDD-038 | 1 | `test_deactivation::test_material_activation_feed_base_bdd038` |
| BDD-039 | 2 | `test_scheduler::test_interrupted_run_and_catch_up`, `test_update_statuses::test_last_update_counts_interrupted_run_with_data` |
| BDD-040 | 1 | `test_deactivation::test_material_activation_resets_absences_bdd040` |
| BDD-041 | 1 | `test_feed_price_change::test_same_date_rerun_keeps_first_event` |
| BDD-042 | 2 | `test_screens_history::test_relink_and_rerun_same_day_bdd042`, `test_update_run::test_relink_between_same_date_runs` |
| BDD-043 | 1 | `test_scheduler::test_manual_and_scheduled_runs_give_same_results` |
| BDD-044 | 3 | `test_deactivation::test_deactivated_supplier_not_polled_bdd044`, `test_deactivation::test_deactivated_supplier_not_in_comparison_bdd044`, `test_deactivation::test_deactivated_supplier_prices_in_history_bdd044` |
| BDD-045 | 2 | `test_feed_price_change::test_events_only_for_linked_items_of_active_materials`, `test_screens_feed::test_one_feed_for_both_roles_bdd045` |
| BDD-046 | 1 | `test_update_statuses::test_volume_base_grows_never_drops` |
| BDD-047 | 2 | `test_scheduler::test_spring_forward_day`, `test_scheduler::test_fall_back_day` |
| BDD-048 | 1 | `test_scheduler::test_catch_up_after_interrupted_manual_run` |
| BDD-049 | 1 | `test_feed_assortment::test_disappeared_once_and_return_without_price` |
| BDD-050 | 1 | `test_comparison::test_equal_minimum_later_date_wins_bdd050` |
| BDD-051 | 2 | `test_simulator::test_mode_broken_layout`, `test_update_run::test_bdd051_anomalies_then_broken_layout` |
| BDD-052 | 3 | `test_attention_items::test_leaves_list_when_unit_matches_bdd052`, `test_comparison::test_unit_mismatch_takes_last_price_without_mark`, `test_feed_price_change::test_unit_mismatch_price_no_event_no_base` |
| BDD-053 | 1 | `test_deactivation::test_supplier_reset_volume_and_feed_base_bdd053` |
| BDD-054 | 1 | `test_scheduler::test_time_change_after_todays_run` |
| BDD-055 | 1 | `test_comparison::test_comparison_after_relink_bdd055` |
| BDD-056 | 2 | `test_feed_assortment::test_appeared_after_relink_back`, `test_feed_assortment::test_appeared_after_unlink_and_link` |
| BDD-057 | 2 | `test_feed_assortment::test_partial_presence_resets_counter`, `test_feed_assortment::test_appeared_in_partial_run` |
| BDD-058 | 1 | `test_update_run::test_same_date_run_without_new_price_keeps_stored` |
| BDD-059 | 1 | `test_scheduler::test_skipped_counts_as_scheduled` |
| BDD-060 | 1 | `test_update_run::test_run_uses_snapshot_of_its_start` |
| BDD-061 | 1 | `test_scheduler::test_time_changed_to_past_time` |
| BDD-062 | 1 | `test_feed_assortment::test_no_disappeared_without_feed_base` |
| BDD-063 | 7 | `test_api_directories::test_list_material_links`, `test_api_directories::test_relink_to_other_material`, `test_api_directories::test_relink_to_material_with_same_supplier_item` (+4) |
| BDD-064 | 2 | `test_feed_price_change::test_event_date_is_run_date`, `test_screens_feed::test_same_creation_time_later_created_higher_bdd064` |
| BDD-065 | 3 | `test_api_sessions::test_login_admin_case_insensitive`, `test_auth::test_command_creates_account_and_login_works`, `test_auth::test_command_refuses_existing_login_case_insensitively` |
| BDD-066 | 2 | `test_scheduler::test_interrupted_run_rows`, `test_screens_updates::test_log_screen_interrupted_run` |
| BDD-067 | 2 | `test_feed_assortment::test_last_success_run_of_date_absent`, `test_feed_assortment::test_partial_presence_does_not_reset_when_date_has_success` |
| BDD-068 | 3 | `test_api_directories::test_operation_without_session_is_401`, `test_api_views::test_access_by_roles_bdd068`, `test_settings::test_bdd068_threshold_by_role` |
| BDD-069 | 2 | `test_screens_updates::test_log_screen_run_in_progress`, `test_update_statuses::test_run_in_progress_in_log` |
| BDD-070 | 4 | `test_api_directories::test_list_suppliers_manager_bdd070`, `test_api_directories::test_list_materials_manager_bdd070`, `test_api_directories::test_manager_forbidden_state_unchanged` (+1) |
| BDD-071 | 1 | `test_action_log_b2::test_bdd071_action_log` |
| BDD-072 | 1 | `test_export_csv::test_export_bdd072` |

### 1.3. Операції контракту → код і тести

Усі 29 операцій мають маршрут у `src/spm/api/routes.py` з тим самим методом і адресою, що в
`spec/openapi.yaml`, тести pytest і сценарії `tests/contract/scenarios.json` (86 сценаріїв; проти
сервера 86 з 86 — `logs/2026-11-18-a06-feature.md`).

| # | operationId | Метод і адреса | Тести pytest | Сцен. |
|---|---|---|---|---|
| 1 | `createSession` | POST `/sessions` | `test_api_sessions`, `test_action_log_b1`, `helpers` | 2 |
| 2 | `getCurrentSession` | GET `/sessions/current` | `test_api_sessions`, `test_action_log_b1` | 1 |
| 3 | `deleteCurrentSession` | DELETE `/sessions/current` | `test_api_sessions`, `test_action_log_b1` | 1 |
| 4 | `listSuppliers` | GET `/suppliers` | `test_api_directories`, `test_deactivation` | 3 |
| 5 | `createSupplier` | POST `/suppliers` | `test_api_directories`, `test_action_log_b1` | 4 |
| 6 | `getSupplier` | GET `/suppliers/{supplier_id}` | `test_api_directories`, `test_screens_roles` | 4 |
| 7 | `updateSupplier` | PATCH `/suppliers/{supplier_id}` | `test_api_directories`, `test_deactivation` | 3 |
| 8 | `listParsers` | GET `/parsers` | `test_api_directories` | 2 |
| 9 | `listMaterials` | GET `/materials` | `test_api_directories` | 3 |
| 10 | `createMaterial` | POST `/materials` | `test_api_directories`, `test_action_log_b1` | 5 |
| 11 | `getMaterial` | GET `/materials/{material_id}` | `test_api_directories`, `test_api_views` | 2 |
| 12 | `updateMaterial` | PATCH `/materials/{material_id}` | `test_api_directories`, `test_deactivation`, `test_attention_items` | 3 |
| 13 | `listMaterialLinks` | GET `/materials/{material_id}/links` | `test_api_directories`, `test_deactivation` | 2 |
| 14 | `getMaterialPriceHistory` | GET `/materials/{material_id}/price-history` | `test_api_views` | 2 |
| 15 | `listUnlinkedItems` | GET `/unlinked-items` | `test_api_directories` | 2 |
| 16 | `listAttentionItems` | GET `/attention-items` | `test_api_views`, `test_attention_items` | 2 |
| 17 | `putSupplierItemLink` | PUT `/supplier-items/{supplier_item_id}/link` | `test_api_directories` | 6 |
| 18 | `deleteSupplierItemLink` | DELETE `/supplier-items/{supplier_item_id}/link` | `test_api_directories`, `test_action_log_b1` | 3 |
| 19 | `listMaterialComparisons` | GET `/material-comparisons` | `test_api_views`, `test_comparison` | 3 |
| 20 | `getMaterialComparison` | GET `/material-comparisons/{material_id}` | `test_api_views` | 1 |
| 21 | `exportMaterialComparisons` | GET `/exports/material-comparisons` | `test_export_csv` | 4 |
| 22 | `listEvents` | GET `/events` | `test_api_views`, `test_screens_feed` | 2 |
| 23 | `listSupplierUpdateStatuses` | GET `/supplier-update-statuses` | `test_api_runs`, `test_update_statuses` | 1 |
| 24 | `getSettings` | GET `/settings` | `test_api_views`, `test_settings` | 2 |
| 25 | `updateSettings` | PATCH `/settings` | `test_api_views`, `test_settings`, `test_action_log_b1` | 10 |
| 26 | `createRun` | POST `/runs` | `test_api_runs`, `test_scheduler` | 4 |
| 27 | `getRun` | GET `/runs/{run_id}` | `test_api_runs` | 2 |
| 28 | `listRunLogEntries` | GET `/run-log-entries` | `test_api_runs`, `test_update_statuses` | 2 |
| 29 | `createVolumeAcceptance` | POST `/volume-acceptances` | `test_api_runs`, `test_update_statuses`, `test_feed_assortment` | 3 |

### 1.4. UC → тести основного потоку

Кожна вимога з рядка «Вимоги» всіх 16 UC має тест (розд. 1.1). Основний потік покривають:

| UC | Основний потік | Тести |
|---|---|---|
| UC-01 | вхід і вихід | `test_auth`, `test_api_sessions`, `test_screens_roles` (BDD-029, BDD-065) |
| UC-02 | порівняння цін матеріалу, CSV | `test_comparison` (BDD-023…025, 050), `test_export_csv` (BDD-072) |
| UC-03 | історія цін | `test_screens_history` (BDD-036, BDD-026, BDD-042) |
| UC-04 | стрічка змін | `test_screens_feed` (BDD-045, BDD-064), `test_feed_price_change` |
| UC-05 | стан оновлення постачальників | `test_update_statuses` (BDD-035, BDD-039), `test_api_runs` |
| UC-06 | ведення постачальників | `test_api_directories`, `test_screens_directories`, `test_deactivation` (BDD-044, BDD-053) |
| UC-07 | ведення матеріалів | `test_api_directories`, `test_screens_directories`, `test_deactivation` (BDD-034, 038, 040) |
| UC-08 | прив'язка позиції | `test_api_directories`, `test_screens_links` (BDD-027, 032, 037), `test_feed_assortment` (BDD-019) |
| UC-09 | зняття і перев'язка | `test_api_directories`, `test_screens_links` (BDD-063), `test_comparison` (BDD-055) |
| UC-10 | позиції, що потребують уваги | `test_attention_items` (BDD-028, BDD-052) |
| UC-11 | зміна налаштувань | `test_settings` (BDD-068), `test_scheduler` (BDD-054, BDD-061), `test_feed_price_change` (BDD-017) |
| UC-12 | ручний запуск | `test_api_runs`, `test_screens_updates` (BDD-008, BDD-030) |
| UC-13 | журнал і прийняття обсягу | `test_screens_updates`, `test_update_statuses` (BDD-006, 007, 046, 066, 069) |
| UC-14 | запуск за розкладом | `test_scheduler` (BDD-001, 009, 043, 047), `test_update_run`, `test_feed_price_change`, `test_feed_assortment` |
| UC-15 | доганяння після старту | `test_scheduler` (BDD-011, 012, 048) |
| UC-16 | створення облікового запису | `test_auth` (BDD-065) |

## 2. Вибіркова перевірка критеріїв проти тестів

21 вимога: ціни дня, розклад, стрічка, порівняння, права ролей, журнал дій, CSV. «Покрито» — кожна
умова критерію має асерт на даних, які відрізняють правильну реалізацію від хибної.

| REQ | Тести (основні) | Вердикт | Знахідка |
|---|---|---|---|
| REQ-F-028 ціна дня, повторний запуск | `test_update_run::test_second_run_same_date_replaces_price`, `::test_same_date_run_without_new_price_keeps_stored`, `::test_relink_between_same_date_runs`; `test_screens_history::test_relink_and_rerun_same_day_bdd042`; `test_feed_price_change::test_event_date_is_run_date` | покрито, дрібне зауваження | Умову 2 (запуск о 23:59 пише ціни датою 10-05) перевірено як «ціна за 10-05 = 1100»; асерту, що ціни за 10-06 немає, немає — Р-05 |
| REQ-F-053 повторна дата і стрічка | `test_feed_price_change::test_same_date_rerun_keeps_first_event`, `::test_same_date_rerun_no_second_appeared` | покрито | База 1000 перевірена опосередковано (подія 1000 → 1015 наступного дня) |
| REQ-F-018 розклад 03:30 | `test_scheduler::test_scheduled_run_at_0330`, `::test_scheduled_run_at_changed_time` | покрито | Субагент позначив «частково» через тік 05:00:30; критерій задає вікно 05:00–05:01, а тік 04:59:59 перевірено як «запуску немає» — відхилено |
| REQ-F-054 літній / зимовий час | `test_scheduler::test_spring_forward_day`, `::test_fall_back_day` | покрито | — |
| REQ-F-024 перерваний запуск | `test_scheduler::test_interrupted_run_and_catch_up` | покрито | Сторінка змінюється перед перезапуском — ціну доганяння видно |
| REQ-F-055 зміна часу і доганяння | 8 тестів `test_scheduler` | покрито | — |
| REQ-F-042 стрічка змін | `test_screens_feed::test_one_feed_for_both_roles_bdd045`, `test_feed_price_change::test_events_only_for_linked_items_of_active_materials` | покрито, дрібне зауваження | «Не надсилає e-mail / push» — негативна умова, перевірено інспекцією (такого коду немає) — Р-06 |
| REQ-F-044 поріг | `test_feed_price_change::test_threshold_compared_exactly`, `::test_drop_by_threshold` | покрито | 1009,99 ловить округлення; 1010 і 990 — межа «≥» |
| REQ-F-045 накопичення | `test_feed_price_change::test_small_changes_accumulate`, `::test_opposite_changes_cancel` | покрито | — |
| REQ-F-046 «з'явився» | `test_feed_assortment` (4 тести) | покрито | — |
| REQ-F-047 «зник» | `test_feed_assortment` (10 тестів), `test_deactivation::test_material_activation_resets_absences_bdd040` | покрито | — |
| REQ-F-035 найдешевша ціна | `test_comparison` (6 тестів) | покрито, дрібне зауваження | На екрані не перевіряється «грн» біля ціни (лише «Альфа» і «1000,00») — Р-05 |
| REQ-F-036 різниця від найдешевшої | `test_comparison::test_cheapest_and_difference_bdd025`, `::test_stale_boundary` | частково | «—» замість різниці для застарілої ціни перевірено лише в API (`difference_from_cheapest is None`); на екрані за іншої придатної ціни — лише позначка «застаріла», не «—» — Р-04 |
| REQ-F-037 виключені ціни | `test_comparison::test_excluded_prices_do_not_take_part` (5 випадків) | покрито | — |
| REQ-F-038 застарілість | `test_comparison::test_stale_boundary`, `::test_stale_at_midnight_without_run` | покрито | — |
| REQ-F-059 пошук | `test_comparison::test_list_search_case_insensitive`, `test_export_csv::test_search_ldsp` | покрито | — |
| REQ-F-005 «немає доступу» для менеджера | `test_screens_roles::test_manager_other_screens_no_access`, `test_screens_updates::test_manager_no_access_to_log` | частково | «Без вмісту екрана» перевірено пошуком рядків `А-1`, `Б-9`, `http://127.0.0.1`; для журналу оновлень це не його вміст (дати, статуси, назви постачальників не перевіряються) — Р-04 |
| REQ-NF-003 рівно 5 / 11 екранів | `test_screens_roles::test_admin_opens_all_11_screens`, `::test_manager_opens_5_screens`, `::test_admin_navigation` | частково | Меню адміністратора перевірено як підмножину (`set(...) <= links`) — 12-й екран пройшов би; для менеджера перевірено строго — Р-04 |
| REQ-NF-032 журнал дій | `test_action_log_b1/b2/b3`, `test_logs` | частково | «Жоден екран і жодна операція не повертають записів журналу» перевірено на 10 адресах переглядів; списки довідників, журнал оновлень, налаштування й решту операцій не перевірено — Р-04 |
| REQ-NF-033 збій журналу не ламає дію | `test_action_log_b1::test_threshold_change_api_with_broken_action_log`, `::test_threshold_change_web_with_broken_action_log`, `test_action_log_b2::test_manual_run_with_broken_technical_log` | покрито, дрібне зауваження | «Та сама відповідь» ручного запуску — порівняння з фіксованими 202 / Location / `in_progress`, а не з запуском без збою — Р-05 |
| REQ-F-072 CSV | `test_export_csv` (14 тестів) | покрито | Файл порівнюється побайтово; деактивований матеріал має найнижчу ціну — дані розрізняють |

Знахідку субагента щодо REQ-F-013 («сервіс перев'язує вже прив'язану позицію замість відмови»)
відхилено: перев'язка — окрема дозволена дія (REQ-F-015, REQ-F-069, операція
`putSupplierItemLink`: «Другої прив'язки в позиції не виникає»). Критерій REQ-F-013 забороняє другу
одночасну прив'язку, і схема її унеможливлює (одна колонка `material_id`).

## 3. Архітектура і правила розробки

### 3.1. Правило залежностей (`docs/architecture.md`, розд. 5)

Фактичні залежності між компонентами `src/spm` (без `logging` і `clock`, дозволених усім):
`web → auth, services`; `api → auth, services`; `auth → storage`; `services → storage`;
`update → services, storage`; `app` (збирання) → усі. Залежностей `services → update`,
`services → web/api`, `web/api → storage` немає; `services` не імпортує FastAPI, Starlette чи Jinja2.

`src/spm` не імпортує `simulator` (слово трапляється лише в докстрінгу `spm/update/parsers.py`);
`simulator/` не імпортує `spm`.

Одне відхилення від букви правила: `spm/auth/cli.py:25` імпортує `spm.config` (`load_config`).
Правило каже «напряму `config` жоден компонент не імпортує». `cli.py` — окрема точка входу команди
створення облікового запису, тобто власний «старт», і читає конфігурацію лише під час запуску
команди, тож дух правила збережено — Р-03.

### 3.2. REQ-NF-012, REQ-NF-023, адреси

- REQ-NF-012: залежності Python змінювали два коміти — `079ca52` і `cbc9d0d`, обидва `chore:` без
  файлів у `src/`, `tests/`, `spec/`; інструменти Node (`8977db9`, Redocly і Prism) — так само.
  Виконано.
- REQ-NF-023: кожному з 5 комітів `feat:` передує коміт `test:` з тестами цього пакета (B1.1, B1.2,
  B2, B3, T-60); 14 комітів `refactor:` поведінки не змінюють і йдуть під наявними тестами
  (`logs/2026-11-18-a06-feature.md`). Виконано за формою; що тест «стосується зміненої поведінки»,
  підтверджують TEST-GATE у `logs/gates.md`.
- Адрес реальних сайтів у `src`, `simulator`, `tests` немає (лише `127.0.0.1` і `localhost`).

## 4. Матриця трасування (T-49)

Генератор `tests/tools/generate_traceability.py` колонок «Тест», «Код», «Документація» не будував —
лише переносив їх з поточної матриці, де вони були порожні. Доопрацювання:

- колонки будуються за ID вимог у файлах: `tests/**/test_*.py` (крім `test_traceability.py`, де ID —
  зразкові дані) і `tests/contract/scenarios.json`; `src/spm/**/*.py`, шаблони `src/spm/**/*.html`,
  `simulator/**/*.py`; документи `docs/architecture.md`, `docs/api/resources.md`,
  `docs/api/scenarios.md`;
- `CODE_EXTRA` — модулі з розд. 1.1, що реалізують вимогу без її ID;
- `NOTES` — текст клітинок для REQ-NF-002, 008, 009, 010, 012, 023; щойно з'явиться тест, що цитує
  вимогу, він автоматично замінить примітку;
- «Тікет» і далі переноситься; вступ матриці описує нові колонки;
- у `tests/test_traceability.py` додано два тести генератора.

Результат: «Тест» заповнено в 105 з 105 рядків (99 — файли, 6 — примітки), «Код» — у 102 (немає в
REQ-NF-002, 008, 009), «Документація» — у 101. Колонки від «REQ ID» до «Тікет» не змінились.
`tests/test_traceability.py` — 4 passed; `--check` генератора — без розбіжностей.

## 5. Розбіжності (не виправлялись)

| № | Важливість | Що | Де | Далі |
|---|---|---|---|---|
| Р-01 | значна | Немає тесту швидкодії з окремою міткою (REQ-NF-009) і протоколу тривалості запуску ≤ 5 хв (REQ-NF-008); T-45 не виконано | `tests/`, `logs/` | T-45 |
| Р-02 | значна для приймання | Немає протоколу ручної перевірки в Chrome і Firefox (REQ-NF-002); T-48 не виконано | `logs/` | T-48, людина |
| Р-03 | дрібно | `spm/auth/cli.py` імпортує `spm.config` всупереч букві правила розд. 5 | `docs/architecture.md` або `cli.py` | людина: уточнити правило («точки входу читають config») чи винести збирання |
| Р-04 | середня (тести) | Слабкі асерти: REQ-F-005 (вміст журналу для менеджера), REQ-NF-003 (меню адміністратора як підмножина), REQ-NF-032 (не всі екрани й операції), REQ-F-036 («—» на екрані за іншої придатної ціни) | `tests/test_screens_roles.py`, `tests/test_screens_updates.py`, `tests/test_action_log_b3.py`, `tests/test_comparison.py` | окремий тікет `test:` |
| Р-05 | дрібно (тести) | REQ-F-028 (немає асерту відсутності ціни за 10-06), REQ-F-035 («грн» на екрані), REQ-NF-033 (порівняння з фіксованою відповіддю) | ті самі модулі | за рішенням людини |
| Р-06 | інформативно | REQ-F-042 «не надсилає e-mail / push» — без тесту, перевірено інспекцією | — | — |
| Р-07 | дрібно (документація) | Інструкції із запуску (T-46) у `docs/` немає; `docs/api/resources.md`, розд. 0: «Дані — JSON» без винятку `text/csv`; `docs/architecture.md` не згадує REQ-F-072 у рядку `services` | `docs/` | T-46, окремий `docs:` |

## 6. Висновок

- **SRS 1.11.** Функціональні вимоги реалізовано: усі 72 REQ-F мають код і тести, усі 72 BDD —
  автоматичні тести, основні потоки всіх 16 UC покрито. У вибірці з 21 вимоги розбіжностей поведінки
  з критеріями не знайдено; знайдено слабкі місця тестів (Р-04, Р-05), які могли б пропустити
  регресію, але не свідчать про хибну реалізацію. Нефункціональні вимоги виконано, крім REQ-NF-002,
  REQ-NF-008 і REQ-NF-009, перевірки яких (T-45, T-48) ще не зроблено (Р-01, Р-02); REQ-NF-010 не
  приймається за визначенням, REQ-NF-012 і REQ-NF-023 виконано за історією git.
- **Контракт.** Усі 29 операцій реалізовано з тими самими методами й адресами, кожна має тести
  pytest і сценарії; 86 з 86 сценаріїв проходять проти сервера.
- **A-06.** REQ-F-072, BDD-072 і `exportMaterialComparisons` реалізовано й покрито повністю; Н-46 і
  Н-47 проходять. Залишки A-06 — лише документація (Р-07).
- **Архітектура.** Правило залежностей дотримано, крім формального відхилення Р-03; `src/spm` не
  імпортує імітатор.
- **Загалом:** реалізація відповідає SRS 1.11, контракту й A-06 у частині функціональної поведінки.
  Повне приймання за SRS блокують Р-01 і Р-02 (T-45, T-48).

## Стан індексу

В індексі три групи для трьох окремих комітів; лог не в індексі:

1. `test:` — `tests/tools/generate_traceability.py`, `tests/test_traceability.py`; наприклад
   `test: generate test, code and doc columns of traceability matrix`.
2. `spec:` — `spec/traceability.md` (T-49); наприклад
   `spec: fill test, code and documentation columns of traceability`.
3. `docs:` — `docs/api/scenarios.md`; наприклад
   `docs: update CSV scenario note after contract runner rework`.

Порядок: спершу `test:` (генератор), потім `spec:` (матриця, яку він згенерував), потім `docs:`.
Індекс спільний, тому кожен коміт — з переліком файлів: `git commit -- <файли>`.
