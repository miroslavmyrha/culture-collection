# 0008 Domain model of the collection

Date: 2026-10-18
Status: accepted (#50)
Amended 2026-10-19: terms, contacts and the intake (#10, #12).
Deciders: maintainer

## Context

The strain registry (#11) creates the first domain tables. The shape of the
lineage, the accession number, passage numbering, taxonomy, the strain and
deposit states, where personal contact data lives and how events find their
strain are in every later table and query. Each is expensive to change once
data exists. Regulated agents and the security level are in ADR 0009.

The collection keeps pure cultures. A strain arrives in a deposit, is grown
in passages, preserved in batches and stored as vials. A vial is used whole.
No material is pooled.

## Decision

**D1 Lineage: a typed tree deposit > passage > batch > vial.**
- `Passage` has exactly one source: the deposit (the material as received),
  a parent passage, or a vial that was revived. A check constraint holds
  `num_nonnulls(...) = 1`.
- `Batch` is one preservation of one passage. `Vial` is one physical item:
  no quantity column, stock is a count of rows.
- A revival consumes a vial and starts a passage from it, so the tree reads
  deposit > passage 1 > batch 1 > vial 7 > passage 2 > batch 2.
- Source columns are written once. A correction marks the row
  entered_in_error and adds a new one, so no cycle can form. That parent and
  child belong to the same strain crosses tables: the service checks it.

**D2 Accession number: text unique per lab plus a nullable sequence.**
- `accession_number` is the number as displayed and is unique per lab
  without regard to case. `accession_seq` is an integer unique per lab.
- A new number takes the next sequence value from a counter row locked
  under the lab lock, and its text is the lab code, a space and the
  sequence (`MYC 42`).
- The number is assigned when the strain is accepted, never changed, and
  never given to another strain, also after deaccession. OECD BRC
  guidelines, General 10.1: a unique collection number, never reassigned
  when the material is later discarded.
- Legacy numbers ("1234a") enter only through a catalogue import, which
  keeps their text and moves the counter past the highest imported number
  in the same transaction. No screen accepts a typed number.

**D3 Passages are counted from receipt.** The material as received is
passage 0, each subculture or revival adds one. The passage count the
depositor states, if any, is an optional field on the deposit. The absolute
count from isolation is unknown for most deposits.

**D4 Taxonomy: one global table managed by staff.**
- `Taxon` has no lab. It holds name, authority, rank and parent. A synonym
  points at its accepted name (a check: set if and only if the status is
  synonym). External ids (NCBI, LPSN, MycoBank) are optional rows, unique
  per system, so a fungus or a newly described species without one can be
  stored.
- Staff change taxa in admin through services, like every other audited
  write. Labs read them.
- A strain's identification is a history: one row per identification with
  taxon, date, method and reason, and exactly one current (partial unique).
  Reclassification adds a row. The current taxon is cached on the strain
  for filters.
- The name as received stays on the strain and never changes.

**D8 Strain and deposit states.**
- Strain: `pending` > `active` <> `restricted` > `deaccessioned`, terminal.
- Deposit: `received` > `checking` > `accepted` or `rejected`. Acceptance
  assigns the accession number. A rejected deposit burns no number.
- One transition service per entity locks the row, checks the edge and
  records the event.
- Until deposit intake exists (#12), a curator creates a strain directly and
  it gets its number at once, so it starts `active`. After #12 strains come
  from accepted deposits: the intake creates the strain `pending` without a
  number, acceptance numbers it. Direct creation then stays only for the
  catalogue import.

**D11 Contacts live in their own table, outside the row audit.** Names,
e-mail addresses and postal addresses of depositors and requesters are rows
of a contact table listed in `NOT_ROW_AUDITED`. Depositor and requester rows
point at a contact. Service events hold ids only, and a contact field that
changed is recorded as `changed` (ADR 0005, update of 2026-10-18). An
erasure overwrites the contact row and touches no audit row.

**D13 Audit events carry the strain.** `AuditEvent.strain_id` is the
strain's public id, nullable, without a foreign key, so an event outlives
its strain like `subject_id` does. Every event about a strain or anything
under it (deposit, passage, batch, vial, check, placement, request line)
carries it, passed by the service in `Change(strain_id=...)`. A batch event
carries the strain when all its items share one. The strain's timeline (#19)
is one query on a partial index `(lab, strain_id, occurred_at DESC)` over
the events that name a strain.

**Decided elsewhere or later.** Each is settled in the ADR or issue named,
before the tables it shapes:
- D5 placement and move history of vials and storage units: with storage
  (#14).
- D6 box coordinates, 1-based rows and columns with computed labels: with
  the box grid (#15).
- D7 vial states and transitions: with preservation and batches (#16).
- D9 terms model, versioned terms per deposit with frozen MTA versions:
  with depositors and terms (#10).
- D10 use vocabulary of the terms: with depositors and terms (#10), agreed
  with the curators.
- D12 biosafety: ADR 0009.
- D14 storage model, one unit table or one per level: with storage (#14).
- D15 seed and distribution stock: with preservation and batches (#16).
- D16 identity, purity and viability checks: with viability checks (#17).
- D17 vial barcodes, generated labels and pre-printed codes: with
  preservation and batches (#16).
- D18 requesters, records kept by curators or a portal: with distribution
  (#18).
- D19 when vials are reserved for a request: with distribution (#18).

## Migration impact

This ADR adds one thing now: `audit_auditevent.strain_id` (audit 0012, a
nullable column, no rewrite) and its partial index, built concurrently
(audit 0013). Both come before the first strain event, so nothing ever needs
a backfill. Reversible: `migrate audit 0011` drops the index and the column.
The tables of D1 to D11 arrive with their issues, each with its row audit
attachment (ADR 0005) and lab scope (ADR 0006). Changing the lineage shape,
the accession columns or the taxon table after strains exist means a data
migration of every strain.

## Consequences

+ Lineage rules are database constraints on typed foreign keys, not rules on
  process names in a generic edge table.
+ No accession number is ever reused or edited, and imports keep the
  numbers a catalogue already printed on its vials.
+ A strain's history is one indexed query, also for events of vials and
  batches deep in the tree.
- The tree has no place for mixed cultures, consortia or pooled material.
  Adding them means a material layer with ratios.
- Taxonomy is shared by all labs: a lab cannot add a taxon itself, staff
  do.
- A contact change by SQL or `QuerySet.update()` leaves no row change.
  Contacts are written only by their service, which records the event.
- A service that forgets `strain_id` hides its event from the timeline, so
  the tests of each strain service assert it for every event they record.

## Alternatives considered

- Lineage as one material table with a generic parent and child edge and the
  process on the edge (freezeman does this): needs rules keyed on process
  names to stay valid, and gives no constraint per level.
- Accession as an integer only, display computed: cannot hold legacy numbers
  with suffixes. A UUID only: not a collection number people can cite.
- Passages counted from isolation: unknown for most deposits.
- Taxonomy as free text per lab: no synonyms, no history, no filter by
  genus. External lookups only: the collection then depends on a service
  being reachable and on its id existing.
- Contact columns on the depositor row, marked excluded: personal data and
  audited facts mixed in one row, and each new contact column needs the
  exclusion.
- A generic root type and id on events: two columns that every query must
  match, for one root the domain needs.

## Sources

- OECD Best Practice Guidelines for Biological Resource Centres (2007),
  General 10.1 (p. 40), 10.2 and 10.3 (pp. 40 to 41). Read in the Internet
  Archive copy of the OECD PDF:
  https://web.archive.org/web/20201124135925/http://www.oecd.org/sti/emerging-tech/38777417.pdf
  (landing page
  https://www.oecd.org/en/publications/oecd-best-practice-guidelines-for-biological-resource-centres_9789264128767-en.html).
- WFCC Guidelines for the establishment and operation of collections of
  cultures of microorganisms, 3rd edition (2010), 8.2 to 8.5 and 11.1:
  https://wfcc.info/static/pdf/Guidelines_e.pdf
- ISO 24088-1:2022, biobanking of microorganisms, bacteria and archaea:
  https://committee.iso.org/standard/77790.html
- ISO 21710:2020, data management and publication in microbial resource
  centres, to read before the strain data set is fixed:
  https://committee.iso.org/standard/71384.html

Revisit when: the collection takes mixed cultures or consortia, a catalogue
to import has a numbering this model cannot hold, or a lab needs taxa of its
own.

## Amendment 2026-10-19: terms, contacts and the intake (#10, #12)

Decided with depositors and terms (#10) and deposit intake (#12).

**D9 Terms are versions per deposit.** A deposit's terms are rows of
`DepositTerms`, numbered from 1, at most one active per deposit (a partial
unique index). A change adds a version with a reason and makes it the active
one; the old version stays, unchanged. The uses are rows (`TermsUse`), one
per use of D10, each `permit`, `deny` or `on_request`, and a version lists
every use: "not stated" is no decision. A version may point at one MTA
template version. MTA templates (`MtaTemplate`) are per lab, with a code and
a version, and their text is frozen: a trigger refuses any change or delete
and checks on insert that `text_sha256` is the SHA-256 of the stored text.
A new text is a new version. A request line (#18) will keep the terms
version it was approved under.

**D10 Use vocabulary.** `research_noncommercial`, `research_commercial`,
`teaching`, `diagnostics`, `production`, `reference_qc`,
`patent_deposit_related`, `redistribution`, as a `TextChoices`. These are
MTA permissions, not ABS utilisation (storage and culturing are not
utilisation under Regulation (EU) No 511/2014, guidance 2021/C 13/01).
To be confirmed with the curators before the first production data: a
renamed or split use then needs a data migration of every terms version.

**ABS facts are part of each terms version.** Following Regulation (EU) No
511/2014, Art. 4(3): country of origin (ISO 3166-1 alpha-2), collection date
(YYYY, YYYY-MM or YYYY-MM-DD), the scope (`not_in_scope`, `in_scope`,
`unknown`), PIC and MAT references, the IRCC identifier and a permit
reference. A check constraint: `in_scope` needs an IRCC identifier or a
permit reference. They sit on the terms version rather than on the deposit
row, so a correction is a new version with a reason and the facts passed to
a recipient are one row to pin. The IRCC text is not checked against a
format: none was verified.

**D11 Contacts.** `deposits.Contact` holds the name, e-mail and postal
address, is lab scoped and is listed in `NOT_ROW_AUDITED`. A depositor
(`Depositor`, row audited) points at one contact and holds the institution,
an organisation, not a person. Events about a depositor or a contact record
a personal field as `changed` (`registry.PERSONAL_FIELDS`). Erasure
(`contact_erase`, reason required, command `erase_contact` for staff) empties
the contact row in place and sets `erased_at`; a check constraint holds the
empty row. The depositor, its deposits and every audit row stay. Requesters
(#18) will point at the same table.

**D8 as built.** Deposit: `received` > `checking` > `accepted` or
`rejected`, held by a guard trigger as well as the services. The receipt
facts (depositor, received date, condition on arrival, name as received,
the passage count the depositor states) never change. Rejection needs a
reason and burns no number.
- Changed from D8 above: the intake creates no pending strain. Acceptance
  creates the strain through the strain service (`strain_create`), active
  and numbered at once, with the name as received from the deposit, and
  passage 0 from the deposit (D3, `lineage.Passage`). The taxon and the risk
  group are only known after the check, and a pending strain would need a
  placeholder for both. `pending` stays a valid status, unused for now.
- The biosafety gates of #11 run at acceptance: risk group 4 is refused,
  a VRAT or quarantine pest needs the lab's valid permit.
- Direct creation leaves the API: the strain create endpoint is removed, and
  "Add a strain" in the strain list leads to deposit intake. `strain_create`
  stays for acceptance, the development data and the catalogue import.
- Events about a deposit carry the strain from acceptance on.
- `lineage.Passage` has a strain, a number, and exactly one source, the
  deposit or a parent passage (`num_nonnulls(...) = 1`); passage 0 if and
  only if the source is the deposit. The vial source comes with #16.

**Who does what.** Curators and managers read and write depositors, deposits
and terms (`deposits.view`, `deposits.manage`), and read MTA templates.
Only managers publish an MTA version (`deposits.manage_mta`): its text is a
legal document the lab signs up to, not daily curation. Viewers and
technicians see no depositor or deposit, so contacts reach only the people
who handle deposits.

Migration impact: new tables only (`deposits_*`, `lineage_passage`), each
with its row audit (except the contact) and guard triggers, the new event
types in the reason check of `audit_auditevent`. The strain tables do not
change.
