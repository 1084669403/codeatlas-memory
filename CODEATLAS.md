---
project: CodeAtlas
generated: 2026-09-14 16:20
language: en
files: 46
symbols: 326
last_scan: 2026-09-14T08:20:35+00:00
---

> First time here? Run `codeatlas scan .` to generate the full detail (`.codeatlas/detail/`).

## Diagrams

### Directory Tree

```mermaid
graph TD
    d___root___f1fabfb4["/"]
    d_demo_todo_af73008e["demo-todo"]
    d___root___f1fabfb4 --> d_demo_todo_af73008e
    d_demo_todo_app_c6975872["app"]
    d_demo_todo_af73008e --> d_demo_todo_app_c6975872
    d_todo_app_controllers_a309c4ff["controllers"]
    d_demo_todo_app_c6975872 --> d_todo_app_controllers_a309c4ff
    f_s_task_controller_py_53d29a6d["task_controller.py"]
    d_todo_app_controllers_a309c4ff --> f_s_task_controller_py_53d29a6d
    f_emo_todo_app_main_py_d01174b7["main.py"]
    d_demo_todo_app_c6975872 --> f_emo_todo_app_main_py_d01174b7
    d_demo_todo_app_models_95d91b5d["models"]
    d_demo_todo_app_c6975872 --> d_demo_todo_app_models_95d91b5d
    f_o_app_models_task_py_b52a7bc4["task.py"]
    d_demo_todo_app_models_95d91b5d --> f_o_app_models_task_py_b52a7bc4
    f_o_app_models_user_py_8e368df3["user.py"]
    d_demo_todo_app_models_95d91b5d --> f_o_app_models_user_py_8e368df3
    d_mo_todo_app_services_a84afc58["services"]
    d_demo_todo_app_c6975872 --> d_mo_todo_app_services_a84afc58
    f_ices_auth_service_py_cfaef27a["auth_service.py"]
    d_mo_todo_app_services_a84afc58 --> f_ices_auth_service_py_cfaef27a
    f_ices_task_service_py_cf7adef2["task_service.py"]
    d_mo_todo_app_services_a84afc58 --> f_ices_task_service_py_cf7adef2
    d_demo_todo_app_utils_2f990ce9["utils"]
    d_demo_todo_app_c6975872 --> d_demo_todo_app_utils_2f990ce9
    f__utils_validators_py_00984a64["validators.py"]
    d_demo_todo_app_utils_2f990ce9 --> f__utils_validators_py_00984a64
    d_demo_todo_static_11b780a2["static"]
    d_demo_todo_af73008e --> d_demo_todo_static_11b780a2
    f_static_task_panel_ts_84a17a8c["task_panel.ts"]
    d_demo_todo_static_11b780a2 --> f_static_task_panel_ts_84a17a8c
    d_scripts_d6c5855a["scripts"]
    d___root___f1fabfb4 --> d_scripts_d6c5855a
    f_scripts_probe_ast_py_821708b4["probe_ast.py"]
    d_scripts_d6c5855a --> f_scripts_probe_ast_py_821708b4
    f_scripts_probe_cli_py_61b2660a["probe_cli.py"]
    d_scripts_d6c5855a --> f_scripts_probe_cli_py_61b2660a
    f_pts_probe_indexer_py_f369534f["probe_indexer.py"]
    d_scripts_d6c5855a --> f_pts_probe_indexer_py_f369534f
    f_ipts_probe_parser_py_b5e019be["probe_parser.py"]
    d_scripts_d6c5855a --> f_ipts_probe_parser_py_b5e019be
    f_robe_query_render_py_fa2fe2c9["probe_query_render.py"]
    d_scripts_d6c5855a --> f_robe_query_render_py_fa2fe2c9
    f_cripts_smoke_test_py_769f7b32["smoke_test.py"]
    d_scripts_d6c5855a --> f_cripts_smoke_test_py_769f7b32
    d_src_25d902c2["src"]
    d___root___f1fabfb4 --> d_src_25d902c2
    d_src_codeatlas_9b8859fc["codeatlas"]
    d_src_25d902c2 --> d_src_codeatlas_9b8859fc
    f_odeatlas___init___py_b23e50a1["__init__.py"]
    d_src_codeatlas_9b8859fc --> f_odeatlas___init___py_b23e50a1
    f__codeatlas_budget_py_77d59d5c["budget.py"]
    d_src_codeatlas_9b8859fc --> f__codeatlas_budget_py_77d59d5c
    f_deatlas_callgraph_py_09387f91["callgraph.py"]
    d_src_codeatlas_9b8859fc --> f_deatlas_callgraph_py_09387f91
    f_deatlas_changelog_py_7f95a410["changelog.py"]
    d_src_codeatlas_9b8859fc --> f_deatlas_changelog_py_7f95a410
    f_src_codeatlas_cli_py_023008d7["cli.py"]
    d_src_codeatlas_9b8859fc --> f_src_codeatlas_cli_py_023008d7
    f_atlas_consistency_py_138fcdbe["consistency.py"]
    d_src_codeatlas_9b8859fc --> f_atlas_consistency_py_138fcdbe
    f_odeatlas_diagrams_py_9af4eb3f["diagrams.py"]
    d_src_codeatlas_9b8859fc --> f_odeatlas_diagrams_py_9af4eb3f
    f_codeatlas_indexer_py_1c986101["indexer.py"]
    d_src_codeatlas_9b8859fc --> f_codeatlas_indexer_py_1c986101
    f_odeatlas_markdown_py_92f67d62["markdown.py"]
    d_src_codeatlas_9b8859fc --> f_odeatlas_markdown_py_92f67d62
    f__codeatlas_memory_py_811979e0["memory.py"]
    d_src_codeatlas_9b8859fc --> f__codeatlas_memory_py_811979e0
    f__codeatlas_models_py_4449037a["models.py"]
    d_src_codeatlas_9b8859fc --> f__codeatlas_models_py_4449037a
    f__codeatlas_parser_py_25f5e1b0["parser.py"]
    d_src_codeatlas_9b8859fc --> f__codeatlas_parser_py_25f5e1b0
    f_odeatlas_prefetch_py_2cc85f49["prefetch.py"]
    d_src_codeatlas_9b8859fc --> f_odeatlas_prefetch_py_2cc85f49
    f_codeatlas_scanner_py_8b5a09f9["scanner.py"]
    d_src_codeatlas_9b8859fc --> f_codeatlas_scanner_py_8b5a09f9
    f_codeatlas_storage_py_c8346aca["storage.py"]
    d_src_codeatlas_9b8859fc --> f_codeatlas_storage_py_c8346aca
    f_eatlas_summarizer_py_e3f8a862["summarizer.py"]
    d_src_codeatlas_9b8859fc --> f_eatlas_summarizer_py_e3f8a862
    d_tests_b61a6d54["tests"]
    d___root___f1fabfb4 --> d_tests_b61a6d54
    f_tests_conftest_py_484462fc["conftest.py"]
    d_tests_b61a6d54 --> f_tests_conftest_py_484462fc
    f_tests_test_budget_py_c3873fcf["test_budget.py"]
    d_tests_b61a6d54 --> f_tests_test_budget_py_c3873fcf
    f_ts_test_callgraph_py_5122bd9d["test_callgraph.py"]
    d_tests_b61a6d54 --> f_ts_test_callgraph_py_5122bd9d
    f_ts_test_changelog_py_c7f314c2["test_changelog.py"]
    d_tests_b61a6d54 --> f_ts_test_changelog_py_c7f314c2
    f_t_consistency_e2e_py_787988a7["test_consistency_e2e.py"]
    d_tests_b61a6d54 --> f_t_consistency_e2e_py_787988a7
    f__test_context_e2e_py_2aa49f07["test_context_e2e.py"]
    d_tests_b61a6d54 --> f__test_context_e2e_py_2aa49f07
    f_sts_test_diagrams_py_beb09a0a["test_diagrams.py"]
    d_tests_b61a6d54 --> f_sts_test_diagrams_py_beb09a0a
    f_ests_test_indexer_py_bec50d19["test_indexer.py"]
    d_tests_b61a6d54 --> f_ests_test_indexer_py_bec50d19
    f_sts_test_markdown_py_0ffced02["test_markdown.py"]
    d_tests_b61a6d54 --> f_sts_test_markdown_py_0ffced02
    f_tests_test_memory_py_58229cbd["test_memory.py"]
    d_tests_b61a6d54 --> f_tests_test_memory_py_58229cbd
    f_tests_test_parser_py_ed9d6689["test_parser.py"]
    d_tests_b61a6d54 --> f_tests_test_parser_py_ed9d6689
    f_sts_test_prefetch_py_d61dc3b5["test_prefetch.py"]
    d_tests_b61a6d54 --> f_sts_test_prefetch_py_d61dc3b5
    f_est_query_history_py_5c516287["test_query_history.py"]
    d_tests_b61a6d54 --> f_est_query_history_py_5c516287
    f_ests_test_scanner_py_a6246478["test_scanner.py"]
    d_tests_b61a6d54 --> f_ests_test_scanner_py_a6246478
    f_ests_test_storage_py_ce0ce06d["test_storage.py"]
    d_tests_b61a6d54 --> f_ests_test_storage_py_ce0ce06d
    f_s_test_summarizer_py_eed59225["test_summarizer.py"]
    d_tests_b61a6d54 --> f_s_test_summarizer_py_eed59225
```

### Module Dependencies

```mermaid
flowchart LR
    empty["no internal dependencies"]
```

### Class Inheritance

```mermaid
classDiagram
    class c_oller_TaskController_85e43147 {
        TaskController
    }
    class c_app_models_task_Task_e1309af7 {
        Task
    }
    class c_app_models_user_User_2331dc53 {
        User
    }
    class c__service_AuthService_eb766f7c {
        AuthService
    }
    class c__service_TaskService_90941598 {
        TaskService
    }
    class c_task_panel_TaskPanel_e1172c04 {
        TaskPanel
    }
    class c_mory_AmbiguousSymbol_386b8d46 {
        AmbiguousSymbol
    }
    note for c_mory_AmbiguousSymbol_386b8d46 "extends Exception"
    class c_as_models_ChangeType_17480da7 {
        ChangeType
    }
    note for c_as_models_ChangeType_17480da7 "extends str"
    note for c_as_models_ChangeType_17480da7 "extends Enum"
    class c_odeatlas_models_Role_c5d68e68 {
        Role
    }
    note for c_odeatlas_models_Role_c5d68e68 "extends str"
    note for c_odeatlas_models_Role_c5d68e68 "extends Enum"
    class c_as_models_SymbolKind_8d37c271 {
        SymbolKind
    }
    note for c_as_models_SymbolKind_8d37c271 "extends str"
    note for c_as_models_SymbolKind_8d37c271 "extends Enum"
    class c_eatlas_storage_Store_1fe73e2a {
        Store
    }
    class c_rizer_RuleSummarizer_596e2a02 {
        RuleSummarizer
    }
    class c_ummarizer_Summarizer_790cd1b2 {
        Summarizer
    }
    note for c_ummarizer_Summarizer_790cd1b2 "extends Protocol"
```

### Call Graph (approximate)

```mermaid
%% approximate
flowchart TD
    cg_ripts_probe_cli_main_56c37b22["main"]
    cg_cripts_probe_cli_run_b3a806d7["run"]
    cg_ripts_probe_cli_main_56c37b22 -->|"9"| cg_cripts_probe_cli_run_b3a806d7
    cg_s_prefetch_neighbors_69a0aae7["neighbors"]
    cg__panel_TaskPanel_add_1290b4de["add"]
    cg_s_prefetch_neighbors_69a0aae7 -->|"6"| cg__panel_TaskPanel_add_1290b4de
    cg_grams_directory_tree_edc90507["directory_tree"]
    cg_as_diagrams__node_id_c401dc4d["_node_id"]
    cg_grams_directory_tree_edc90507 -->|"4"| cg_as_diagrams__node_id_c401dc4d
    cg___parse_js_signature_7af9866c["_parse_js_signature"]
    cg_deatlas_parser__text_d1d34230["_text"]
    cg___parse_js_signature_7af9866c -->|"4"| cg_deatlas_parser__text_d1d34230
    cg_s_probe_indexer_main_a4ac6aa6["main"]
    cg_s_indexer_run_update_6164233b["run_update"]
    cg_s_probe_indexer_main_a4ac6aa6 -->|"3"| cg_s_indexer_run_update_6164233b
    cg_ms_inheritance_graph_8a222358["inheritance_graph"]
    cg_tlas_diagrams__clean_6b5d9662["_clean"]
    cg_ms_inheritance_graph_8a222358 -->|"3"| cg_tlas_diagrams__clean_6b5d9662
    cg_las_indexer_run_scan_0ac7e4f9["run_scan"]
    cg_orage_Store_set_meta_2ea4c7e4["set_meta"]
    cg_las_indexer_run_scan_0ac7e4f9 -->|"3"| cg_orage_Store_set_meta_2ea4c7e4
    cg_s_memory_locality_of_34184314["locality_of"]
    cg_memory__parse_anchor_00fceef2["_parse_anchor"]
    cg_s_memory_locality_of_34184314 -->|"3"| cg_memory__parse_anchor_00fceef2
    cg_s_memory_save_budget_353c881e["save_budget"]
    cg_s_memory_save_budget_353c881e -->|"3"| cg_orage_Store_set_meta_2ea4c7e4
    cg_eatlas_memory_status_b6825145["status"]
    cg_memory__is_file_page_a9c1e0f6["_is_file_page"]
    cg_eatlas_memory_status_b6825145 -->|"3"| cg_memory__is_file_page_a9c1e0f6
    cg_tlas_parser__flatten_fb37295b["_flatten"]
    cg___parse_js_signature_7af9866c -->|"3"| cg_tlas_parser__flatten_fb37295b
    cg___parse_py_signature_8554cf56["_parse_py_signature"]
    cg___parse_py_signature_8554cf56 -->|"3"| cg_deatlas_parser__text_d1d34230
    cg_tch_recency_discount_16f3cb09["test_prefetch_recency_discount"]
    cg_udget_eviction_score_e3997300["eviction_score"]
    cg_tch_recency_discount_16f3cb09 -->|"3"| cg_udget_eviction_score_e3997300
    cg_cycle_and_invariants_12cdbc1e["test_full_lifecycle_and_invaria…"]
    cg_tency_check_fts_sync_414a03e5["check_fts_sync"]
    cg_cycle_and_invariants_12cdbc1e -->|"3"| cg_tency_check_fts_sync_414a03e5
    cg__check_refs_dangling_0565b695["check_refs_dangling"]
    cg_cycle_and_invariants_12cdbc1e -->|"3"| cg__check_refs_dangling_0565b695
    cg_trips_breaking_chars_eaacf045["test_clean_strips_breaking_chars"]
    cg_trips_breaking_chars_eaacf045 -->|"3"| cg_tlas_diagrams__clean_6b5d9662
    cg_detection_and_render_113d3e46["test_file_page_detection_and_re…"]
    cg_detection_and_render_113d3e46 -->|"3"| cg_memory__is_file_page_a9c1e0f6
    cg_est_layered_locality_a554f738["test_layered_locality"]
    cg_s_memory__build_page_93e6d209["_build_page"]
    cg_est_layered_locality_a554f738 -->|"3"| cg_s_memory__build_page_93e6d209
    cg_est_layered_locality_a554f738 -->|"3"| cg_s_memory_locality_of_34184314
    cg_r_and_pin_protection_f3e84880["test_lru_eviction_order_and_pin…"]
    cg_las_memory_load_page_33f090e0["load_page"]
    cg_r_and_pin_protection_f3e84880 -->|"3"| cg_las_memory_load_page_33f090e0
    cg__pages_evicted_first_9438c079["test_prefetch_pages_evicted_fir…"]
    cg__pages_evicted_first_9438c079 -->|"3"| cg_las_memory_load_page_33f090e0
    cg_ts_probe_parser_main_624d499e["main"]
    cg_as_parser_parse_file_159138e2["parse_file"]
    cg_ts_probe_parser_main_624d499e -->|"2"| cg_as_parser_parse_file_159138e2
    cg_be_query_render_main_192b71c9["main"]
    cg_be_query_render_main_192b71c9 -->|"2"| cg_cripts_probe_cli_run_b3a806d7
    cg_h_rebuild_call_edges_91721405["rebuild_call_edges"]
    cg_h_rebuild_call_edges_91721405 -->|"2"| cg_orage_Store_set_meta_2ea4c7e4
    cg_og_write_history_doc_000f9315["write_history_doc"]
    cg_as_changelog__fmt_ts_907c6abc["_fmt_ts"]
    cg_og_write_history_doc_000f9315 -->|"2"| cg_as_changelog__fmt_ts_907c6abc
    cg_Store_last_change_ts_e519d5b7["last_change_ts"]
    cg_og_write_history_doc_000f9315 -->|"2"| cg_Store_last_change_ts_e519d5b7
    cg__diagrams_call_graph_46ed467f["call_graph"]
    cg__diagrams_call_graph_46ed467f -->|"2"| cg_tlas_diagrams__clean_6b5d9662
    cg__diagrams_call_graph_46ed467f -->|"2"| cg_as_diagrams__node_id_c401dc4d
    cg_ams_dependency_graph_2ff1aa32["dependency_graph"]
    cg_ams_dependency_graph_2ff1aa32 -->|"2"| cg_tlas_diagrams__clean_6b5d9662
    cg_ams_dependency_graph_2ff1aa32 -->|"2"| cg_as_diagrams__node_id_c401dc4d
    cg_grams_directory_tree_edc90507 -->|"2"| cg__panel_TaskPanel_add_1290b4de
    cg_grams_directory_tree_edc90507 -->|"2"| cg_tlas_diagrams__clean_6b5d9662
    cg_ms_inheritance_graph_8a222358 -->|"2"| cg_as_diagrams__node_id_c401dc4d
    cg_dexer_detect_renames_5fdb88f6["detect_renames"]
    cg_dexer_detect_renames_5fdb88f6 -->|"2"| cg__panel_TaskPanel_add_1290b4de
    cg_s_indexer__sig_shape_3a710053["_sig_shape"]
    cg_dexer_detect_renames_5fdb88f6 -->|"2"| cg_s_indexer__sig_shape_3a710053
    cg_down_render_overview_7f993468["render_overview"]
    cg_s_markdown__file_row_65af00b2["_file_row"]
    cg_down_render_overview_7f993468 -->|"2"| cg_s_markdown__file_row_65af00b2
    cg_ted_files_for_symbol_6514933f["_related_files_for_symbol"]
    cg_ted_files_for_symbol_6514933f -->|"2"| cg__panel_TaskPanel_add_1290b4de
    cg_memory_ensure_budget_7b3ce7dd["ensure_budget"]
    cg__working_set_entries_cda002e8["working_set_entries"]
    cg_memory_ensure_budget_7b3ce7dd -->|"2"| cg__working_set_entries_cda002e8
    cg___parse_py_signature_8554cf56 -->|"2"| cg_tlas_parser__flatten_fb37295b
    cg_rser__py_class_bases_46031ff5["_py_class_bases"]
    cg_rser__py_class_bases_46031ff5 -->|"2"| cg_deatlas_parser__text_d1d34230
    more_40["… 40+ edges (see call_edges table)"]
```

## Files

| File | Lang | Role | Symbols | Ref'd |
|---|---|---|---:|---:|
| `demo-todo/app/controllers/task_controller.py` | python | controller | 4 | 0 |
| `demo-todo/app/main.py` | python | entry | 1 | 0 |
| `demo-todo/app/models/task.py` | python | model | 3 | 0 |
| `demo-todo/app/models/user.py` | python | model | 2 | 0 |
| `demo-todo/app/services/auth_service.py` | python | service | 3 | 0 |
| `demo-todo/app/services/task_service.py` | python | service | 6 | 0 |
| `demo-todo/app/utils/validators.py` | python | util | 1 | 0 |
| `demo-todo/static/task_panel.ts` | typescript | module | 4 | 0 |
| `scripts/probe_ast.py` | python | module | 1 | 0 |
| `scripts/probe_cli.py` | python | entry | 2 | 0 |
| `scripts/probe_indexer.py` | python | module | 1 | 0 |
| `scripts/probe_parser.py` | python | module | 1 | 0 |
| `scripts/probe_query_render.py` | python | module | 1 | 0 |
| `scripts/smoke_test.py` | python | test | 1 | 0 |
| `src/codeatlas/__init__.py` | python | module | 0 | 0 |
| `src/codeatlas/budget.py` | python | module | 5 | 0 |
| `src/codeatlas/callgraph.py` | python | module | 8 | 0 |
| `src/codeatlas/changelog.py` | python | module | 5 | 0 |
| `src/codeatlas/cli.py` | python | entry | 7 | 0 |
| `src/codeatlas/consistency.py` | python | module | 7 | 0 |
| `src/codeatlas/diagrams.py` | python | module | 7 | 0 |
| `src/codeatlas/indexer.py` | python | module | 12 | 0 |
| `src/codeatlas/markdown.py` | python | module | 6 | 0 |
| `src/codeatlas/memory.py` | python | module | 26 | 0 |
| `src/codeatlas/models.py` | python | module | 3 | 0 |
| `src/codeatlas/parser.py` | python | module | 19 | 0 |
| `src/codeatlas/prefetch.py` | python | module | 5 | 0 |
| `src/codeatlas/scanner.py` | python | module | 2 | 0 |
| `src/codeatlas/storage.py` | python | module | 46 | 0 |
| `src/codeatlas/summarizer.py` | python | module | 10 | 0 |
| `tests/conftest.py` | python | test | 0 | 0 |
| `tests/test_budget.py` | python | test | 7 | 0 |
| `tests/test_callgraph.py` | python | test | 9 | 0 |
| `tests/test_changelog.py` | python | test | 11 | 0 |
| `tests/test_consistency_e2e.py` | python | test | 7 | 0 |
| `tests/test_context_e2e.py` | python | test | 11 | 0 |
| `tests/test_diagrams.py` | python | test | 10 | 0 |
| `tests/test_indexer.py` | python | test | 9 | 0 |
| `tests/test_markdown.py` | python | test | 6 | 0 |
| `tests/test_memory.py` | python | test | 21 | 0 |
| `tests/test_parser.py` | python | test | 6 | 0 |
| `tests/test_prefetch.py` | python | test | 8 | 0 |
| `tests/test_query_history.py` | python | test | 6 | 0 |
| `tests/test_scanner.py` | python | test | 5 | 0 |
| `tests/test_storage.py` | python | test | 5 | 0 |
| `tests/test_summarizer.py` | python | test | 6 | 0 |

## Recent Changes

- [2026-09-14_1355.md](.codeatlas/history/2026-09-14_1355.md)
- [2026-09-14_1352.md](.codeatlas/history/2026-09-14_1352.md)
