# 0008 Domain model of the collection

Date: 2026-10-18
Status: accepted (#50)
Amended 2026-10-19: terms, contacts and the intake (#10, #12); storage (#14);
preservation, batches and vials (#16). Amended 2026-10-20: the box grid (#15).
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
  (#14). Decided 2026-10-19, see the storage amendment below.
- D6 box coordinates, 1-based rows and columns with computed labels: with
  the box grid (#15). Decided 2026-10-19 with storage, see the storage amendment below.
- D7 vial states and transitions: with preservation and batches (#16).
  Decided 2026-10-19, see the preservation amendment below.
- D9 terms model, versioned terms per deposit with frozen MTA versions:
  with depositors and terms (#10).
- D10 use vocabulary of the terms: with depositors and terms (#10), agreed
  with the curators.
- D12 biosafety: ADR 0009.
- D14 storage model, one unit table or one per level: with storage (#14).
  Decided 2026-10-19, see the storage amendment below.
- D15 seed and distribution stock: with preservation and batches (#16).
  Decided 2026-10-19, see the preservation amendment below.
- D16 identity, purity and viability checks: with viability checks (#17).
- D17 vial barcodes, generated labels and pre-printed codes: with
  preservation and batches (#16). Decided 2026-10-19, see the preservation
  amendment below.
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

## Amendment 2026-10-19: storage (#14)

The storage tree is built before vials exist (#16), so the shape of the
tree, its history and the box coordinates are settled now.

**D14 Storage: one unit table, scoped by lab.**
- `StorageUnit` holds every level: kind `freezer`, `ln2_tank`, `rack` or
  `box`, a name, a parent (PROTECT), an optional `slot` (1-based position
  in the parent), an optional barcode, an optional `temperature_c`, a
  status, and for boxes a box type with rows and columns.
- A kind spec in code (`storage.models.KIND_SPEC`) says which kind may hold
  which: freezers and tanks are the roots and only they (a check
  constraint), a rack sits in a freezer or a tank, a box in a rack, a
  freezer or a tank. The path trigger refuses the same pairs, and a test
  tries all sixteen against both.
- The name is unique among the units of one parent, and among the roots of
  one lab, without regard to case. A retired unit no longer blocks its name
  or its slot. A barcode is unique per lab, retired units included, because
  the label stays on the object.
- Status is `active`, `out_of_service` or `retired`. Active and out of
  service go both ways; retired is final and needs `retired_at`. A unit is
  retired only once every unit in it is retired and no position of it is
  occupied, and every status change has a reason. Units are never deleted
  (a trigger, and no DELETE for the runtime role).
- `BoxType` is global reference data managed by staff in admin, like taxa:
  a name, rows and columns, at most 26 each (one letter per row). A box
  copies rows and columns from its type when it is made. The type keeps its
  size for good (a trigger), and a box gets a new size only by taking
  another type while no position is occupied. `storage.services.box_occupied`
  answers that; it is false until #16 counts placements in it, and every
  service that resizes or retires a box asks it.
- The path is a `bigint[]` of ids from the root down to the unit, written
  only by a trigger. On every insert and move the trigger takes an
  advisory lock per lab, reads the parent, refuses a parent that is the
  unit or below it, a parent in another lab and a pair the kind spec does
  not allow, and rewrites the path of everything below a moved unit. A unit
  never leaves its lab, so a lab's units form one forest and one lock per
  lab is the tree lock; the services take the lab row lock before it, so
  for them it never waits. netbox keeps its tree in ltree with a lock per
  root (read for the design, no code taken); an array needs no extension,
  which the migration role would have to be allowed to create.
- `max_risk_group` (1 to 4) caps what a unit and everything in it may
  hold. Every root states one (a check constraint), a unit below may lower
  it. The effective cap is the lowest along the path, one subquery per row
  (`with_path_facts`). `storage.policy.may_store(unit, risk_group)` is the
  gate of ADR 0009: only a box, only while it and every unit above it are
  active, only up to the cap. It is written and tested now and called by
  placements from #16. Lowering a cap below what a unit already holds is
  refused from #16, when units hold something.
- Who: viewers and up see the tree (`storage.view`), curators and managers
  build it (`storage.manage`). The permission was granted to technicians
  before; no code used it. The tree carries the biosafety caps of
  ADR 0009, so it is the curators'. Technicians place vials in it
  (`vials.handle`, #15 and #16).
- The tree is read whole: the list endpoint returns every unit of the lab
  in tree order, not paged, in one query.

**D5 Location history: interval rows for vials, events for units.**
Vials get placement rows with a start and an end (#16): "where was this
vial on day X" is one query, and the freezer failure report needs it.
Units move rarely. A unit's parent is its current location, and each move
is a `storage_unit_moved` event that records the parent, the slot and the
whole path before and after, as public ids. The location of a box on day X
is its own latest move before X, then that of each unit above it, at most
three steps. No source we read needs this as a single query. If a report
does, a unit location table can be filled from these events alone.

**D6 Coordinates: 1-based rows and columns, computed labels.** A position
is a row and a column, both counted from 1. The label is computed: rows as
letters, columns as numbers, so row 1, column 1 is "A1" and row 9,
column 9 is "I9". This is the default for every lab. A lab that labels its
boxes otherwise (numbered positions 1 to 81) is deferred until one asks.

**Regulated locations (ADR 0009).** Units hold no strains yet, so nothing
in #14 says where a regulated strain lies. The masking and the reveal come
with placements (#16).

Migration impact: additive. Storage migrations 0001 to 0003 create the two
tables, attach the row audit and the triggers; audit 0017 replaces the
reason-required check on `audit_auditevent` for the new status event, a
scan of the audit table under its lock. `migrate storage zero` and
`migrate audit 0016` reverse it while no other table points at units.

Revisit when: a lab holds more than about 5 000 units (load the tree by
level), a lab needs another kind (a shelf, a drawer, a canister of its
own), a lab labels its positions otherwise, or a report needs past unit
locations as one query.

## Amendment 2026-10-19: preservation, batches and vials (#16)

Decided with preservation and vial batches (#16). The box grid is #15, viability checks
#17, distribution #18.

**D1 as built: three passage sources.** `lineage.Passage` gets `source_vial`, so its check
is `num_nonnulls(source_deposit, source_passage, source_vial) = 1`, and passage 0 still
comes only from the deposit. A subculture is a passage from a parent passage, a revival a
passage from a vial. Either is numbered one more than its source (D3): the parent's number,
or the number of the passage the vial's batch was preserved from. A revival consumes the
vial in the same transaction, and the vial is the source of one passage at most (a one to
one key). The service checks that the source belongs to the same strain. A strain without
passage 0 (one created before deposit intake, or by a later import) cannot be preserved
until it has a passage; the import decides how it gets one.

**Batch.** `lineage.Batch` is one preservation of one passage: lab, strain, passage, a
number per strain, the method (`cryo_minus80`, `cryo_ln2`, `lyophilised`), the protectant
as free text (`cryoprotectant`, "10 % glycerol", or the lyoprotectant), the day it was
preserved (`preserved_on`, a Czech day, not in the future), `vial_count_created` (1 to 200,
a fact of the event, not a stock counter), a purpose and a status. The number is the
strain's highest plus one, taken under the strain's row lock, and a unique constraint
(strain, number) is the final arbiter. A batch is never deleted and changes only its status
(a guard trigger).
- **D15: purpose `seed` or `distribution`** (recommendation a). OECD General 11.2 keeps a
  seed stock made from the original and supplies only from distribution stock, so seed
  vials are never distributed. #18 enforces it; the purpose is set at preservation and
  never changes.
- **Status: `pending_check`, `released`, `on_hold`, `exhausted`.** A batch starts
  `pending_check`. No service changes the status in #16: release and hold follow the checks
  of #17 (D16), which brings the edges and their guard. Exhausted is set by #18 or by the
  last vial leaving, decided there.

**D17: barcode nullable and unique per lab, label always computed** (recommendation c). A
vial's label is "<accession number> / <batch number> / <seq>", computed, never stored. A
pre-printed or scanned barcode is optional, unique per lab (also after the vial left: the
code is printed on the tube), without spaces, and may be set or corrected with its own
event. Scanning comes with the box grid (#15).

**D7: vial states.** `lineage.Vial` is one physical item: lab, batch, `seq` (1 to the
count, unique per batch), barcode, status and `status_changed_at`. No quantity: a vial is
used whole. The states and edges (lab-domain D7):
- `available` > `reserved`, `consumed`, `quarantined`, `to_destroy`, `lost`,
  `entered_in_error`;
- `reserved` > `available`, `distributed`, `to_destroy`;
- `quarantined` > `available`, `to_destroy`;
- `to_destroy` > `destroyed`;
- `lost` > `available` (found again);
- terminal: `consumed`, `destroyed`, `distributed`, `entered_in_error`.
`entered_in_error` is allowed only for a vial whose status never changed
(`status_changed_at` is null): a vial that had a life is corrected by its states, not
erased. One service, `vial_transition`, locks the row, checks the edge, needs a reason and
records the event; a guard trigger refuses every other edge, a delete and any change of the
identity columns. Reserved and distributed belong to distribution (#18, D19): the API and
the screen offer the other states only.

**D5 as built: placements.** `lineage.VialPlacement` is one interval of one vial in one
position: lab, vial, box, row, col, `placed_at` and `placed_by`, `removed_at` and
`removed_by`, and a removal reason (`moved`, `consumed`, `destroyed`, `distributed`,
`lost`, `entered_in_error`). Rows and columns are 1-based (D6).
- Partial unique indexes: one open placement per vial, one open placement per box position.
- The upper bound needs the box: the service checks it under the box's row lock, and the
  placement trigger checks it again on insert, with the box's kind and lab. The CHECK says
  row and col are 1 or more.
- A placement row never changes but for its one removal, and is never deleted (a trigger).
- A move closes the open row (`moved`) and opens a new one in one transaction. A vial that
  leaves the collection (`consumed`, `destroyed`, `distributed`, `entered_in_error`) or is
  `lost` has its open row closed with that reason by the transition; the vial trigger
  refuses those states while a placement is open, and the placement trigger refuses to open
  one for a vial in them. Quarantined, to destroy and reserved vials keep their place.
- Preserving a batch into a box locks the box, takes the free positions in fill order (row
  by row, A1, A2, ...), refuses when fewer are free than vials, writes the rows with
  `bulk_create` and records one event per vial plus a summary (`record_batch`).
- Every placement asks `storage.policy.may_store(box, strain.risk_group)` under the lab
  lock: a box only, active along its path, with a cap at or above the strain's risk group.
- `storage.services.box_occupied` counts open placements, so an occupied box keeps its size
  and is not retired. As announced with storage, lowering a unit's cap below the risk group
  of a strain stored in it or below it is refused, and so is moving a unit under a parent
  whose cap is lower than what it holds. The other side holds too: a strain's risk group is
  not raised above the effective cap of a box that holds one of its vials
  (`risk_group_above_box_cap`, on the risk group, naming no box, so a regulated strain's place
  stays masked). The strain service locks the lab, the strain, then those boxes; a lower
  group always fits.

**Who does what.** Viewers and up see passages, batches and vials (`strains.view`).
Technicians and up preserve, subculture, revive, place, move and change a vial's state
(`vials.handle`): the bench work. Every service takes the lab lock first, then the strain,
the vial and the box rows, and re-reads the actor's role under the lab lock.

**Events.** `passage_created`, `batch_created`, `vial_created` and `vials_created`,
`vial_placed` and `vials_placed`, `vial_moved`, `vial_status_changed` (reason required),
`vial_barcode_set`, each with the strain (D13).

Migration impact: additive. `lineage` 0003 adds `source_vial` (a nullable column, no
rewrite), replaces the source check (a scan of `lineage_passage`, small) and creates
`lineage_batch`, `lineage_vial` and `lineage_vialplacement`; 0004 attaches their row audit
and triggers. Audit 0018 extends the reason check of `audit_auditevent`, a scan of the audit
table under its lock. Reversible while no vial exists: `migrate lineage 0002`, then
`migrate labs 0002` and `migrate audit 0017` (ADR 0009 amendment of the same day).

Revisit when: a lab labels vials with its own scheme, a batch needs more than 200 vials,
a protocol needs aliquots used in part (a quantity), or a vial must sit in two places (a
straw in a goblet).

## Amendment 2026-10-20: the box grid (#15)

**D6 as built: the grid.** A box's page shows its positions as a grid, rows as letters and
columns as numbers (D6). `GET /labs/<lab>/boxes/<box>/` answers the box with its taken
positions, read in one query whatever the box holds; a position missing from the answer is
empty. Reading needs `strains.view` on a box the reader sees through `storage.view` (both a
viewer's). Technicians and up move a vial inside the box in two steps (pick it, then an empty
position) and place a vial they scanned. Both go through the vial's place action, so the
services, the locks and `may_store` are the ones of #16. Moving a vial to another box stays
on the strain page.

**D17 as built: scanning.** The vial list takes `code`: a barcode, matched exactly, or a label
as printed ("MYC 42 / 1 / 3", the accession number without regard to case). A scanner that
types like a keyboard needs nothing more: the box page has one field, and its Enter finds the
vial. Generating and printing labels stays open.

**Fill order.** Preserving into a box still fills row by row (A1, A2, ..., B1), and a scanned
vial starts at the first empty position in that order. A fill order per box type (by column, or
a lab's own numbering) is deferred until a lab asks.

Migration impact: none. A new read endpoint and a filter; no table changes.

