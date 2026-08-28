# Consistency audit — 2026-08-27

**This record is intentionally English-only.** The bilingual rule in `AGENTS.md` governs
documents a reader of the project depends on; this is an internal audit of one day's work —
a snapshot of what was checked, what was fixed in place, and what remains open. It is dated
rather than living, and it is not linked from `docs/README.md`.

Scope: the mechanisms that landed on top of `a32fa5f` — canonical supersession, the document
overview, the index-component seam, the shipped `people` and `time` components, and fast
recall's routed component paths — audited as **design → docs → code → tests**. Every row
names the code symbol that enforces the mechanism and the test that pins it.

Baseline at the start of the pass: `uv run pytest -q` 1488 passed; `uv run pytest tests/ -q`
83 passed, 6 skipped.

---

## A. Canonical write mechanics

Core paths below are relative to
`packages/pneuma-knowledge-core/src/pneuma_knowledge_core/`; core tests to
`packages/pneuma-knowledge-core/tests/`.

| mechanism | doc | code | test | status |
|---|---|---|---|---|
| Claim = anchor + citations; anchors system-assigned and immutable | architecture §5 | `compile/anchor_ops.py:assign_anchor`, `domain/ids.py:ANCHOR_MARK_RE` | `test_anchor_ops.py::test_extract_anchors_ordered` | consistent |
| Four write verbs, no whole-document write | architecture §1, §5 | `compile/runner.py:_build_tools`, `compile/patch.py:PatchDraft` | `test_runner.py`, `test_supersession.py`, `test_overview.py` | **fixed** — architecture §1 still said "can only edit or append"; rewritten to name all four |
| Gate: anchors, citations, provenance, links, frontmatter, path ownership, frozen volumes | architecture §5 | `compile/gate.py:run_gate` | `test_gate.py` | consistent |
| `edit_claim` preserves the replaced block's FORM | architecture §5 | `compile/anchor_ops.py:edit_claim_text` | `test_anchor_ops.py::test_edit_claim_keeps_a_list_item_a_list_item`, `::test_edit_claim_does_not_bullet_a_paragraph_claim` | **fixed** — a real model's wording fix turned a bullet into a paragraph (spec §E.2) |
| `supersede_claim`: predecessor frozen, successor gets system anchor + `supersedes` marker, one block, new evidence required | architecture §5, compile-contract §6 | `compile/anchor_ops.py:supersede_claim_text`, `compile/patch.py:PatchDraft.supersede_claim`, `:_refuse_superseded` | `test_supersession.py::test_supersede_keeps_the_old_claim_and_places_the_successor_right_after_it`, `::test_supersede_refuses_a_caller_minted_anchor_or_marker_and_multi_block_text`, `::test_supersede_refuses_a_successor_without_new_evidence`, `::test_a_superseded_claim_is_frozen_for_edit_and_for_a_second_supersession` | consistent |
| Supersession gate: 7 rejection kinds | architecture §5 | `compile/gate.py:check_supersession` | `test_supersession.py::test_gate_rejects_missing_target_self_reference_and_multiple_targets`, `::test_gate_rejects_two_successors_a_cycle_and_a_missing_citation`, `::test_gate_freezes_a_claim_that_was_already_superseded_in_the_base`, `::test_gate_accepts_a_legal_supersession_end_to_end` | **fixed** — docstring said "Six rejections" and listed seven |
| Current view / history chain derived from the marker alone | architecture §5 | `compile/supersession.py:current_blocks`, `:chains`, `:superseded_index` | `test_supersession.py::test_current_view_and_history_chain_are_derived_from_the_marker_alone` | consistent |
| **as-of** answer by cited-source dates | architecture §5 | `components/time.py:TimeComponent.as_of` (service) | `test_time_component.py::test_as_of_reports_the_chain_link_that_was_in_force_on_that_day` | **fixed** — §5 credited "the framework"; it is the `time` component's deep tool, and §5 now says so |
| `claim_superseded` event; brief narrates a state change | architecture §5 | `compile/transitions.py:derive_events`, `compile/brief.py:_EVENT_VERBS` | `test_supersession.py::test_events_narrate_a_state_change_not_an_addition` | consistent |
| Rollover: byte conservation, anchor survival, history card ≠ overview | architecture §5 | `compile/rollover.py:plan_rollover`, `compile/gate.py` rollover checks | `test_rollover.py`, `test_overview.py::test_a_rollover_carries_the_overview_region_across_untouched` | **fixed** — §5's "the overview below" became stale when the overview moved above rollover |
| Web: current/history toggle, marker never reaches prose | — | `apps/web/src/lib/supersession.ts`, `apps/web/src/views/library/LibraryView.tsx` | `apps/web/tests/supersession.test.mjs` (4 cases) | consistent (component itself untested — see gaps) |

## B. The overview

| mechanism | doc | code | test | status |
|---|---|---|---|---|
| Two parts: ledger + bounded head; four slots; system-written HTML markers | architecture §5, compile-contract §5 | `compile/documents.py:OVERVIEW_SLOTS`, `:render_overview`, `:overview_span` | `test_overview.py::test_render_and_parse_round_trip_through_the_region`, `::test_the_region_markers_are_structure_and_never_orphan_claims` | **fixed** — §5 was rewritten as one ledger→overview→supersession narrative instead of three appended paragraphs |
| `rewrite_overview`: whole region, fresh anchors, ledger byte-identical, frontmatter untouched, empty refused | architecture §5 | `compile/patch.py:PatchDraft.rewrite_overview` | `test_overview.py::test_rewrite_overview_replaces_the_region_and_leaves_the_ledger_byte_identical`, `::test_rewrite_overview_refuses_an_entirely_empty_overview`, `::test_rewrite_overview_refuses_a_rollover_volume` | consistent |
| Grounding gate: every block references a ledger claim anywhere in the library, or cites a source span; never another overview | architecture §5 | `compile/overview.py:check_overviews`, `:grounding_references`, `:ledger_anchors` | `test_overview.py::test_an_ungrounded_overview_block_is_rejected`, `::test_an_overview_may_ground_on_a_claim_in_another_document`, `::test_an_overview_may_not_ground_on_another_overview` | consistent |
| Grounding references normalized to bare anchors at the write boundary | architecture §5, `compile.tool.rewrite_overview` | `compile/overview.py:normalize_grounding_references`, `compile/patch.py:_bare_grounding` | `test_overview.py::test_a_dressed_up_ledger_reference_is_stored_as_a_bare_anchor`, `::test_a_real_source_citation_in_an_overview_survives_byte_for_byte` | **fixed** — a real model wrote `[cite: c:b05d47fc]` and burned four repair turns (spec §E.1) |
| Budget + `definition` length; unchanged region not re-judged; overview anchors exempt from continuity | architecture §5 | `compile/overview.py:OVERVIEW_BUDGET_CHARS`, `:DEFINITION_MAX_CHARS`; `compile/gate.py:run_gate` (`allowed_removals`) | `test_overview.py::test_an_over_budget_overview_is_rejected`, `::test_an_over_long_definition_is_rejected`, `::test_an_unchanged_region_is_not_re_judged`, `::test_overview_anchors_are_exempt_from_continuity_but_ledger_anchors_are_not` | consistent |
| `overview_rewritten` event; slot labels in projection; `definition` in outline + glance | architecture §5, §7 | `compile/transitions.py:derive_events`, `recall/projection.py:project_document_claims`, `canonical_glance.py:document_definition` | `test_overview.py::test_a_rewrite_yields_one_overview_event_and_no_claim_churn`, `::test_overview_claims_are_labelled_by_slot`, `::test_the_outline_and_the_glance_carry_the_definition_line`, `::test_without_an_overview_the_outline_and_glance_are_byte_identical` | consistent |
| `OVERVIEW_BUDGET_CHARS` knob | configuration.md | `settings.py:overview_budget_chars`, `engine/stage_map.py` | `test_engine_schema.py::test_committed_schema_is_exactly_what_the_code_derives` | consistent |
| Web overview card | — | `apps/web/src/lib/overview.ts`, `LibraryView.tsx:OverviewCard` | `apps/web/tests/overview.test.mjs` (4 cases) | consistent (card component untested — see gaps) |

## C. The index-component seam

| mechanism | doc | code | test | status |
|---|---|---|---|---|
| `IndexComponent` protocol; every face has a no-op default | architecture §6, design/index-components §3 | `components/__init__.py:IndexComponent`, `:BaseComponent` | `test_components.py::test_a_registered_component_reaches_gate_outline_and_tools` | consistent |
| `gate_checks` called | architecture §6 | `compile/gate.py:run_gate` | `test_components.py::test_a_registered_component_reaches_gate_outline_and_tools` | consistent |
| `outline_tail` called | architecture §6 | `canonical_glance.py:render_outline` | same as above | consistent |
| `protected_fields` refuses `set_fields` and names the tool | architecture §5 | `compile/patch.py:PatchDraft.set_fields` | `test_overview.py::test_set_fields_refuses_a_component_protected_field_and_names_its_tool` | consistent |
| `compile_tools(sources=)` gets THIS compile's sources, aliased | design/index-components §3 | `compile/runner.py` | `test_components.py::test_a_component_tool_is_built_with_this_compiles_sources_under_their_handles` | consistent |
| `source_preamble` rendered under a source | architecture §6 | `compile/runner.py:_render_task` | `test_components.py::test_a_registered_component_is_stamped_into_the_commit_trailer_and_may_add_a_source_preamble` | consistent |
| `prepare` runs at the head of a compile job, before any sync face | architecture §10, design §4 | `components/__init__.py:prepare_components` ← `compile/runner.py` | `test_runner.py::test_components_are_prepared_once_before_any_sync_face` | **fixed** — the docstring said "at the head of a job"; only compile jobs call it, and it now says which and why the others need nothing |
| `on_source_indexed` / `rebuild` — the projection channel | architecture §6, design §4 | `components/__init__.py:notify_source_indexed`, `:rebuild_components` ← `workers/compile_worker.py`, `scripts/ops/rebuild_derived.py` | `test_index_job_projection_channel.py::test_the_index_job_tells_every_component_the_source_is_ready`, `test_components.py::test_every_registered_component_is_told_a_source_was_indexed` | consistent |
| Fail-soft: a raising component never fails a job, a rebuild or a prepare | architecture §6 | the three `try/except` fan-outs in `components/__init__.py` | `test_components.py::test_a_component_that_raises_never_takes_the_job_or_the_rebuild_with_it`, `test_runner.py::test_a_component_whose_prepare_raises_does_not_fail_the_compile`, `test_index_job_projection_channel.py::test_a_component_that_raises_does_not_fail_the_index_job` | consistent |
| Nothing registered ⇒ every surface byte-identical | architecture §6 | absence by construction | `test_components.py::test_nothing_registered_means_every_surface_is_unchanged`, `::test_nothing_registered_means_the_projection_channel_is_a_no_op`, `test_index_job_projection_channel.py::test_with_no_component_registered_the_job_is_exactly_what_it_was` | consistent |
| **I7 — a component never writes canonical** | architecture §4, §9; design §2, §4 | `components/__init__.py:CanonicalReadOnly`; narrowed at `wiring.py:register_components` | `test_components.py::test_a_component_receives_a_canonical_face_with_no_way_to_write`, `test_people_component.py::test_registration_hands_a_component_a_canonical_face_it_cannot_write_through` | **fixed** — registration handed both components the full `CanonicalStore` (`commit_patch` one attribute away). The invariant held only by the shipped components' restraint; it is now a property of the object |
| Application registers by name; unknown name fails loudly | architecture §6, configuration.md | `wiring.py:register_components`, `settings.py:components`, `:people_family` | `test_people_component.py::test_register_components_enables_people_by_name_and_refuses_unknown_names` | consistent |
| `Components:` commit trailer | architecture §6 | `compile/runner.py:_with_skill_trailer` | `test_components.py::test_a_registered_component_is_stamped_into_the_commit_trailer_and_may_add_a_source_preamble` | consistent (write only; nothing reads the key back — noted, not a defect: it is a stamp) |
| Knobs in the engine schema | configuration.md, architecture §11 | `engine/stage_map.py` (`components`, `people_family`, `component_paths`, `component_budget_chars`, `overview_budget_chars`, `compile_call_timeout`) | `test_engine_schema.py::test_every_setting_is_either_an_engine_knob_or_classified_non_engine`, `::test_committed_schema_is_exactly_what_the_code_derives` | consistent |

## D. `people` and `time`

Service paths relative to `packages/pneuma-knowledge-service/src/pneuma_knowledge_service/`.

| mechanism | doc | code | test | status |
|---|---|---|---|---|
| `identities` unique library-wide, `scheme:value`; `aliases` only ever added | architecture §6, configuration.md, compile-contract §7 | `components/people.py:PeopleComponent.gate_checks` (`people.identity_shape`, `people.identity_duplicate`, `people.identities_removed`, `people.aliases_removed`) | `test_people_component.py::test_gate_rejects_a_duplicate_identity_a_bad_shape_and_a_shrinking_alias_list`, `::test_gate_accepts_growth_and_the_outline_shows_identities_and_aliases` | consistent |
| `find_person` / `bind_identity` (append-only) | architecture §6 | `components/people.py:PeopleComponent.compile_tools` | `test_people_component.py::test_find_person_matches_identity_alias_slug_or_title_exactly`, `::test_bind_identity_appends_to_an_existing_page_and_never_replaces` | consistent |
| `enumerate_identities` — closed set + visible residue, paginated | architecture §6, design §6 | `components/people.py:PeopleComponent.enumerate` | `test_people_component.py::test_enumerate_identities_reports_bound_pages_and_the_unbound_residue`, `::test_enumerate_identities_pages_and_states_how_to_continue` | consistent |
| `person_profile` + `person` fast path — whole page, current first, superseded labelled | architecture §7, design §6 | `components/people.py:person_claims`, `:person_profile` | `test_people_component.py::test_the_person_fast_path_returns_current_claims_first_then_superseded_history`, `::test_the_person_path_returns_the_whole_page_and_the_navigation_line_pages_it` | consistent |
| Address terms: CONCENTRATION not frequency (support ≥ 3, sources ≥ 2, share ≥ 0.6) | architecture §6, configuration.md, design §6 | `components/people.py:is_reported`, `:reported_terms`, `REPORT_MIN_*` | `test_people_component.py::test_a_term_is_reported_only_where_its_support_concentrates` | consistent |
| Reported vs *emerging* in the source preamble, both capped and the cut stated | architecture §6, design §5 | `components/people.py:PeopleComponent.source_preamble` | `test_people_component.py::test_the_source_preamble_separates_reported_terms_from_emerging_ones`, `::test_the_preamble_caps_both_lists_and_says_how_many_it_cut` | consistent |
| Accumulate-never-replace write; `rebuild` starts from nothing | architecture §4, configuration.md | `components/people.py:on_source_indexed`, `:rebuild`; `adapters/postgres.py:add_people_terms` | `test_people_component.py::test_the_projection_accumulates_across_sources_and_a_rebuild_starts_from_nothing`; `integration/test_component_people_pg.py::test_the_projection_accumulates_and_a_rebuild_reproduces_it_byte_for_byte` | consistent |
| Derived term resolves a name at READ time, no LLM; a canonical alias is only ever written by an ordinary compile | architecture §6, design §5 | `components/people.py:find_by_term`, `:_resolve_pages`; absence of any promotion path (`bind_identity` is the only writer; `protected_fields` blocks `set_fields`) | `test_people_component.py::test_find_person_resolves_a_reported_address_term_and_calls_the_match_derived`, `::test_a_canonical_alias_wins_the_lookup_and_is_never_labelled_derived` | consistent (the ABSENCE of a promotion path is not directly asserted — see gaps) |
| `people.prepare` warms the term mirror | design §4 | `components/people.py:PeopleComponent.prepare` | `test_people_component.py::test_a_fresh_component_renders_the_address_line_only_after_prepare` | consistent |
| `time` rows: UTC instant + subject-local day + zone + provenance | architecture §6, configuration.md | `components/time.py:time_rows` | `test_time_component.py::test_the_index_key_is_the_owners_day_even_when_the_utc_date_disagrees`, `::test_every_row_records_the_zone_it_was_normalized_under_and_where_it_came_from` | consistent |
| The day rules D1–D7 | design §6 | `components/time.py` module docstring | one test per rule (D1 `test_the_index_key_is_the_owners_day…`; D2 `test_a_zone_change_rewrites_nothing_until_an_explicit_rebuild`; D3 core `test_timespan.py::test_a_range_spanning_a_move_converts_each_end_with_its_own_zone`; D4 `test_a_colloquial_or_non_iso_day_never_reaches_the_index`; D5 `test_the_compile_preamble_renders_both_clocks_when_the_zones_differ`; D6 `test_as_of_reports_the_chain_link_that_was_in_force_on_that_day`) | **fixed** — the labels had drifted: the docstring enumerated only D1–D3, D4 sat inline, D5 lived in core, D7 existed only as a `schema.sql` comment, and D6 existed nowhere. One enumeration now lists all seven and names each rule's home. D7 (indexed range scan, not tenant scan) still has no test — see gaps |
| `timespan` fast path; `timeline` (incl. `verbatim`) and `as_of` deep tools; pagination ends with the exact call | architecture §7, design §6 | `components/time.py:timespan`, `:timeline`, `:as_of`; `components/pagination.py:navigation_line` | `test_time_component.py::test_timespan_groups_consecutive_blocks_of_one_source_per_day_and_orders_by_time`, `::test_timeline_pages_its_buckets_and_says_how_to_read_the_rest`, `::test_verbatim_reads_one_whole_day_block_by_block_and_refuses_a_range` | consistent |
| Never parses natural-language time | architecture §6, configuration.md, design §6 | `components/time.py:TimespanArgs._iso_only` → core `recall/timespan.py:parse_iso_day` | `test_time_component.py::test_a_colloquial_or_non_iso_day_never_reaches_the_index` | consistent |
| `time.prepare` warms the zone so a compile renders the OWNER's clock | design §4 | `components/time.py:TimeComponent.prepare` | `test_time_component.py::test_prepare_warms_the_zone_so_a_compile_renders_the_owners_clock` | **fixed** — a compile process rendered source times in the deployment default zone (spec §E.3) |
| PG schema matches the adapters; per-tenant isolation; user delete drops projections | configuration.md | `infra/schema.sql` (`component_time_blocks`, `component_people_terms`) vs `adapters/postgres.py` | `integration/test_component_time_pg.py::test_rows_round_trip_and_the_day_range_is_inclusive_at_both_ends`, `::test_deleting_a_user_takes_the_projection_with_it`; `integration/test_component_people_pg.py::test_the_projection_is_per_tenant_and_a_deleted_user_takes_it_with_them` | consistent |

## E. Fast recall — routed component paths

| mechanism | doc | code | test | status |
|---|---|---|---|---|
| `FastPath` shape (name, description, `args_schema`, cap, `run`) | architecture §7, design §7 | `recall/paths.py:FastPath` | `test_fast_paths.py::test_a_routed_path_runs_and_becomes_its_own_face_deduped_from_the_ranked_side` | **fixed** — the Protocol omitted `args_schema`, which `route_paths` requires and both shipped paths declare |
| ONE routing tool-call turn, never a loop | architecture §7 | `recall/paths.py:route_paths` | `test_fast_paths.py::test_a_routed_path_runs_and_becomes_its_own_face_deduped_from_the_ranked_side` | consistent |
| Chosen paths run concurrently; built-in retrieval never waits | architecture §7 | `recall/fast.py:fast_recall` (`asyncio.gather`), `recall/paths.py:run_paths` | `test_fast_paths.py::test_built_in_retrieval_does_not_wait_for_the_routing_turn` | consistent |
| A fourth evidence face under its own header, never RRF input | architecture §7, design §7 | `recall/paths.py:render_component_evidence`, `recall/fast.py:build_evidence_context` | `test_fast_paths.py::test_a_routed_path_runs_and_becomes_its_own_face_deduped_from_the_ranked_side` | consistent |
| Deterministic model-free ordering; reranker replaces the overlap term and fails soft | architecture §7, design §7 | `recall/component_rank.py:rank_candidates`, `recall/paths.py:rerank_component_evidence` | `test_component_evidence.py::test_a_cjk_question_ranks_the_claim_that_answers_it_first`, `::test_current_beats_superseded_at_equal_overlap_and_strong_words_still_win`, `::test_the_reranker_replaces_the_lexical_term_and_fails_soft_back_to_it`, `::test_a_failing_reranker_leaves_the_lexical_order_and_a_marker` | consistent |
| Cap under two floors, then a character budget over the whole face | architecture §7, design §7 | `recall/component_rank.py:apply_cap`; `recall/paths.py:cap_component_evidence`, `:budget_component_evidence` | `test_component_evidence.py::test_one_window_survives_even_a_cap_full_of_better_claims`, `::test_every_section_keeps_its_best_claim_before_any_section_gets_a_second`, `::test_the_character_budget_holds_the_whole_face_and_says_what_it_cost` | consistent |
| Honest truncation — described, not counted; excerpts cut at block boundaries naming what was lost | architecture §7, design §7 | `recall/component_rank.py:_summarize`, `:truncate_window`; `recall/paths.py:_fit_row` | `test_component_evidence.py::test_what_the_cap_dropped_is_described_per_section_not_merely_counted`, `::test_an_over_long_window_is_cut_at_a_block_boundary_that_names_the_lost_blocks` | consistent |
| Dedup never disturbs the ranked faces; `via:<path>` labelling | architecture §7, design §7 | `recall/paths.py:label_ranked_claims`, `:hide_already_shown`, `:fold_claims_into_windows` | `test_component_evidence.py::test_a_claim_whose_evidence_is_inside_a_window_of_the_same_face_is_folded_into_it`, `::test_one_address_returned_by_two_paths_is_shown_once_and_names_both` | consistent |
| `evidence_strategy=select`: component results join the numbered pool as their own group | architecture §7, design §7 | `recall/fast.py:component_candidate_pool`, `:select_evidence` | `test_component_evidence.py::test_the_selector_sees_component_results_as_a_group_it_can_pick_from`, `::test_invented_component_coordinates_are_rejected_like_every_other_index`, `::test_a_selector_failure_falls_back_to_the_rendered_component_face` | consistent |
| Telemetry reaches the answer and the wire | architecture §7, http-api.md | `recall/fast.py:FastAnswer` (`route_offered/route_chosen/route_degraded/…`), `api/routes/v1.py:RecallAnswerOut`, `apps/web/.../RecallView.tsx` | `test_fast_paths.py::test_invalid_and_unknown_calls_are_kept_as_audit_rows_not_run`, `::test_path_and_routing_failures_are_fail_soft_with_telemetry` | consistent (the HTTP echo itself has no test — see gaps) |
| No path offered ⇒ no routing call, byte-identical lane | architecture §7, design §7 | `recall/paths.py:route_paths`, `recall/fast.py` early return | `test_fast_paths.py::test_no_path_means_no_routing_call_and_identical_messages` | consistent |
| Claim face respects supersession independently of any component | architecture §7 | `recall/fast.py:mark_superseded_claims` | `test_fast_paths.py::test_superseded_claims_from_the_ranked_face_are_labelled_and_moved_last` | consistent |
| Deep's opposite discipline: pagination ends with the exact call that fetches the rest | architecture §7, design §7 | `components/pagination.py`, both components' `recall_tools` | `test_people_component.py::test_enumerate_identities_pages_and_states_how_to_continue`, `test_time_component.py::test_timeline_pages_its_buckets_and_says_how_to_read_the_rest` | consistent |

## F. Prompts and model-visible wording

| mechanism | doc | code | test | status |
|---|---|---|---|---|
| The catalog is a closed set: every key has an English default, a Chinese twin and a surface | architecture §6 | `prompts/catalog.py`, `prompts/lang_zh.py`, `prompts/surfaces.py` | `test_prompt_lang_zh.py::test_the_pack_covers_exactly_the_catalog_no_key_more_no_key_less`, `::test_every_translation_declares_exactly_its_originals_placeholders`, `::test_the_machine_read_tokens_are_not_translated`; `test_prompt_surfaces.py::test_every_catalog_key_belongs_to_at_least_one_surface`, `::test_no_surface_names_a_key_the_catalog_does_not_have` | consistent — **414 keys, closed in both directions across all three files**, including the 51 keys this work added (overview 9, supersession 14, component/recall-paths 12, routing 2, other 5, plus this pass's edits) |
| `rewrite_overview` states that ledger references are bare anchors | architecture §5 | `prompts/catalog.py:compile.tool.rewrite_overview` + zh twin | catalog closure tests above | **fixed** — the description invited `[cite: …]` for both kinds of reference |
| `recall/paths.py` and `recall/component_rank.py` model-visible strings are catalog-backed | — | every message goes through `prompt()`; `component_rank.py` has no model-visible string at all | catalog closure tests | consistent |
| Component tool descriptions state only where things come from and what the tool does | design §8, AGENTS discipline 1 | `components/people.py` (`bind_identity`, `find_person` miss text, `enumerate_identities`, the two preamble lines), `components/time.py` (`timespan`) | `test_people_component.py::test_find_person_points_at_the_address_evidence_of_this_compiles_sources` (asserts the new declarative wording) | **fixed** — 7 literals carried exhortation ("Bind a term as an alias only on high-confidence evidence… wait", "Call this before creating a person page", "judge each listed candidate", "resolve … yourself"). All rewritten declaratively; the *when to bind* judgement moved to the compile-contract guide, which is where judgement belongs |
| Component strings live in the prompt catalog | — | — | — | **gap** — see below |

## G. Invariants

| invariant | doc | mechanism | test | status |
|---|---|---|---|---|
| I1 user isolation | architecture §9, AGENTS | `user_id` first on every port method; per-user library and Meili index; tenant filter injected in the Qdrant adapter | throughout; component projections covered by `integration/test_component_*_pg.py` | consistent |
| I2 canonical vs derived | architecture §9 | distinct types; `rebuild_derived` rebuilds everything derived, component projections included | `test_components.py`, `integration/test_component_*_pg.py` | consistent |
| I3 L0/L1 unconditional | architecture §9 | — | — | consistent |
| I4 one addressing scheme | architecture §9 | one citation grammar, one parser; component candidates are ordinary anchors and spans | `test_fast_paths.py`, `test_component_evidence.py` | consistent |
| I5 byte-stable system message | architecture §9 | stable per enabled component set | `test_components.py::test_nothing_registered_means_every_surface_is_unchanged` | consistent |
| I6 eval never leaks into what it evaluates | architecture §9, AGENTS, CONTRIBUTING | the eval package is a leaf: `eval → core`, neither core nor service imports it | `tests/test_open_source_hygiene.py::test_the_eval_package_is_a_leaf_and_cannot_leak_into_what_it_judges` | **fixed** — architecture §9 listed five invariants while `AGENTS.md` cited "§9" for six; the mechanism was real but unpinned. §9 now lists it, and a test pins the import direction |
| I7 component projections are derived; a component never writes canonical | architecture §4, §9; AGENTS; CONTRIBUTING; design §2 | `CanonicalReadOnly` at registration + the projection channel's rebuild path | `test_components.py::test_a_component_receives_a_canonical_face_with_no_way_to_write`, `test_people_component.py::test_registration_hands_a_component_a_canonical_face_it_cannot_write_through` | **fixed** — added, and made mechanical first (see §C) |

---

## H. Cross-references repaired in passing

Adding two sections to the compile-contract guide moved its acceptance loop from §6 to §8,
and the audit turned up references that were already stale before that.

| reference | was | now |
|---|---|---|
| `docs/guides/evolution.md` / `.zh-CN.md` | `compile-contract.md#6-the-acceptance-loop` | `#8-…` |
| `examples/opc/README.md` / `.zh-CN.md` | `#5-the-acceptance-loop` | `#8-…` (already stale before this pass) |
| `compile/challenge.py` module docstring | "compile-contract.md §5" | §8 |
| `settings.py` (`challenge_enabled`) | "compile-contract.md §5" | §8 |
| `docs/reference/configuration.md` / `.zh-CN.md` | "Both are stated in `engine.yaml`" over a four-row table | names which two live in `engine.yaml` and which two in `recall/recall.yaml`, and links the new design doc |
| `api/routes/v1.py`, `apps/web/src/lib/api.ts` | `used_claims[].labels` "empty for the ranked faces" | states the `via:<path>` label that `merge_component_evidence` actually attaches to ranked claims |
| `api/routes/v1.py` | a comment naming `component_candidates` as if it were on the wire | says plainly that the pool size is not echoed |

`docs/architecture.md#6-the-compile-contract-skill` was deliberately NOT renamed, although
"the two extension seams" would have described the section better: three files link to that
anchor, two of them generated assets, and a section heading is an address. The framing lives
in the section's first line instead.

`tests/test_strategy_provenance.py`'s citation of "compile-contract §4" was checked and is
correct — it refers to §4 "Mechanism stays out".

---

## Gaps — listed, not fixed

Each needs real work rather than an in-place correction.

1. **Component prompt namespace.** The shipped components' model-visible strings are code
   literals: ~27 families across `components/people.py`, `components/time.py` and
   `components/pagination.py`. They have no catalog key, no Chinese twin, no surface entry
   and no closure test — the one part of the compile and recall prompt surface that a
   deployment cannot override and a language pack cannot translate. The wording was fixed in
   this pass (§F); the *namespace* is the open question. It is not a mechanical migration:
   components live in service, the catalog lives in core, and a component that ships outside
   this repository would need to register its own keys. Deciding that seam is the work.
2. **`rebuild_derived.py` has no test.** The per-component `rebuild` implementations are
   covered; the script that calls them — including `rebuild_components`' place in its order
   of operations — is not.
3. **The recall-lane registry call site is untested.** `recall/deep.py:_component_recall_tools`
   fans out over `registered_components()`; the components' `recall_tools` faces are tested
   directly, but nothing asserts that deep actually picks them up from the registry.
4. **The HTTP echo of route telemetry is untested.** `RecallAnswerOut`'s
   `route_offered` / `route_chosen` / `route_degraded` / `used_component_evidence` /
   `model_selected_component_items` are populated in `api/routes/v1.py` with no test over the
   response shape.
5. **Web components are untested above their parsing helpers.** `apps/web/tests/overview.test.mjs`
   and `supersession.test.mjs` cover `lib/overview.ts` and `lib/supersession.ts` thoroughly;
   `OverviewCard`, the current/history toggle in `LibraryView.tsx`, and `RecallView.tsx`'s
   routing line and component-evidence card have no test.
6. **D7 is unpinned.** "A day range is answered by an index on the day column, not by a scan
   of the tenant's blocks" is real (`component_time_blocks_day`), but no test would notice if
   the index were dropped. A cheap fix exists (assert the index in the integration schema
   check); it is listed rather than done because it belongs with a broader look at what the
   schema tests should assert.
7. **The absence of an alias promotion path is asserted only indirectly.** That a derived
   address term can never become a canonical `alias` except through `bind_identity` in an
   ordinary compile is the design's load-bearing claim (§5 of the design doc). It holds by
   construction — `bind_identity` is the only writer and `set_fields` refuses the field — but
   no test asserts the absence, and absences are exactly what regress silently.
8. **`adapters/postgres.py:people_terms(user_id, terms=None)`** carries an optional filter no
   caller uses. Harmless, documented, and either a future need or dead weight; left alone
   rather than removed blind.
9. **Three telemetry fields are set in core and never reach the wire.**
   `FastAnswer.component_candidates` (the pool `model_selected_component_items` is drawn
   from — the only one of the four candidate-pool counts not echoed),
   `FastAnswer.component_rerank_degraded`, and `ComponentEvidence.covered_by_windows` are
   computed and then dropped at the API boundary. The misleading comment that named
   `component_candidates` as if it were on the wire was corrected in place; exposing the
   three fields is an API change and is left listed.
10. **`people` indexes nothing on the scaffold's own ingest path.** The generated project's
    `.md` importer (`scaffold/templates/app.py:_ingest`) passes `meta={"occurred_on": …}` and
    nothing else — no participant list, no user list, even for `type: conversation`. The
    `people` component reads identities and address-term targets exclusively off those meta
    lists, with no fallback to transcript speaker names, so a scaffold-born library that
    enables `people` gets an empty projection. `time` degrades gracefully instead (a `date:`
    frontmatter yields day-granularity rows; only per-block instants buy within-day
    precision). `scaffold/AGENT-GUIDE.md` now says this plainly rather than implying the
    switch is enough; closing it properly means the scaffold importer emitting the source
    contracts' identity fields.
11. **Nothing reads the `Components:` commit trailer.** It is written and tested as a stamp,
   and `commit_trailer` can read arbitrary keys, but no code path consumes it — so a commit
   produced by a different component set is attributable by hand, not by tooling.
