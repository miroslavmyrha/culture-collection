# Compliance: regulated material

Every rule the app enforces about regulated material (VRAT and RAT agents, dual-use items,
Union quarantine pests, GMOs and risk groups), with what it rests on, where the code enforces it
and which tests prove it. Then the legal duties the app does not enforce yet, with their issues,
and the questions put to an authority that are still open.

## How to read this document

Each rule has a stable id, `R-<area>-<nn>`, and these fields:

- **Kind**: one of
  - `law`: a legal text puts the duty on the collection, and the code enforces it;
  - `law in part`: part of the rule is such a duty, the rest is a choice of our own (both are
    named);
  - `own control`: no legal text read puts this duty on the collection. The source is an ADR, a
    guidance document, the practice of other collections, or another party's legal duty the app
    checks;
  - `not verified`: the rule rests on a text that was not read in the original (only through a
    study or a summary), so no sentence of it is quoted as fact.
- **Source**: the act or regulation and its section, or the ADR or guidance.
- **Quote**: the sentence in the original language, copied from the official text. Required for
  `law` and `law in part`. Czech quotes come from the consolidated texts of e-Sbírka (act
  281/2002 Sb. in force from 2022-02-01, act 78/2004 Sb. from 2025-07-01, act 326/2004 Sb. from
  2025-04-01, decree 474/2002 Sb. from 2026-01-01, decree 209/2004 Sb. from 2020-01-01), with the
  space the export puts before a comma after a link removed. EU quotes come from the texts on
  EUR-Lex: Directive 2000/54/EC, Regulation (EU) 2016/2031, Implementing Regulation (EU) 2019/829,
  Regulation (EU) 2021/821 and Delegated Regulation (EU) 2025/2003.
- **English**: a translation of a Czech quote.
- **Code**: where the rule is enforced, as `path::symbol` (a function, class or constant of that
  file) or `path::"text"` (a database constraint or trigger named in a string of that file,
  usually a migration).
- **Tests**: the tests that prove the rule, as `path::test_name`.
- **Gate codes**: the codes of `distribution.policy.gate_codes()` the rule answers with.
- **Limits**: where the rule is weaker or wider than its source, with the issue that closes it.

Only backend tests are named. The server enforces every rule here, in a service, a constraint or
a trigger. The screens explain the rules and hide actions that would be refused, and their tests
live with the screens.

## How this document is kept true

`backend/cultures/core/tests/test_compliance.py` reads this file and fails when:

- a rule names a code path or symbol that does not exist;
- a rule names a test that does not exist, or a test that does not carry the rule's id;
- a test carries a rule id (`@pytest.mark.rule("R-...")`) that has no rule here, or carries the
  id of a rule that does not name it;
- a rule of kind `law` or `law in part` has no quoted sentence;
- an id appears twice;
- a gate code of `distribution.policy.gate_codes()` is in no rule and not in the list of gates
  that are not about regulated material, or a listed gate code does not exist;
- a duty or a rule that breaks a source names no issue (write `none` when there is none).

The test reads the source files, it does not import the tests, so it runs in a second. In the
development container `docs/` is mounted read-only at `/docs` (`compose.yaml`).

To change a rule: change the code and its tests, then the rule here, in the same commit. To add
one: give it the next free id of its area (ids are never reused), write its fields, and mark each
test that proves it with `@pytest.mark.rule("<id>")` (one marker may carry several ids). A rule
that ends keeps its heading with Kind `own control` and the line "Ended: <date>, <why>", or moves
to the duties when the law still asks it. A duty that gets built becomes a rule and leaves the
duties. An answer from an authority is written into its question with the day and the reference,
and the rules and duties it decides are changed in the same commit.

## Rules enforced

### Classification of a strain

#### R-KIND-01 A strain carries any number of restrictions of five kinds

- Kind: own control
- Source: ADR 0009, Context: the kinds name the lists a strain can be on (decree 474/2002 Sb.
  Annexes 1 and 2, Regulation (EU) 2021/821 Annex I, Implementing Regulation (EU) 2019/2072 Annex
  II, act 78/2004 Sb.). Which lists the app models is a scope choice.
- Code: `backend/cultures/biosafety/models.py::RestrictionKind`, `backend/cultures/strains/models.py::"strains_restriction_kind_valid"`
- Tests: `backend/cultures/strains/tests/test_models.py::test_a_restriction_has_the_fields_of_its_kind`, `backend/cultures/strains/tests/test_models.py::test_restrictions_of_the_right_shape_are_stored`
- Limits: every restriction is typed by a person. No official list is held and the taxon is not
  consulted (#169).

#### R-KIND-02 A dual-use restriction names an entry of 1C351, 1C353 or 1C354

- Kind: own control
- Source: Regulation (EU) 2021/821, Annex I, entries 1C351 (human and animal pathogens and
  toxins), 1C353 (genetic elements and genetically modified organisms), 1C354 (plant pathogens).
  The pattern is a data rule of our own.
- Code: `backend/cultures/strains/models.py::DUAL_USE_ENTRY`, `backend/cultures/strains/services.py::check_restriction`, `backend/cultures/strains/models.py::"strains_restriction_dual_use_entry"`
- Tests: `backend/cultures/strains/tests/test_models.py::test_a_restriction_has_the_fields_of_its_kind`
- Limits: the pattern accepts entries the annex does not have: 1C351.b reads "b. Not used;" in
  Annex I as replaced by Delegated Regulation (EU) 2025/2003. The entry is not checked against
  the annex (#169).

#### R-KIND-03 A dual-use restriction names the delegated act its annex was read in

- Kind: own control
- Source: ADR 0009, Decision: Annex I of Regulation (EU) 2021/821 is replaced by a delegated act
  about once a year, so an entry is only meaningful with the act it was read in.
- Code: `backend/cultures/strains/models.py::EU_ACT`, `backend/cultures/strains/services.py::check_restriction`, `backend/cultures/strains/models.py::"strains_restriction_act_iff_dual_use"`
- Tests: `backend/cultures/strains/tests/test_models.py::test_a_restriction_has_the_fields_of_its_kind`

#### R-KIND-04 A GMO restriction has a category of risk I to IV, no other kind has one

- Kind: law
- Source: act 78/2004 Sb., § 15(1), § 16(2)
- Quote: „Výsledkem hodnocení rizika je v případě uzavřeného nakládání zařazení tohoto nakládání do jedné z kategorií rizika uvedených v příloze č. 3 k tomuto zákonu.“
- English: The result of the risk assessment of a contained use is its classification into one
  of the categories of risk of Annex 3 of this act (§ 16(2) names the first to fourth category).
- Code: `backend/cultures/strains/services.py::check_restriction`, `backend/cultures/strains/models.py::"strains_restriction_category_iff_gmo"`
- Tests: `backend/cultures/strains/tests/test_models.py::test_a_restriction_has_the_fields_of_its_kind`, `backend/cultures/strains/tests/test_models.py::test_restrictions_of_the_right_shape_are_stored`

#### R-KIND-05 One active restriction per strain, kind and entry

- Kind: own control
- Source: a data rule of our own.
- Code: `backend/cultures/strains/models.py::ACTIVE_RESTRICTION_UNIQUE`, `backend/cultures/strains/services.py::strain_restriction_add`
- Tests: `backend/cultures/strains/tests/test_models.py::test_one_active_restriction_of_a_kind_and_entry_per_strain`, `backend/cultures/strains/tests/test_services.py::test_a_restriction_twice_is_a_field_error`

#### R-KIND-06 A restriction is never deleted and ends once, with a reason

- Kind: own control
- Source: ADR 0009 (history is kept). Decree 474/2002 Sb. § 5(2) a) asks the same of the
  register book, not of a classification.
- Code: `backend/cultures/strains/migrations/0005_end_proposal_audit_and_guards.py::"strains_restriction_guard"`, `backend/cultures/strains/models.py::"strains_restriction_end_has_reason"`
- Tests: `backend/cultures/strains/tests/test_models.py::test_a_restriction_only_ends_once`, `backend/cultures/strains/tests/test_services.py::test_a_restriction_ends_once`

#### R-KIND-07 A restriction ends only by two people: a proposal and a confirmation by another manager

- Kind: own control
- Source: ADR 0009, amendment 2026-10-24 (#105). No law read asks it.
- Code: `backend/cultures/strains/services.py::strain_restriction_end_propose`, `backend/cultures/strains/services.py::strain_restriction_end_confirm`, `backend/cultures/strains/services.py::ConfirmOwnEndProposal`, `backend/cultures/strains/migrations/0010_confirmed_proposal_outcome.py::"strains_endproposal_confirmed"`
- Tests: `backend/cultures/strains/tests/test_end_proposals.py::test_nobody_confirms_their_own_proposal`, `backend/cultures/strains/tests/test_end_proposals.py::test_a_restriction_ends_only_at_a_confirmed_proposal`, `backend/cultures/strains/tests/test_end_proposals.py::test_the_runtime_role_cannot_confirm_an_end_that_did_not_happen`, `backend/cultures/strains/tests/test_end_proposals.py::test_a_curator_alone_no_longer_lets_a_vrat_out_of_its_rules`

#### R-KIND-08 A restriction is added by one person who manages strains, with a reason

- Kind: own control
- Source: our own. Adding a restriction only tightens the rules, so one person suffices, while
  its end takes two (R-KIND-07).
- Code: `backend/cultures/strains/services.py::strain_restriction_add`
- Tests: `backend/cultures/strains/tests/test_services.py::test_a_curator_adds_a_restriction_and_it_ends_by_two_people`

#### R-KIND-09 A strain is regulated while it has any active restriction, one definition in Python and SQL

- Kind: own control
- Source: ADR 0009, Decision: "A strain with any restriction is a regulated strain in this ADR".
- Code: `backend/cultures/strains/selectors.py::regulating_restrictions`, `backend/cultures/strains/migrations/0009_deaccession_audit_and_guards.py::"strains_strain_guard"`, `backend/cultures/lineage/migrations/0010_vial_guard_regulated_destroy.py::"lineage_vial_guard"`
- Tests: `backend/cultures/strains/tests/test_deaccession.py::test_the_trigger_and_the_python_predicate_agree_on_regulated`, `backend/cultures/lineage/tests/test_vial_states.py::test_the_trigger_and_the_service_agree_with_the_python_predicate_on_destruction`

### Risk groups

#### R-RISK-01 A risk group is one of the four groups

- Kind: law
- Source: Directive 2000/54/EC, Art. 2, second paragraph (Czech: government order 361/2007 Sb.)
- Quote: "'Biological agents' shall be classified into four risk groups, according to their level of risk of infection"
- Code: `backend/cultures/strains/models.py::"strains_strain_risk_group_1_to_4"`
- Tests: `backend/cultures/strains/tests/test_models.py::test_risk_groups_one_to_four_are_stored`, `backend/cultures/strains/tests/test_models.py::test_a_strain_row_that_cannot_be_true_is_refused`
- Limits: the group is typed by a person, not read from the annex of the directive or of the
  government order (#169).

#### R-RISK-02 A risk group 4 agent is refused at accession and on change

- Kind: own control
- Source: ADR 0009, Decision: "A risk group 4 strain is refused at accession, and so is a later
  change of a strain's risk group to 4". No law read forbids holding one under containment
  level 4.
- Code: `backend/cultures/strains/services.py::_check_risk_group`, `backend/cultures/strains/services.py::RiskGroupRefused`
- Tests: `backend/cultures/strains/tests/test_services.py::test_a_risk_group_4_agent_is_refused_on_its_field`, `backend/cultures/strains/tests/test_services.py::test_a_change_to_risk_group_4_is_refused`, `backend/cultures/deposits/tests/test_services.py::test_a_risk_group_4_agent_is_refused_at_acceptance`

#### R-RISK-03 A risk group changes by one person who manages strains, with a reason

- Kind: own control
- Source: our own.
- Code: `backend/cultures/strains/services.py::strain_set_risk_group`
- Tests: `backend/cultures/strains/tests/test_services.py::test_a_risk_group_change_records_old_new_and_the_reason`, `backend/cultures/strains/tests/test_services.py::test_a_risk_group_change_needs_a_reason`, `backend/cultures/strains/tests/test_services.py::test_the_same_risk_group_again_records_nothing`
- Limits: one person also lowers a group, which relaxes R-SHIP-03, R-DIST-10 and R-DIST-12.
  Lowering by two people is #174.

#### R-RISK-04 A higher risk group must fit the cap of every box holding the strain

- Kind: own control
- Source: ADR 0009, the `may_store` gate.
- Code: `backend/cultures/strains/services.py::_check_boxes_hold`, `backend/cultures/strains/services.py::RiskGroupAboveBoxCap`
- Tests: `backend/cultures/lineage/tests/test_risk_group_caps.py::test_raising_above_the_cap_of_one_of_several_boxes_is_refused`, `backend/cultures/lineage/tests/test_risk_group_caps.py::test_lowering_always_fits`, `backend/cultures/lineage/tests/test_risk_group_caps.py::test_the_api_refusal_names_no_box`

#### R-RISK-05 Pathogenicity for animals and for plants is recorded apart from the risk group

- Kind: own control
- Source: ADR 0009, Decision: the risk group rates harm to humans only.
- Code: `backend/cultures/strains/models.py::Pathogenicity`, `backend/cultures/strains/models.py::"strains_strain_pathogenicity_valid"`
- Tests: `backend/cultures/strains/tests/test_models.py::test_a_strain_row_that_cannot_be_true_is_refused`
- Limits: no gate reads it. See C-01 below (#173).

### The lab's own permits

#### R-PERMIT-01 A VRAT strain enters a lab only while the lab holds a valid SÚJB permit

- Kind: law
- Source: act 281/2002 Sb., § 6(1). "Úřad" is SÚJB (§ 3(1)).
- Quote: „Nakládat s vysoce rizikovými biologickými agens a s toxiny na území České republiky lze jen na základě povolení vydaného Úřadem…“
- English: Highly risky biological agents and toxins may be handled in the Czech Republic only
  under a permit issued by the Office.
- Code: `backend/cultures/biosafety/policy.py::require_authorisation`, `backend/cultures/strains/services.py::strain_create`, `backend/cultures/strains/services.py::strain_restriction_add`
- Tests: `backend/cultures/biosafety/tests/test_policy.py::test_no_permit_refuses_with_the_field_and_the_kind`, `backend/cultures/biosafety/tests/test_policy.py::test_a_permit_of_another_kind_does_not_count`, `backend/cultures/biosafety/tests/test_policy.py::test_a_permit_of_another_lab_does_not_count`, `backend/cultures/strains/tests/test_services.py::test_a_vrat_or_quarantine_strain_enters_with_a_valid_permit`, `backend/cultures/strains/tests/test_services.py::test_an_added_vrat_restriction_needs_the_permit_too`
- Limits: any valid VRAT permit of the lab counts. The permit fixes the kinds and quantities of
  agents (§ 11(3) d)), and the app does not hold them. See D-01 (#170).

#### R-PERMIT-02 A quarantine pest strain enters a lab only while the lab holds a valid ÚKZÚZ authorisation

- Kind: law
- Source: Regulation (EU) 2016/2031, Art. 5(1) and Art. 8(1). In the Czech Republic ÚKZÚZ
  decides on it, act 326/2004 Sb., § 8(1).
- Quote: "A Union quarantine pest shall not be introduced into, moved within, or held, multiplied or released in, the Union territory." and "By way of derogation from Article 5(1), Member States may, on application, temporarily authorise the introduction into, the movement within, and the holding and multiplication in, their territory of Union quarantine pests … for official testing, scientific or educational purposes, trials, varietal selections, or breeding."
- Code: `backend/cultures/biosafety/policy.py::require_authorisation`, `backend/cultures/strains/services.py::strain_create`, `backend/cultures/strains/services.py::strain_restriction_add`
- Tests: `backend/cultures/strains/tests/test_services.py::test_without_a_valid_permit_of_its_kind_in_its_lab_the_strain_is_refused`, `backend/cultures/strains/tests/test_services.py::test_a_vrat_or_quarantine_strain_enters_with_a_valid_permit`
- Limits: any valid ÚKZÚZ authorisation of the lab counts. The authorisation names the pest
  (2019/829 Annex II: "including scientific name of the specified pest concerned"), and the app
  does not match it. See D-01.

#### R-PERMIT-03 The lab permit gate reads only the two kinds a permit is recorded for

- Kind: own control
- Source: ADR 0009, Lab authorisation: VRAT and quarantine pests need a permit of the lab. A RAT
  needs a notice of the lab to SÚJB (act 281/2002 Sb., § 17a(1)) and a GMO a notification or
  permit of contained use (act 78/2004 Sb., § 4(2)), which the app does not record.
- Code: `backend/cultures/biosafety/policy.py::NEEDS_PERMIT`, `backend/cultures/biosafety/models.py::AuthorisationKind`
- Tests: `backend/cultures/biosafety/tests/test_policy.py::test_kinds_without_a_permit_need_none`, `backend/cultures/strains/tests/test_services.py::test_kinds_without_a_permit_need_none`
- Limits: a RAT or GMO strain enters any lab. See D-03 and D-04.

#### R-PERMIT-04 A VRAT permit is issued by SÚJB and a quarantine authorisation by ÚKZÚZ

- Kind: law
- Source: act 281/2002 Sb., § 3(1) and § 6(1); act 326/2004 Sb., § 4(1) and § 8(1)
- Quote: „Státní správu v oblasti dodržování zákazu bakteriologických (biologických) a toxinových zbraní vykonává Státní úřad pro jadernou bezpečnost (dále jen „Úřad“)…“ and „Ústav na základě žádosti … rozhoduje o povolení dovozu, přemísťování v rámci území České republiky, držení a množení karanténního materiálu…“
- English: State administration of the ban on biological and toxin weapons is carried out by the
  State Office for Nuclear Safety (the Office). The Institute (ÚKZÚZ, act 326/2004 Sb., § 4(1))
  decides on application on permits to import, move within the Czech Republic, hold and multiply
  quarantine material.
- Code: `backend/cultures/biosafety/models.py::ISSUER_OF`, `backend/cultures/biosafety/models.py::"biosafety_labauthorisation_kind_issuer"`
- Tests: `backend/cultures/biosafety/tests/test_models.py::test_each_kind_has_its_issuer_and_no_other_kind_is_a_permit`

#### R-PERMIT-05 A permit is valid on Czech calendar days

- Kind: own control
- Source: our reading, in the module docstring of `biosafety/policy.py`: the permits are issued
  by Czech authorities and state their dates in local time. No text read states it.
  `expires_on` is the last valid day, `ended_on` the first invalid one.
- Code: `backend/cultures/biosafety/policy.py::permit_today`, `backend/cultures/biosafety/policy.py::valid_on`
- Tests: `backend/cultures/biosafety/tests/test_policy.py::test_validity_follows_the_dates`, `backend/cultures/biosafety/tests/test_policy.py::test_the_day_is_the_day_in_prague`

#### R-PERMIT-06 A lab permit is never deleted, and an end has a reason

- Kind: own control
- Source: ADR 0009, Lab authorisation: "which permit did the lab hold on that day" stays a query.
- Code: `backend/cultures/biosafety/services.py::authorisation_end`, `backend/cultures/biosafety/models.py::"biosafety_labauthorisation_end_has_reason"`, `backend/cultures/biosafety/models.py::"biosafety_labauthorisation_expires_after_start"`
- Tests: `backend/cultures/biosafety/tests/test_models.py::test_an_end_date_comes_with_a_reason_and_only_then`, `backend/cultures/biosafety/tests/test_models.py::test_the_expiry_is_not_before_the_start`

#### R-PERMIT-07 A lab permit that expires within 30 days is listed for the managers

- Kind: own control
- Source: a planning choice. The code cites act 500/2004 Sb., § 71(3) (30 days for a decision of
  an authority): not verified, the text is not among the sources read.
- Code: `backend/cultures/biosafety/policy.py::EXPIRES_SOON_DAYS`, `backend/cultures/biosafety/selectors.py::permit_list`, `backend/cultures/overview/selectors.py::_expiring`
- Tests: `backend/cultures/overview/tests/test_waiting.py::test_a_lab_permit_waits_for_managers_within_thirty_days_of_its_expiry`, `backend/cultures/biosafety/tests/test_api.py::test_what_expires_soon_comes_first_and_the_history_last`

### Where regulated material is stored

#### R-MASK-01 A regulated vial's location is masked in every list, detail and write answer

- Kind: own control
- Source: ADR 0009, amendment 2026-10-19. WHO Laboratory biosecurity guidance (2024), 6.3.1:
  "The inventory of high-consequence material should be treated as sensitive information" (a
  guidance, not a law).
- Code: `backend/cultures/lineage/services/locations.py::is_regulated`, `backend/cultures/lineage/services/locations.py::location_of`, `backend/cultures/lineage/selectors.py::_regulated`
- Tests: `backend/cultures/lineage/tests/test_masking.py::test_lists_and_details_never_carry_a_regulated_location`, `backend/cultures/lineage/tests/test_masking.py::test_moving_a_regulated_vial_shows_neither_where_it_was_nor_where_it_went`, `backend/cultures/lineage/tests/test_masking.py::test_one_ended_and_one_active_restriction_stay_masked`

#### R-MASK-02 A reveal needs a location grant of the person, and its event is committed before the location is read

- Kind: own control
- Source: ADR 0009, amendment 2026-10-19.
- Code: `backend/cultures/lineage/services/locations.py::vial_reveal_location`, `backend/cultures/labs/services.py::holds_location_grant`
- Tests: `backend/cultures/lineage/tests/test_masking.py::test_without_the_grant_no_role_reveals`, `backend/cultures/lineage/tests/test_masking.py::test_a_holder_of_the_grant_reveals_and_the_reveal_is_recorded`, `backend/cultures/lineage/tests/test_masking.py::test_a_failed_event_write_fails_the_reveal_without_the_location`, `backend/cultures/lineage/tests/test_masking.py::test_the_reveal_is_committed_before_the_location_is_read`, `backend/cultures/lineage/tests/test_masking.py::test_no_role_implies_the_grant`

#### R-MASK-03 Location grants are rows, revoked once and never deleted, and revoked with the membership

- Kind: own control
- Source: ADR 0009, amendment 2026-10-19.
- Code: `backend/cultures/labs/services.py::location_grant_revoke`, `backend/cultures/labs/services.py::membership_delete`, `backend/cultures/labs/migrations/0004_locationgrant_audit_and_guard.py::"labs_locationgrant_guard"`
- Tests: `backend/cultures/labs/tests/test_location_grants.py::test_a_grant_is_revoked_once`, `backend/cultures/labs/tests/test_location_grants.py::test_removing_the_member_revokes_the_grant_in_the_same_transaction`, `backend/cultures/labs/tests/test_location_grants.py::test_one_open_grant_per_person_and_lab`
- Limits: this is the grant to see a stored location, not the list of people with access to the
  agent (act 281/2002 Sb., § 14a(4)): that is R-ACCESS-01. The two are not linked.

#### R-MASK-04 The box grid shows a regulated position as taken and names nothing

- Kind: own control
- Source: ADR 0009, amendment 2026-10-20 (#15).
- Code: `backend/cultures/lineage/selectors.py::box_positions`
- Tests: `backend/cultures/lineage/tests/test_box_grid.py::test_a_regulated_position_is_taken_but_names_nothing`, `backend/cultures/lineage/tests/test_box_grid.py::test_a_regulated_vial_found_by_its_code_keeps_its_place_masked`

#### R-MASK-05 Only managers read the reveal log

- Kind: own control
- Source: ADR 0009, amendment 2026-10-27 (#83).
- Code: `backend/cultures/lineage/selectors.py::reveal_list`, `backend/cultures/labs/permissions.py::Perm.VIEW_REVEALS`
- Tests: `backend/cultures/lineage/tests/test_reveal_log.py::test_only_managers_read_the_log`, `backend/cultures/lineage/tests/test_reveal_log.py::test_a_holder_of_the_grant_does_not_read_the_log`, `backend/cultures/lineage/tests/test_reveal_log.py::test_the_answer_holds_no_location_anywhere`, `backend/cultures/lineage/tests/test_reveal_log.py::TestFilters::test_a_month_is_its_czech_days`

### Who has access to VRAT agents

#### R-ACCESS-01 The lab keeps the list of the people with access to its VRAT agents, with its history

- Kind: law in part
- Source: act 281/2002 Sb., § 14a(4); the offence § 21a(2) f). ADR 0009, amendment 2026-11-03
  (#167). What an entry holds (from, until, who decided, a reason both ways) is our own choice:
  the act states no form or content.
- Quote: „Držitel povolení je povinen vytvořit a aktualizovat seznam osob, které mají přístup k vysoce rizikovému biologickému agens nebo toxinu.“
- English: the permit holder makes and keeps up to date a list of the people who have access to
  a highly risky agent or toxin.
- Code: `backend/cultures/labs/services.py::vrat_access_grant`, `backend/cultures/labs/services.py::vrat_access_end`, `backend/cultures/labs/selectors.py::vrat_access_list`, `backend/cultures/labs/selectors.py::has_vrat_access`, `backend/cultures/labs/migrations/0006_vrataccess_audit_and_guards.py::"labs_vrataccess_guard"`, `backend/cultures/labs/models.py::"labs_vrataccess_one_open"`
- Tests: `backend/cultures/labs/tests/test_vrat_access.py::test_a_manager_puts_a_member_on_the_list_and_takes_them_off_with_reasons_and_events`, `backend/cultures/labs/tests/test_vrat_access.py::test_only_a_manager_puts_on_and_takes_off`, `backend/cultures/labs/tests/test_vrat_access.py::test_a_reason_is_required_both_ways`, `backend/cultures/labs/tests/test_vrat_access.py::test_an_entry_ends_once`, `backend/cultures/labs/tests/test_vrat_access.py::test_one_open_entry_per_person_and_lab`, `backend/cultures/labs/tests/test_vrat_access.py::test_an_entry_changes_only_when_it_ends_and_is_never_deleted`, `backend/cultures/labs/tests/test_vrat_access.py::test_an_ended_entry_is_never_reopened`, `backend/cultures/labs/tests/test_vrat_access.py::test_the_runtime_role_puts_on_and_ends_but_deletes_nothing`, `backend/cultures/labs/tests/test_vrat_access.py::test_has_vrat_access_answers_for_a_moment_before_during_and_after`, `backend/cultures/labs/tests/test_vrat_access.py::test_only_managers_see_and_change_the_list`
- Limits: the list of the people with access to the workplace (§ 14a(5)) is D-17, the yearly
  training (§ 14a(6)) D-18. Nothing requires the lab to hold a VRAT permit to keep the list.

#### R-ACCESS-02 Only an active member of the lab is on the list: leaving the lab, deactivation and erasure end the entry

- Kind: own control
- Source: ADR 0009, amendment 2026-11-03 (#167). The act names no condition; a person without an
  account or outside the lab cannot be checked by the app.
- Code: `backend/cultures/labs/services.py::vrat_access_end_for_users`, `backend/cultures/labs/services.py::membership_delete`, `backend/cultures/users/services.py::user_deactivate`, `backend/cultures/users/services.py::users_deactivate`, `backend/cultures/users/services.py::user_erase`, `backend/cultures/labs/migrations/0006_vrataccess_audit_and_guards.py::"labs_vrataccess_holder_deactivated"`, `backend/cultures/labs/migrations/0006_vrataccess_audit_and_guards.py::"labs_vrataccess_member_left"`
- Tests: `backend/cultures/labs/tests/test_vrat_access.py::test_only_an_active_member_goes_on_the_list`, `backend/cultures/labs/tests/test_vrat_access.py::test_removing_the_member_ends_the_entry_in_the_same_transaction`, `backend/cultures/labs/tests/test_vrat_access.py::test_deactivating_the_user_ends_every_entry_in_the_same_transaction`, `backend/cultures/labs/tests/test_vrat_access.py::test_deactivating_many_users_ends_their_entries`, `backend/cultures/labs/tests/test_vrat_access.py::test_erasing_the_user_ends_the_entry_and_keeps_it_under_the_tombstone`, `backend/cultures/labs/tests/test_vrat_access.py::test_the_database_puts_only_an_active_member_on_the_list`, `backend/cultures/labs/tests/test_vrat_access.py::test_a_deactivation_past_the_service_with_an_open_entry_fails_at_commit`, `backend/cultures/labs/tests/test_vrat_access.py::test_a_membership_deleted_past_the_service_with_an_open_entry_fails_at_commit`

### Distribution: request, approval and gates

#### R-DIST-01 Nothing goes to a requester outside the EU

- Kind: law in part
- Source: for a dual-use item, Regulation (EU) 2021/821, Art. 3(1): the export needs an
  authorisation this collection does not hold. For VRAT, act 281/2002 Sb., § 14(8) asks an
  end-user statement the app does not record. For every other strain a scope choice (ADR 0009,
  amendment 2026-10-20), stricter than the law. The 27 member states as read on
  european-union.europa.eu on 2026-10-20.
- Quote: "An authorisation shall be required for the export of dual-use items listed in Annex I."
- Code: `backend/cultures/distribution/policy.py::EU_MEMBER_STATES`, `backend/cultures/distribution/policy.py::destination_finding`, `backend/cultures/distribution/services/requests.py::request_submit`
- Tests: `backend/cultures/distribution/tests/test_api.py::test_a_request_to_a_requester_outside_the_eu_is_refused_at_entry`, `backend/cultures/distribution/tests/test_policy.py::test_the_destination_and_an_erased_contact_block_the_whole_request`, `backend/cultures/distribution/tests/test_policy.py::test_the_eu_is_its_27_member_states`
- Gate codes: `export_of_regulated_strain`, `export_not_supported`

#### R-DIST-02 Only an institution receives material: a legal person or a natural person licensed to do business

- Kind: law in part
- Source: for a GMO, act 78/2004 Sb., § 16(1) with § 3(1) c) (a transfer to anyone not
  authorised for contained use is placing on the market). For the other kinds the practice of
  the collections read (ADR 0008, amendment 2026-10-20).
- Quote: „Oprávnění k uzavřenému nakládání může vzniknout pouze právnické osobě nebo fyzické osobě oprávněné k podnikání.“
- English: An authorisation for contained use can only be held by a legal person or a natural
  person licensed to do business.
- Code: `backend/cultures/distribution/models.py::LegalForm`, `backend/cultures/distribution/models.py::"distribution_requester_legal_form_valid"`
- Tests: `backend/cultures/distribution/tests/test_models.py::test_requester_constraints`

#### R-DIST-03 A regulated line needs a manager's approval with a reason

- Kind: own control
- Source: ADR 0009, amendment 2026-10-20. No law read asks it.
- Code: `backend/cultures/distribution/services/decisions.py::request_approve`, `backend/cultures/distribution/services/errors.py::ManagerRequired`
- Tests: `backend/cultures/distribution/tests/test_services.py::test_a_regulated_line_needs_a_manager_and_a_reason`, `backend/cultures/distribution/tests/test_policy.py::test_a_regulated_strain_needs_a_manager`
- Gate codes: `regulated`

#### R-DIST-04 A VRAT goes only to the holder of a valid SÚJB permit that names it, or under an SÚJB exception

- Kind: law
- Source: act 281/2002 Sb., § 13 h)
- Quote: „…poskytovat vysoce rizikové biologické agens nebo toxin pouze držiteli povolení podle § 6 odst. 1, pokud Úřad ve výjimečném odůvodněném případě na omezenou dobu rozhodnutím nestanoví jinak a pokud současně nebude ohrožen účel tohoto zákona,“
- English: The permit holder must supply a highly risky agent or toxin only to a holder of a
  permit under § 6(1), unless the Office decides otherwise for a limited time in an exceptional,
  justified case and the purpose of this act is not endangered.
- Code: `backend/cultures/distribution/policy.py::_LineCheck.restriction`, `backend/cultures/distribution/policy.py::names`, `backend/cultures/distribution/models.py::NAMES_AGENTS`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_a_vrat_goes_only_to_a_holder_of_a_permit_that_names_it`, `backend/cultures/distribution/tests/test_policy.py::test_an_sujb_exception_lets_a_vrat_go_to_a_non_holder`, `backend/cultures/distribution/tests/test_policy.py::test_a_permit_counts_only_on_the_days_it_holds`, `backend/cultures/distribution/tests/test_policy.py::test_a_permit_names_a_synonym_through_its_accepted_name`
- Gate codes: `vrat_permit_missing`
- Limits: the permit names the agent in free text, matched on the taxon's name as whole words
  (#169).

#### R-DIST-05 A RAT goes only to a requester who notified SÚJB under § 17a

- Kind: own control
- Source: the act puts the notice on the recipient (act 281/2002 Sb., § 17a(1)) and no duty on
  the sender. SÚJB asks senders to supply only notifiers, page "Přesun a předání" (guidance of
  the authority): „RAT si mohou navzájem poskytovat pouze osoby, které SÚJB ohlásily nakládání s
  RAT podle § 17a“ (RAT may be supplied only between persons who notified SÚJB of their handling
  of RAT under § 17a).
- Code: `backend/cultures/distribution/policy.py::_LineCheck.restriction`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_a_rat_goes_only_to_a_requester_who_notified_sujb`, `backend/cultures/distribution/tests/test_policy.py::test_only_a_section_17a_notice_lets_a_rat_go_out`, `backend/cultures/distribution/tests/test_policy.py::test_a_rat_notice_that_names_a_highly_risky_agent_does_not_let_it_go_out`
- Gate codes: `rat_notice_missing`
- Limits: any notice of the requester passes, though a notice names its kind of agent (§ 17a(3)
  a)). See C-04 (#173).

#### R-DIST-06 Inside the EU only ricin and saxitoxin need a transfer licence, which this collection does not hold

- Kind: law
- Source: Regulation (EU) 2021/821, Art. 11(1) and Annex IV, Part II. Ricin and saxitoxin are
  still 1C351.d.4 and 1C351.d.5 in Annex I as replaced by Delegated Regulation (EU) 2025/2003.
- Quote: "An authorisation shall be required for intra-Union transfers of dual-use items listed in Annex IV." Annex IV, Part II: "Items of the CWC (Chemical Weapons Convention) 1C351.d.4. Ricin 1C351.d.5. Saxitoxin"
- Code: `backend/cultures/distribution/policy.py::TRANSFER_LICENCE_ENTRIES`, `backend/cultures/distribution/policy.py::_LineCheck.restriction`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_only_ricin_and_saxitoxin_need_a_transfer_licence_inside_the_eu`
- Gate codes: `transfer_licence_required`

#### R-DIST-07 A quarantine pest goes only with a valid Letter of Authority that names it, with quantity and sendings left

- Kind: law
- Source: Implementing Regulation (EU) 2019/829, Art. 6(1) and (4), Annex II
- Quote: "This letter of authority shall always accompany the specified material concerned."
- Code: `backend/cultures/distribution/policy.py::_LineCheck.letter_of_authority`, `backend/cultures/distribution/policy.py::COUNTING`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_a_quarantine_pest_needs_a_letter_with_quantity_and_sendings_left`, `backend/cultures/distribution/tests/test_policy.py::test_a_letter_runs_out_of_sendings`, `backend/cultures/distribution/tests/test_policy.py::test_two_lines_of_one_request_draw_on_one_letter_together`, `backend/cultures/distribution/tests/test_policy.py::test_a_cancelled_request_gives_its_quantity_back_to_the_letter`
- Gate codes: `loa_missing`, `loa_exhausted`
- Limits: the endorsement by the member state of origin (Art. 6(2)) is stored and not checked,
  D-13 (#173). The quantity is counted in vials, and the letter may state another unit (not
  verified).

#### R-DIST-08 A GMO goes only to a holder of an authorisation for contained use of its category or higher

- Kind: law
- Source: act 78/2004 Sb., § 3(1) c): a transfer to a person not authorised for contained use is
  placing on the market. That the recipient's category must reach the strain's is our reading of
  § 15(2): contained use only in a space that meets the requirements „pro příslušnou nebo vyšší
  kategorii rizika“ (for the corresponding or a higher category of risk).
- Quote: „…uvádění geneticky modifikovaných organismů nebo genetických produktů na trh (dále jen „uvádění na trh“), za které se považuje jejich úplatné nebo bezúplatné předání jiné osobě, nejde-li o předání výlučně za účelem uzavřeného nakládání nebo uvádění do životního prostředí osobě oprávněné k tomuto způsobu nakládání.“
- English: placing GMOs or genetic products on the market is any handover to another person, paid
  or free, unless it is a handover solely for contained use or release to a person authorised for
  that use.
- Code: `backend/cultures/distribution/policy.py::_LineCheck.restriction`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_a_gmo_needs_a_contained_use_authorisation_of_its_category_or_higher`
- Gate codes: `gmo_authorisation_missing`

#### R-DIST-09 A strain of several kinds meets the gate of each

- Kind: own control
- Source: ADR 0009, Context: one organism can be on several lists.
- Code: `backend/cultures/distribution/policy.py::_LineCheck.run`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_one_strain_with_several_kinds_meets_each`

#### R-DIST-10 The requester's declared containment level reaches the risk group

- Kind: own control
- Source: the duty is the recipient's: Directive 2000/54/EC, Art. 16(1)(b), handling "only in
  working areas corresponding to at least containment level 2, for a group 2 biological agent"
  (level 3 for group 3, level 4 for group 4). The app checks the requester's declaration.
- Code: `backend/cultures/distribution/policy.py::_LineCheck.biosafety`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_the_declared_containment_must_reach_the_risk_group`
- Gate codes: `containment_too_low`

#### R-DIST-11 Risk group 2 or 3 without a work permit of the requester needs a manager

- Kind: own control
- Source: the practice of DSMZ (study s10).
- Code: `backend/cultures/distribution/policy.py::_LineCheck.biosafety`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_a_pathogen_without_a_work_permit_needs_a_manager`
- Gate codes: `work_permit_missing`

#### R-DIST-12 Risk group 3 may be Category A, so a manager decides

- Kind: own control
- Source: a scope choice (ADR 0009, amendment 2026-10-20: Category A is not shipped). The
  transport rules behind it (IATA DGR 3.6.2.2.2.1, the WHO transport guidance) were read only
  through study s10: not verified.
- Code: `backend/cultures/distribution/policy.py::_LineCheck.biosafety`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_risk_group_3_may_be_category_a`
- Gate codes: `category_a_possible`

#### R-DIST-13 Material in scope of the ABS regulation goes out only for the uses its terms cover, and an unknown scope blocks

- Kind: not verified
- Source: Regulation (EU) No 511/2014, Art. 4(3), read only through study s10. The text is not
  among the sources read.
- Code: `backend/cultures/distribution/policy.py::_LineCheck.terms`
- Tests: `backend/cultures/distribution/tests/test_policy.py::test_an_unknown_abs_scope_blocks`, `backend/cultures/distribution/tests/test_policy.py::test_material_in_scope_goes_out_only_for_uses_the_mat_covers`
- Gate codes: `abs_scope_unknown`, `abs_use_not_covered`

#### R-DIST-14 The gates run again on the Czech day of shipment

- Kind: own control
- Source: study s10, section 8: permits expire between approval and shipment.
- Code: `backend/cultures/distribution/services/shipment.py::_gates_today`, `backend/cultures/distribution/services/two_person.py::request_confirm_shipment`
- Tests: `backend/cultures/distribution/tests/test_shipment.py::test_a_permit_that_expired_since_the_approval_blocks_the_shipment`, `backend/cultures/distribution/tests/test_shipment.py::test_the_ship_day_is_a_czech_day`, `backend/cultures/distribution/tests/test_two_person.py::test_a_permit_that_expires_between_preparation_and_confirmation_blocks_it`

### Gates that are not about regulated material

These gate codes of `distribution.policy.gate_codes()` hold for every strain, regulated or not.
They rest on the collection's terms, the depositor's decisions, the MTA and the stock, and are
listed here so that the test can tell them from a regulated gate without a rule.

- Gate codes: `contact_erased`, `not_enough_vials`, `reserved_vials_not_distributable`, `terms_replaced`, `use_denied`, `use_on_request`, `use_declined_by_depositor`, `mta_missing`, `mta_not_accepted`

### Shipment and its documents

#### R-SHIP-01 A regulated request ships in two steps by two people, and the confirmer is neither the approver nor the preparer

- Kind: own control
- Source: ADR 0009, amendments 2026-10-20 and 2026-10-22. WHO Laboratory biosecurity guidance
  (2024), 7.3.3: "the involvement of two persons in critical steps in the shipping process" (a
  guidance, not a law).
- Code: `backend/cultures/distribution/services/two_person.py::request_prepare_shipment`, `backend/cultures/distribution/services/two_person.py::request_confirm_shipment`, `backend/cultures/distribution/services/errors.py::ConfirmOwnApproval`, `backend/cultures/distribution/services/errors.py::ConfirmOwnPreparation`, `backend/cultures/distribution/migrations/0008_preparation_audit_and_guards.py::"distribution_shipment_guard"`
- Tests: `backend/cultures/distribution/tests/test_two_person.py::test_the_approver_does_not_confirm`, `backend/cultures/distribution/tests/test_two_person.py::test_the_preparer_does_not_confirm`, `backend/cultures/distribution/tests/test_two_person.py::test_a_regulated_request_is_not_shipped_in_one_step`, `backend/cultures/distribution/tests/test_two_person.py::test_the_table_refuses_a_confirmation_by_the_preparer_or_the_approver`, `backend/cultures/distribution/tests/test_two_person.py::test_the_table_refuses_a_regulated_shipment_without_a_preparation`

#### R-SHIP-02 A shipment is exempt or UN 3373, never Category A or UN 3245

- Kind: own control
- Source: a scope choice, ADR 0009, amendment 2026-10-22.
- Code: `backend/cultures/distribution/models.py::TransportClass`
- Tests: `backend/cultures/distribution/tests/test_shipment.py::test_the_table_refuses_a_shipment_the_rules_refuse`
- Limits: a GMO line is not refused, so it ships under a class the transport rules may not allow
  for it. See C-02 (#173).

#### R-SHIP-03 A strain of risk group 2 or higher is not shipped as exempt, non-pathogenic

- Kind: not verified
- Source: IATA DGR 3.6.2.2.3.2 ("non-pathogenic to humans or animals"), read only through study
  s10. The IATA text is not among the sources read.
- Code: `backend/cultures/distribution/services/shipment.py::_check_exempt`
- Tests: `backend/cultures/distribution/tests/test_shipment.py::test_a_manager_finding_is_not_asked_again_at_shipment`, `backend/cultures/distribution/tests/test_two_person.py::test_a_risk_group_raised_after_the_preparation_makes_the_exemption_refused_at_confirmation`
- Limits: animal and plant pathogenicity are not read. See C-01 (#173).

#### R-SHIP-04 UN 3373 is packed to P650, and dry ice is shipped with its quantity

- Kind: not verified
- Source: RID and ADR 4.1.4.1 P650 and IATA PI 650, read only through study s10. The texts are
  not among the sources read.
- Code: `backend/cultures/distribution/services/shipment.py::_checked_shipment`
- Tests: `backend/cultures/distribution/tests/test_shipment.py::test_shipment_errors_name_their_field_and_change_nothing`, `backend/cultures/distribution/tests/test_shipment.py::test_the_table_refuses_a_shipment_the_rules_refuse`

#### R-SHIP-05 The delivery note of a dual-use line says the item is subject to controls if exported

- Kind: law
- Source: Regulation (EU) 2021/821, Art. 11(9)
- Quote: "The relevant commercial documents relating to intra-Union transfers of dual-use items listed in Annex I shall indicate clearly that those items are subject to controls if exported from the customs territory of the Union."
- Code: `backend/cultures/distribution/documents.py::DUAL_USE_NOTICE`, `backend/cultures/distribution/documents.py::delivery_note`
- Tests: `backend/cultures/distribution/tests/test_documents.py::test_only_a_dual_use_line_carries_the_notice_of_art_11_9`, `backend/cultures/distribution/tests/test_documents.py::test_the_dual_use_notice_is_the_sentence_of_the_regulation`, `backend/cultures/distribution/tests/test_documents.py::test_an_ended_dual_use_restriction_prints_no_notice`

#### R-SHIP-06 The delivery note of a quarantine pest says its Letter of Authority travels with the package

- Kind: law
- Source: Implementing Regulation (EU) 2019/829, Art. 6(1)
- Quote: "This letter of authority shall always accompany the specified material concerned."
- Code: `backend/cultures/distribution/documents.py::delivery_note`
- Tests: `backend/cultures/distribution/tests/test_documents.py::test_a_quarantine_pest_line_says_its_letter_of_authority_travels_with_it`

#### R-SHIP-07 A VRAT or RAT line gets a register entry and a handover protocol, written in the transaction of the shipment

- Kind: law
- Source: act 281/2002 Sb., § 16(1), with § 17(4) for RAT; decree 474/2002 Sb., Annex 3 (the
  columns). SÚJB, page "Přesun a předání": „každý pohyb VRAT nebo RAT musí být zapsán v evidenční
  knize poskytovatele i příjemce“ (every movement of VRAT or RAT is entered in the register of
  both the supplier and the recipient).
- Quote: „Držitel povolení je povinen průběžně vést evidenci o nakládání s vysoce rizikovými biologickými agens nebo toxiny a na požádání je předložit Úřadu.“
- English: The permit holder must keep a continuous register of the handling of highly risky
  agents or toxins and show it to the Office on request.
- Code: `backend/cultures/distribution/documents.py::register_entry`, `backend/cultures/distribution/documents.py::REGISTERED`, `backend/cultures/distribution/migrations/0010_shipment_document_audit_and_guards.py::"distribution_shipment_documented"`
- Tests: `backend/cultures/distribution/tests/test_documents.py::test_a_register_entry_and_handover_protocol_for_a_vrat_line`, `backend/cultures/distribution/tests/test_documents.py::test_a_rat_line_gets_a_register_entry_and_a_dual_use_line_none`, `backend/cultures/distribution/tests/test_documents.py::test_a_register_entry_without_a_known_seat_says_so_and_never_prints_the_delivery_address`, `backend/cultures/distribution/tests/test_documents.py::test_at_commit_a_shipment_without_its_documents_is_refused`
- Limits: only a shipment writes an entry (D-05, #171). The stock left is counted per strain,
  while the register keeps a sheet per agent (C-03, #171). The unit "vials" is not on SÚJB's list
  of units (Q-SUJB-2).

#### R-SHIP-08 A shipment document is rendered once, stored with its SHA-256, and never changed or deleted

- Kind: own control
- Source: ADR 0009, amendment 2026-10-23 (#90). Decree 474/2002 Sb., § 5(2) a) asks it of the
  register book itself: „údaje v ní evidované nemohly být odstraněny nebo změněny“ (its entries
  cannot be removed or changed).
- Code: `backend/cultures/distribution/migrations/0010_shipment_document_audit_and_guards.py::"distribution_shipmentdocument_guard"`
- Tests: `backend/cultures/distribution/tests/test_documents.py::test_a_document_is_never_changed_or_deleted`, `backend/cultures/distribution/tests/test_documents.py::test_a_document_whose_sha256_is_not_of_its_text_is_refused`, `backend/cultures/distribution/tests/test_documents.py::test_the_stored_text_stays_after_the_strain_is_renamed_and_its_restriction_ends`

### Deaccession, destruction and loss

#### R-END-01 A regulated strain leaves the collection only by a proposal and a confirmation by another manager

- Kind: own control
- Source: ADR 0009, amendment 2026-10-27. WHO Laboratory biosecurity guidance (2024), 6.3.1:
  "removal of biological material from the inventory by two employees" (a guidance, not a law).
- Code: `backend/cultures/strains/services.py::strain_deaccession`, `backend/cultures/strains/services.py::strain_deaccession_confirm`, `backend/cultures/strains/services.py::DeaccessionNeedsSecondPerson`, `backend/cultures/strains/services.py::ConfirmOwnDeaccession`, `backend/cultures/strains/migrations/0009_deaccession_audit_and_guards.py::"strains_strain_guard"`, `backend/cultures/strains/migrations/0010_confirmed_proposal_outcome.py::"strains_deaccessionproposal_confirmed"`
- Tests: `backend/cultures/strains/tests/test_deaccession.py::test_one_person_does_not_deaccession_a_regulated_strain`, `backend/cultures/strains/tests/test_deaccession.py::test_nobody_confirms_their_own_proposal`, `backend/cultures/strains/tests/test_deaccession.py::test_the_database_refuses_a_one_person_deaccession_of_a_regulated_strain`, `backend/cultures/strains/tests/test_deaccession.py::test_the_runtime_role_cannot_confirm_a_deaccession_that_did_not_happen`, `backend/cultures/strains/tests/test_deaccession.py::test_a_curator_alone_cannot_take_a_vrat_strain_out`

#### R-END-02 A quarantine pest states its final use when it leaves: destruction, collection or storage

- Kind: law
- Source: Implementing Regulation (EU) 2019/829, Annex I (h) and Art. 5(d). Collection and
  storage keep the vials.
- Quote: "the final use of the specified material on completion of the specified activity e.g.; destruction, collection or storage;"
- Code: `backend/cultures/strains/services.py::_check_final_use`, `backend/cultures/strains/models.py::FinalUse`, `backend/cultures/strains/models.py::KEEPS_MATERIAL`, `backend/cultures/strains/migrations/0009_deaccession_audit_and_guards.py::"strains_strain_guard"`
- Tests: `backend/cultures/strains/tests/test_deaccession.py::test_a_quarantine_pest_states_its_final_use`, `backend/cultures/strains/tests/test_deaccession.py::test_only_a_quarantine_pest_states_a_final_use`, `backend/cultures/strains/tests/test_deaccession.py::test_a_proposal_whose_final_use_no_longer_fits_is_not_confirmed`, `backend/cultures/strains/tests/test_deaccession.py::test_the_database_asks_a_quarantine_pest_for_its_final_use`

#### R-END-03 No vial of a regulated strain is destroyed until the destruction record exists

- Kind: own control
- Source: ADR 0009, amendment 2026-11-02 (#158): a block until the destruction record (#160).
  Study s12: no law read asks a second person at destruction.
- Code: `backend/cultures/lineage/models.py::vial_edges`, `backend/cultures/lineage/services/errors.py::DestructionNeedsRecord`, `backend/cultures/lineage/migrations/0010_vial_guard_regulated_destroy.py::"lineage_vial_guard"`
- Tests: `backend/cultures/lineage/tests/test_vial_states.py::test_a_regulated_strain_takes_every_edge_but_the_one_to_destroyed`, `backend/cultures/lineage/tests/test_api.py::test_a_regulated_strains_vial_to_destroy_is_not_destroyed_through_the_api`, `backend/cultures/lineage/tests/test_runtime_role.py::test_the_runtime_role_cannot_destroy_a_vial_of_a_regulated_strain`

#### R-END-04 A lost vial of a strain that was a VRAT or RAT at the loss owes a report to the police

- Kind: law
- Source: act 281/2002 Sb., § 5(5). That a manager records the report is our own choice.
- Quote: „Každý, kdo zjistí ztrátu vysoce rizikového nebo rizikového biologického agens nebo toxinu … je povinen oznámit tuto skutečnost bez zbytečného odkladu Policii České republiky, která tyto informace bez zbytečného odkladu sdělí Úřadu.“
- English: Anyone who finds that a highly risky or risky agent or toxin is lost must report it to
  the Police of the Czech Republic without undue delay, and the police pass it on to the Office.
- Code: `backend/cultures/lineage/selectors.py::reportable_loss`, `backend/cultures/lineage/models.py::LOSS_REPORTED_KINDS`, `backend/cultures/lineage/services/losses.py::vial_loss_report`, `backend/cultures/lineage/migrations/0012_vial_loss_report_audit_and_guard.py::"lineage_viallossreport_guard"`
- Tests: `backend/cultures/lineage/tests/test_loss_reports.py::test_a_manager_records_the_report_once_with_its_event`, `backend/cultures/lineage/tests/test_loss_reports.py::test_the_trigger_and_the_service_agree_with_the_python_definition`, `backend/cultures/lineage/tests/test_loss_reports.py::test_a_vial_found_and_lost_again_owes_a_new_report`, `backend/cultures/lineage/tests/test_loss_reports.py::test_only_a_manager_records_it`, `backend/cultures/lineage/tests/test_loss_reports.py::test_the_reference_and_the_day_are_checked`

## Legal duties the app does not enforce yet

Each duty is the law's. Until its issue is built it is the lab's to keep outside the app.

### D-01 VRAT handled only within the kinds and quantities of the permit

- Source: act 281/2002 Sb., § 11(3) d) and § 13 a)
- Quote: „druh a množství vysoce rizikových biologických agens nebo toxinů, se kterými lze nakládat,“ and „nakládat s vysoce rizikovými biologickými agens a toxiny jen v rozsahu stanoveném v povolení,“
- English: the permit states the kind and quantity of agents that may be handled, and the holder
  handles them only within the scope of the permit.
- Today: a lab permit has no agents and no quantity (R-PERMIT-01). The ÚKZÚZ authorisation names
  its pest, also not held (R-PERMIT-02).
- Issue: #170

### D-02 At the end of a VRAT permit the agents are handed over or destroyed

- Source: act 281/2002 Sb., § 13 k)
- Quote: „při zániku a zrušení povolení bez zbytečného odkladu zajistit předání vysoce rizikového biologického agens nebo toxinu jinému držiteli povolení nebo jeho zničení“
- English: when the permit ends or is revoked, the holder hands the agent over to another holder
  of a permit or destroys it, without undue delay.
- Today: nothing reads the lab's permit after accession.
- Issue: #170

### D-03 The lab notifies SÚJB 14 days before it first handles a RAT

- Source: act 281/2002 Sb., § 17a(1), (3) a)
- Quote: „V případě, že fyzická nebo právnická osoba hodlá poprvé nakládat s rizikovým biologickým agens nebo toxinem, je povinna ohlásit tuto skutečnost Úřadu 14 dnů před uskutečněním tohoto nakládání.“
- English: a person who intends to handle a risky agent or toxin for the first time notifies the
  Office 14 days before.
- Today: the lab's own notice is not recorded, and a RAT strain enters any lab (R-PERMIT-03).
- Issue: none

### D-04 The lab holds an authorisation for contained use of GMOs, by notification or permit

- Source: act 78/2004 Sb., § 4(2), § 16
- Quote: „Oprávnění k uzavřenému nakládání vzniká na základě povolení k uzavřenému nakládání, popřípadě oznámení.“
- English: the authorisation for contained use arises from a permit for contained use, or a
  notification.
- Today: not recorded and not gated. The GMO restriction's reference is free text.
- Issue: none

### D-05 A continuous register per workplace and agent, of every handling

- Source: act 281/2002 Sb., § 16(1), (2), § 17(4); decree 474/2002 Sb., § 5(3) c)
- Quote: „Evidence musí být vedena podle pracoviště, kde se evidovaná činnost provádí, podle jednotlivých druhů a množství vysoce rizikových biologických agens nebo toxinů.“ and „alespoň jeden samostatný evidenční list pro každé jednotlivé biologické agens nebo toxin“
- English: the register is kept per workplace where the activity takes place, per kind and
  quantity of agent, with at least one sheet for each agent.
- Today: only a shipment writes an entry (R-SHIP-07). Accession, passages, consumption, loss and
  destruction write none, and a lab has no workplace.
- Issue: #171

### D-06 A yearly declaration to SÚJB by 31 January

- Source: act 281/2002 Sb., § 16(4), (5), § 17(2), (3)
- Quote: „Držitel povolení je povinen předložit Úřadu deklaraci za uplynulý kalendářní rok nejpozději do 31. ledna následujícího roku.“
- English: the permit holder submits to the Office a declaration for the past calendar year by
  31 January of the following year (§ 17(2) the same for RAT).
- Today: no export.
- Issue: #160, #171

### D-07 SÚJB is notified when a VRAT or RAT enters or leaves the Czech Republic

- Source: act 281/2002 Sb., § 14(5), § 17b(1)
- Quote: „Držitel povolení je povinen oznámit Úřadu vstup vysoce rizikových biologických agens nebo toxinů na území České republiky nebo jejich opuštění území České republiky do 5 dnů ode dne uskutečnění.“
- English: the permit holder notifies the Office of highly risky agents or toxins entering or
  leaving the Czech Republic within 5 days of the day it happened (§ 17b(1) the same for RAT).
- Today: not recorded. Shipments to every EU state are allowed (R-DIST-01), and a deposit from
  abroad is an entry. Whether SÚJB counts a transfer to another member state is Q-SUJB-6.
- Issue: #172

### D-08 The VRAT holder informs the carrier and documents it

- Source: act 281/2002 Sb., § 13 i)
- Quote: „informovat dopravce vysoce rizikového biologického agens nebo toxinu o povaze zboží, které mu bylo svěřeno, a o bezpečném způsobu nakládání s ním a toto informování dokumentovat,“
- English: inform the carrier of the nature of the goods entrusted to it and of their safe
  handling, and document that.
- Today: not recorded.
- Issue: #172

### D-10 A GMO's label or accompanying document says "Geneticky modifikovaný organismus"

- Source: act 78/2004 Sb., § 11(1)
- Quote: „Osoba poskytující geneticky modifikovaný organismus výlučně pro účely uzavřeného nakládání nebo uvádění do životního prostředí je povinna zajistit, aby na štítku nebo v průvodním dokumentu geneticky modifikovaného organismu byla zřetelně uvedena slova „Geneticky modifikovaný organismus“…“
- English: whoever supplies a GMO solely for contained use or release ensures that its label or
  accompanying document clearly carries the words "Geneticky modifikovaný organismus".
- Today: the delivery note says nothing of a GMO.
- Issue: #173

### D-11 The ministry is told 5 days before a GMO is imported or exported

- Source: act 78/2004 Sb., § 25(5)
- Quote: „Osoba, která hodlá dovézt nebo vyvézt geneticky modifikované organismy podle odstavce 3 nebo 4, je povinna ministerstvu nejpozději 5 dnů před uskutečněním dovozu nebo vývozu poskytnout informaci o druhu a množství geneticky modifikovaných organismů…“
- English: whoever intends to import or export GMOs informs the ministry of their kind and
  quantity at least 5 days before.
- Today: not recorded. Whether it reaches transfers inside the EU is not verified.
- Issue: #172

### D-12 GMO documentation per workplace and a yearly overview by 15 February

- Source: act 78/2004 Sb., § 19 b), c); decree 209/2004 Sb., § 8(3) (the operating diary)
- Quote: „zaslat ministerstvu vždy k 15. únoru kalendářního roku přehled geneticky modifikovaných organismů, údaje o jejich množství, o způsobu nakládání s nimi a vyjádření k přezkoumání hodnocení rizika za uplynulý kalendářní rok,“
- English: send the ministry by 15 February each year an overview of the GMOs, their quantities,
  how they were handled, and a statement on the review of the risk assessment, for the past year.
- Today: not built.
- Issue: #160 (the yearly export only, "Matching exports for GMO"). The operating diary has no
  issue.

### D-13 A Letter of Authority is endorsed by the member state of origin

- Source: Implementing Regulation (EU) 2019/829, Art. 6(2)
- Quote: "It shall be officially endorsed by the Member State of origin, for movement of the respective specified material under quarantine or confinement conditions."
- Today: the endorsement is stored, no gate reads it.
- Issue: #173

### D-14 A confinement facility keeps records of quarantine material in and out for three years, and notifies the end of its activity a month before

- Source: Regulation (EU) 2016/2031, Art. 62(3) c); ÚKZÚZ guide for confinement facilities (2022)
- Quote: "the pests, plants, plant products and other objects entering and leaving the station or facility;" with "Those records shall be kept for three years." The ÚKZÚZ guide: „vést evidenční knihu práce s karanténním materiálem“ and „oznámit ukončení činnosti alespoň 1 měsíc před plánovaným termínem ukončení“
- English (ÚKZÚZ): keep a register book of the work with quarantine material, and notify the end
  of the activity at least one month before the planned end.
- Today: not built. Whether destroyed material "leaves" the facility is Q-UKZUZ-3.
- Issue: #162 (the end notice), #160 (the export for quarantine pests)

### D-15 An escape is reported: a VRAT to SÚJB, quarantine material to ÚKZÚZ

- Source: act 281/2002 Sb., § 13 l); Implementing Regulation (EU) 2019/829, Art. 8(b); ÚKZÚZ guide
  for confinement facilities (2022)
- Quote: „bez zbytečného odkladu oznámit Úřadu únik vysoce rizikového biologického agens nebo toxinu do životního prostředí.“ and "any event resulting in the escape, or likelihood of escape, of pests referred to in point (a) into the environment, is notified immediately to the competent authority by the person responsible for the activities." The ÚKZÚZ guide: „Oznámit neprodleně ÚKZÚZ jakýkoliv možný únik karanténního materiálu z izolačního zařízení“
- English: report to the Office without undue delay an escape of a highly risky agent or toxin
  into the environment. ÚKZÚZ: report at once any possible escape of quarantine material from the
  confinement facility.
- Today: a lost vial of a quarantine pest asks for nothing. Whether a lost vial is an escape is
  not verified.
- Issue: none

### D-16 The public health authority is notified 30 days before the first use of agents of groups 2 to 4

- Source: act 258/2000 Sb., § 41, as summarised in the lab domain study. Not verified: the text
  is not among the sources read, nor which authority receives the notice.
- Today: not recorded.
- Issue: none

### D-17 A list of the people with access to a workplace that handles a VRAT

- Source: act 281/2002 Sb., § 14a(5); the offence § 21a(2) g)
- Quote: „Držitel povolení, který provozuje pracoviště podle § 5 odst. 6, kde se nakládá s vysoce rizikovým biologickým agens nebo toxinem, je povinen vytvořit seznam osob, které mají na toto pracoviště přístup.“
- English: a permit holder who runs a workplace under § 5(6) where a highly risky agent or toxin
  is handled makes a list of the people who have access to that workplace.
- Today: kept by the lab outside the app. The app keeps the list of access to the agent
  (R-ACCESS-01), and a lab has no workplace (D-05).
- Issue: none

### D-18 Everyone with access to a VRAT is trained every year

- Source: act 281/2002 Sb., § 14a(6); the offence § 21a(2) h)
- Quote: „Držitel povolení je povinen zajistit, aby všechny osoby, které mají přístup k vysoce rizikovému biologickému agens nebo toxinu, byly každoročně proškoleny v oblasti zabezpečení vysoce rizikového biologického agens a toxinu proti zneužití, ztrátě a krádeži.“
- English: the permit holder ensures that everyone with access to a highly risky agent or toxin
  is trained every year in securing it against misuse, loss and theft.
- Today: not recorded. The people it concerns are the open entries of R-ACCESS-01.
- Issue: none

## Rules that break a source

### C-01 Exempt, non-pathogenic is refused only for risk group 2 or higher

- Source: IATA DGR 3.6.2.2.3.2, "non-pathogenic to humans or animals", read only through study
  s10 (not verified). The risk group rates harm to humans only (ADR 0009).
- Today: an animal or plant pathogen of group 1 ships as exempt (R-SHIP-03).
- Issue: #173

### C-02 A GMO line is not refused and UN 3245 is never recorded

- Source: study s10: "GMOs that are not infectious go to UN 3245 (WHO 4.5 note)". Not verified
  against RID and ADR 2.2.9.
- Today: a GMO can only be recorded under a class the source says is wrong (R-SHIP-02).
- Issue: #173

### C-03 The stock left on a register entry is counted per strain

- Source: decree 474/2002 Sb., § 5(3) c): a sheet per agent (quoted in D-05).
- Today: two strains of one agent give a wrong stock (R-SHIP-07).
- Issue: #171

### C-04 Any RAT notice of the requester lets any RAT go

- Source: act 281/2002 Sb., § 17a(3) a): the notice names „druh rizikového biologického agens nebo toxinu“ (the kind of risky agent or toxin).
- Today: a notice for one agent lets another go (R-DIST-05).
- Issue: #173

## Own controls decided and not built

Not legal duties, listed so that a reader sees what the ADRs promise and the code does not hold
yet.

- Every classification from an official list, with its source and version: #169.
- Lowering a risk group by two people (the project's own rule for anything that relaxes a gate,
  R-RISK-03): #174.
- The audit hash chain with a daily qualified timestamp (ADR 0009, Tamper evidence): #175.
- A second factor on every account (ADR 0009, Second factor): #176.

## Open questions to the authorities

Written on 2026-11-02 for SÚJB and ÚKZÚZ, no answer recorded yet. Nothing in the app takes an
answer for granted: each question names what waits for it. When an answer comes, write it here with the day and the
reference, and change what it decides.

### SÚJB

- Q-SUJB-1 How is a destruction in the lab written in the register book (decree 474/2002 Sb.,
  Annex 3): the quantity under "Výdej", the supplier or recipient column empty or the own
  workplace, "zničení" with the method in the note, the protocol number in the document column,
  and a reference to the protocols on the first page? Waits: the destruction protocol (#160).
- Q-SUJB-2 Which unit does a collection of cryovials use in the declaration, whose form has a
  fixed list of units without a vial, and is a destruction in the year "použití (spotřeba)"?
  Waits: the declaration export (#160) and the unit "vials" on every register entry
  (R-SHIP-07).
- Q-SUJB-3 May material from work with VRAT or RAT, inactivated in the lab by a validated
  autoclave run, go to an authorised firm as ordinary infectious waste, and what proof of the
  inactivation is wanted? Waits: the outside firm of a destruction record (#160).
- Q-SUJB-4 May the register be kept electronically, or does the bound book with numbered sheets
  stay the register and the app only its source? Waits: whether the app's register is the
  register or a copy (#171, ADR 0009 open question). Until then every register page says the
  bound book is the legal register (R-SHIP-07).
- Q-SUJB-5 Does SÚJB expect the register to check, at each receipt and handling, that the agent
  and its quantity are within the permit (§ 11(3) d)), or is that the lab's to watch? Waits:
  D-01 (#170).
- Q-SUJB-6 Does the notice of § 14(5) and § 17b(1) reach a RAT sent to another member state of
  the EU, as for a VRAT? Waits: D-07 (#172).

### ÚKZÚZ

- Q-UKZUZ-1 Is each destruction of quarantine material notified, or are the register book entry
  and the notice of the end of the activity a month before enough? Waits: #160, #162.
- Q-UKZUZ-2 What does the register book entry of a destruction hold (day, quantity, method, who,
  check of the effect), and how long is the book kept? Waits: #160.
- Q-UKZUZ-3 Does destroyed material count as material that leaves the facility, so that the
  three years of Regulation (EU) 2016/2031, Art. 62(3) apply to its records? Waits: D-14.
- Q-UKZUZ-4 Does a destruction by a method other than the one in the authorisation need a changed
  decision first? Waits: #160 (the method must match the authorisation).
