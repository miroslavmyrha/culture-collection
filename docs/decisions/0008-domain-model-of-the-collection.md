# 0008 Domain model of the collection

Date: 2026-10-18
Status: accepted (#50)
Amended 2026-10-19: terms, contacts and the intake (#10, #12); storage (#14);
preservation, batches and vials (#16). Amended 2026-10-20: the box grid (#15); checks of a
batch and its release (#17); requests and the reservation (#18, part A).
Amended 2026-10-22: the shipment (#88); the two-person shipment of a regulated request (#89).
Amended 2026-10-23: the documents of a shipment (#90).
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
  Decided 2026-10-20, see the checks amendment below.
- D17 vial barcodes, generated labels and pre-printed codes: with
  preservation and batches (#16). Decided 2026-10-19, see the preservation
  amendment below.
- D18 requesters, records kept by curators or a portal: with distribution
  (#18). Decided 2026-10-20, see the requests amendment below.
- D19 when vials are reserved for a request: with distribution (#18).
  Decided 2026-10-20, see the requests amendment below.

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


## Amendment 2026-10-20: checks of a batch and its release (#17)

**D16: one check table with a kind, and a stage.** `lineage.BatchCheck` is one check of one
batch: lab, batch, `kind` (`identity`, `purity`, `viability`), `stage` (`after_preservation`,
`periodic`, `before_dispatch`), `checked_on` (a Czech day, not before the batch was preserved,
not in the future), `performed_by` (the user who records it), `method`, `method_detail`,
`result` (`pass`, `reduced`, `fail`), `value` with `unit`, the `vial` checked, a `note`,
`status` (`valid` or `entered_in_error`), `supersedes` and `reason`. OECD BRC guidelines,
General 10.3, and the WFCC guidelines, 8.2 to 8.5, ask for identity after receipt, before and
after preservation, at intervals and at dispatch, not viability alone, so one table holds all
three kinds. The receipt check stays on the deposit (#12): a deposit has no batch yet.
- Methods are a short list per kind, and `other` with the method described: identity by
  morphology, a biochemical profile, MALDI-TOF or gene sequencing; purity by streak plate or
  microscopy; viability by growth after revival, a plate count or live and dead staining. A
  check constraint holds the pairs. `method_detail` takes the medium, the temperature or the
  gene in words. To be confirmed with the curators before the first production data, like the
  uses of D10.
- A value is given with its unit or not at all: CFU/mL or a percentage (at most 100), stored
  as a decimal with four places.
- **Reduced counts as passed, with a note.** Reduced is a culture that grows and is pure but
  less than expected (fewer colonies, a slow start). It does not stop a release, so a batch
  of a slow but correct strain can be supplied; the check must say what was seen (a check
  constraint), and the history shows it to whoever releases.
- **Append-only.** A check is never changed or deleted (a guard trigger, and the runtime role
  has no DELETE). Its one change is `valid` to `entered_in_error` with a reason. A correction
  is a new check that `supersedes` the wrong one, of the same batch and kind, and enters it in
  error in the same transaction; a check is superseded at most once. Both triggers and
  services check that the vial and the superseded check belong to the batch.
- **The vial checked is consumed through the vial service** (`vial_transition` to consumed,
  with its own event and the placement closed). One vial may serve the checks of several
  kinds, because one thawed vial on one plate shows growth and purity: a vial already
  consumed by a check of the same batch may be named again. Any other vial that is not
  available is refused.

**The release rule.** A batch is released only while the latest valid check of each of the
three kinds, by the day checked and then the order recorded, passed or was reduced. The
latest is what counts: a pass after a failure clears the way, a failure recorded later but
dated before a pass is history.
- **A curator releases and holds, the checks only make it safer.** Recording a check is bench
  work (`vials.handle`, technicians and up). Releasing and holding are a curator's decisions
  with a reason (`batches.release`, curators and up), so the person who checks is not the only
  one who decides. The checks move a batch on their own only towards safety: when the latest
  valid check of a kind failed, a batch pending its checks or released goes on hold, with the
  check's day as the reason; when a released batch loses a passed check it was released on (a
  check entered in error), it waits for its checks again, or goes on hold when an older
  failure becomes the latest. Nothing is ever released without a person. A hold is lifted only
  by a release.
- **Edges.** `pending_check` to `released`, `on_hold` or `exhausted`; `released` to `on_hold`,
  `pending_check` or `exhausted`; `on_hold` to `released` or `exhausted`; `exhausted` is final.
  `lineage.models.BATCH_EDGES` and the batch trigger hold the same pairs (a test tries all 16
  against both), and the trigger refuses `released` while the latest checks do not pass. A
  batch stores why it has its status (`status_reason`) and when it changed; a check
  constraint asks for both from the first change on. No service sets `exhausted` yet:
  distribution (#18) or the last vial leaving does, decided there.
- Events: `batch_check_recorded`, `batch_check_entered_in_error` (reason required) and
  `batch_status_changed` (reason required), each with the strain (D13).

**What may be distributed.** `lineage.selectors.distributable()` is the one definition: a
released batch of distribution stock (D15: seed stock never leaves) of a strain that still
supplies (active or restricted, not pending or deaccessioned). `vials_for_distribution` reads
the available vials of such batches for #18, and the batch list counts them per batch
(`vials_distributable`), so the strain page answers "can we supply it" in one line.

**Screens.** The batch table shows each status with why a batch is not released (what it
waits for, or the recorded reason) and how many vials may go out. A batch's checks open in its
row as a disclosure: the latest result of each kind, the history with the checks entered in
error marked, and the actions (record, enter in error, release, hold). The history loads only
when the row is opened. A check shows the label of the vial used, never a place, so a
regulated strain's locations stay masked (ADR 0009).

Migration impact: additive. `lineage` 0005 adds `status_reason` (with a database default,
no rewrite) and `status_changed_at` to `lineage_batch` with a check constraint (a scan of the
batch table) and creates `lineage_batchcheck`; 0006 attaches its row audit and guard, and
replaces the batch guard (its body before is in 0004, restored on reverse). Audit 0019 extends
the reason check of `audit_auditevent`, a scan of the audit table under its lock. Reversible
while no check exists: `migrate lineage 0004` and `migrate audit 0018`.

Revisit when: a lab needs a maximum age for checks before a release or a dispatch (a lab
setting, the release rule then also reads `checked_on`), the curators want their own method
list, a check needs more than one value (a count and a percentage), or the receipt check of a
deposit should move into this table.

## Amendment 2026-10-20: requests and the reservation (#18, part A)

Distribution comes in two parts. Part A (this amendment) records who may receive material, the
requests with their lines, the gates, the decision and the vials reserved at approval. Part B
adds the shipment, its two-person confirmation, the register entry, the handover protocol and
the delivery note. The design study is s10 (distribution, read against primary sources).

**D18: requesters are institutions a curator enters** (recommendation a). A requester is an
institution, never a private person: a legal person or a natural person licensed to do business
(act 78/2004 Sb., § 16(1) allows only these to hold a GMO; DSMZ, CCM Brno and CECT supply only
institutions or microbiology laboratories). It has a country, an optional company number (the
register of part B asks for the IČO), an optional registered office (seat, as the business
register gives it: the institution's address, row audited like the institution, added in #90),
and the evidence that it runs a microbiology laboratory, with the day it was confirmed:
required, so no requester exists unconfirmed. Its responsible scientist is a `deposits.Contact`,
and the contact's postal address is the delivery address of the laboratory (D11: postal
addresses of requesters are contacts), so an erasure takes both and a request to an erased
requester is blocked. A portal for requesters stays for later.
- **Recipient permits** are the documents a requester holds: an SÚJB VRAT permit, a § 17a
  notice, an SÚJB exception decision, a Letter of Authority for a quarantine pest (with the
  quantity and sendings it allows and the endorsement of the state of origin), a contained-use
  authorisation for GMOs (with its category) and a permit to work with pathogens (with the
  highest risk group). Each is a row with its issuer, reference, validity in Czech days and its
  file; never deleted, ended once with a day and a reason. Import permits, export
  authorisations and end-use statements are out of part A: nothing leaves the EU.
- **Files** are rows of `distribution.Document`: the bytes in the database, their type read from
  the first bytes (PDF, PNG or JPEG), at most 10 MB, and a trigger that checks the SHA-256 and the
  size against the content on insert and refuses any change. No file name is kept (names often
  name people); the download answers an attachment named by the public id, not cached, to a
  caller who may see requesters. Refused: files on disk, which need a storage root, path checks
  and a serving rule of their own for a few documents per requester.

**Requests.** A request has a number per lab and year from a counter row taken under the lab
lock ("2026/7"), the requester, the destination copied from the requester when it is entered
(not typed twice), the use (D10), the end use in words (2021/821 Art. 12(4) and 281/2002 § 14(8)
ask for a concrete purpose), the containment level the requester declares, and who entered it.
Its status is `submitted`, then `approved`, `rejected` or `cancelled`; an approved request may
still be cancelled; part B adds `shipped`. `distribution.models.REQUEST_EDGES` and the request
trigger hold the same pairs (a test tries all 16). Approval and rejection write `decided_by`
and `decided_at` once; a rejection and a cancellation need a reason; an approval needs one when a
manager approves over a finding. Requests, refused ones too, are never deleted (OECD 11.5).
- **Lines** name a strain and 1 to 50 vials, one line per strain, and pin the terms version of
  the strain's deposit in force when the request was entered and that version's MTA (BCCM MTA,
  clause 14). A trigger refuses a line whose terms are not of its strain or whose MTA is not
  the terms', and any change. A strain without terms (no deposit) cannot be asked for. When the
  terms change after entry, the line keeps the old version and the policy blocks it: the request
  is cancelled and entered again under the new terms.
- **MTA acceptances** are recorded by a curator from the signed copy: per request and MTA version,
  the signer (a contact), the signer's role, whether the signer may bind the institution, the
  day and the file. Only an acceptance by someone who may bind the institution counts (ATCC:
  persons with full authority to bind). Never changed.

**MAT uses** (owner's default, recorded here). The uses by a subsequent user that the mutually
agreed terms cover are data on the terms version (`DepositTerms.mat_uses`, D10 values), for
material in scope of 511/2014 only (a check constraint). An in-scope line whose use the MAT does
not cover is blocked. An empty list means the MAT lets nothing go to a third party, so it covers
also the s10 row "third-party supply allowed by the original permits". Earlier in-scope versions
have an empty list until a new version records the MAT.

**The gates** are one function, `distribution.policy.evaluate(request, day)`, run at approval and,
in part B, again at shipment. Each finding has a stable code, a severity and a sentence that names
the strain. A blocker stops the approval with no override; a manager finding lets a manager
approve with a reason. From s10 section 8, within part A's scope (EU only, no Category A):
- request: the destination is outside the EU (`export_of_regulated_strain`, `export_not_supported`,
  also refused when the request is entered), the requester's contact was erased;
- line, the collection's own: fewer vials may go out than asked (`not_enough_vials`), the terms
  changed, ABS scope unknown, an in-scope use the MAT does not cover, a use the depositor denies,
  no MTA in the terms, no acceptance of the pinned MTA, a declared containment level below the
  risk group; a use allowed only on request to the depositor needs a manager;
- line, legal, each blocking: `cz_vrat` without a valid SÚJB permit or exception naming the taxon
  (281/2002 § 13 h)), `cz_rat` without a valid § 17a notice (owner's decision), a quarantine pest
  without a valid Letter of Authority naming it with quantity and a sending left (2019/829 Art. 6;
  approved requests count against it until part B counts shipments), a GMO without a contained-use
  authorisation of its category or higher (78/2004 § 3(1) c)), a dual-use entry 1C351.d.4 or d.5
  (Annex IV Part II: a transfer licence this collection does not hold);
- line, manager: risk group 2 or 3 without a work permit of that group (DSMZ A1), risk group 3
  (its culture may be Category A, which is not shipped: the shipper classifies in part B), and
  every regulated strain (ADR 0009).
"Names the taxon" reads the permit's `covers` text for the current taxon or, for a synonym, its
accepted name, as whole words without regard to case: a permit written with an older name
blocks, the safe side. The permits a line passed with are written at approval as `LinePermit`
rows, so the decision can be replayed.

**D19: specific vials reserved at approval, no expiry** (recommendation). Approval picks, for
each line, the available vials of `lineage.selectors.distributable()` of its strain (released
distribution stock of a strain that still supplies), locked in pk order with
`select_for_update(skip_locked=True)`, and raises before any write when fewer are free. Each
vial is set reserved through `lineage.services.vial_reserve_locked` (its own event) and gets a
`VialReservation` row: open while `ended_at` is null, one open per vial (a partial unique
index), changed once when it ends, never deleted. Deferred constraint triggers hold an open
reservation and the vial's reserved status together at commit, both ways. A reserved vial
leaves its state only through its request (`vial_transition` answers `vial_reserved`):
a cancellation ends its reservations (`cancelled`) and frees the vials; part B ends them as
`shipped`, deaccession (#20) as `deaccessioned`. Stock stays a query: no counter.

**Lock order:** lab, request, strain, batch, vial, box. The services lock the lab, then the
request row, then the strains of its lines by pk, then the vials; `distribution/tests/
test_lock_invariant.py` walks every public service.

**Who does what.** Every member reads requests (`distribution.view`): they name an institution,
never a person, and reserved vials by label, never a place (ADR 0009). Curators and managers
read requesters, permits, signers and files (`distribution.view_requesters`) and enter and decide
(`distribution.manage`); only managers approve over a manager finding
(`distribution.approve_regulated`).

**Events.** `requester_created`, `requester_changed`, `recipient_permit_added`,
`recipient_permit_ended` (reason), `request_submitted`, `request_line_added`,
`mta_acceptance_recorded`, `request_approved`, `request_line_reserved`, `request_rejected`
(reason), `request_cancelled` (reason), `request_line_released`. A request spans strains, so its
own events name none; each line event names its strain (D13), and so does each vial event.

Migration impact: additive. `deposits` 0004 adds `mat_uses` (a database default, no rewrite) with
two check constraints (a scan of the terms table, small). `distribution` 0001 to 0003 create the
tables, their row audit and triggers, including a deferred trigger on `lineage_vial`; `audit`
0020 extends the reason check of `audit_auditevent` (a scan under its lock). Reversible while no
request exists: `migrate distribution zero`, `migrate audit 0019`, `migrate deposits 0003`.

Revisit when: requesters ask for a portal, a lab ships outside the EU (export licences, end-use
statements and import permits as permit kinds), a permit lists its agents in a form a person
cannot match by name, or reservations must expire.

## Amendment 2026-10-22: the shipment (#88)

An approved request is shipped once, all its reserved vials at once, by one person holding
`distribution.manage`. The two-person confirmation of a regulated line (#89) and the documents
that travel with the package (#90) come later; the design input is s10, section 8, "Shipment".

**Status.** `approved > shipped` joins `REQUEST_EDGES` and the request trigger (a test compares
all 25 pairs). A shipped request is final: it is not cancelled. The approval's `decided_by`,
`decided_at` and reason stay as given; the request trigger lets a request become shipped only
once its shipment row exists.

**The shipment record** (`distribution.Shipment`, one per request, `distribution.ShipmentVial`,
unique per vial):
- the transport class the shipper decided, `not_subject` or `un3373` only (ADR 0009: Category A
  and UN 3245 are refused, never recorded), with its basis: an exemption (`exempt_non_pathogenic`,
  `exempt_inactivated`) for `not_subject`, `indicative_list` or `professional_judgement` for UN
  3373, and a note required for a judgement; who classified and when. The shipper classifies
  (WHO transport guidance 2025-2026, 2.1), so the app never computes the class. It refuses one
  thing it can know: a strain of risk group 2 or higher is pathogenic, so it is not exempt as
  non-pathogenic (`not_exempt`);
- the packing instruction, P650 required for UN 3373, and the coolant with its quantity in
  kilograms, required for dry ice (UN 1845, marked on the package);
- the responsible person who answers the phone about the package at all times (WHO 8.1): a
  `deposits.Contact` with a new `phone` column, so the name and the number stay out of every
  append-only row and go with an erasure (D11). The shipment row holds the contact's id;
- the carrier and the tracking number, who shipped and when. The ship day is today's Czech day
  (`permit_today()`): the shipper cannot name another day, so a permit that expired cannot be
  passed by backdating.
Both tables are insert-only: a trigger refuses UPDATE and DELETE, and the runtime role has
SELECT and INSERT only. A shipment vial is inserted only while its reservation for that line is
open; a reservation ends as `shipped` only for a vial a shipment holds; a vial is `distributed`
only when a shipment holds it; and a deferred trigger checks at commit that the request is
shipped, every one of its reservations ended as shipped, and the shipment holds exactly those
vials, each distributed.

**The service** `request_ship` locks lab, request, strains, batches, reservations, vials (the
lock invariant asserts strain before batch before vial). It runs the gates again on the ship
day; any blocker refuses (`shipment_blocked`, the sentences in the detail). Manager findings
were decided at approval and are not asked again. At shipment the stock gate counts the line's
open reservations whose vial is still in a distributable batch
(`reserved_vials_not_distributable`): a batch held after the approval stops the shipment until
it is released again. The gates come before the two-person rule: what may not go at all is said
first. Then a request with a regulated line (`regulating_restrictions()`) is refused with
`second_person_required` until #89. Otherwise the reservations end as shipped, each vial moves
to `distributed` through `lineage.services.vial_ship_locked` (its placement closed, its event),
the shipment and its vials are written, the request becomes shipped. Events: one
`vial_status_changed` per vial, one `request_line_shipped` per line (with the strain), one
`request_shipped` with the shipment's facts (the responsible person as "changed"), and one
`batch_status_changed` per batch that became exhausted. A Letter of Authority counts shipped
requests as it counted approved ones.

**Emptied.** After the shipment each distribution batch it drew from becomes `exhausted`, with
the reason "No vial is left to distribute after request <n> was shipped.", when none of its
vials is `available` or `reserved` (`lineage.services.batch_exhaust_if_emptied_locked`; the
batch trigger already allowed the edge). A vial in quarantine or lost does not keep the batch
open: it was not counted as stock, and a lost vial found later stays in an exhausted batch,
which distribution never reads; a new batch is preserved instead. A seed batch is never
exhausted by a shipment.

Migration impact: additive. `deposits` 0005 adds `phone` with a database default and replaces
the erased-contact check (a scan of the contacts table, small). `distribution` 0004 adds the two
tables and `shipped` to the request's status check; 0005 attaches their row audit and triggers
and replaces the request, reservation and vial-reservation trigger functions from 0003 (the
reverse restores the 0003 bodies). Reversible while no shipment exists: `migrate distribution
0003`, `migrate deposits 0004`.

Revisit when: #89 adds the second person (the regulated refusal becomes a confirmation step),
#90 adds the transport documents and the delivery note, a lab ships Category A or outside the
EU, or a request must ship in parts.

## Amendment 2026-10-22: the two-person shipment (#89)

A request with a regulated line is shipped in two steps (ADR 0009, amendment of the same day):
`approved > awaiting_confirmation` when one person prepares the shipment
(`distribution.ShipmentPreparation`), `awaiting_confirmation > shipped` when a different person
confirms it, `awaiting_confirmation > approved` when the preparation is withdrawn with a reason.
`REQUEST_EDGES` and the request trigger hold the same 36 pairs. A request awaiting confirmation
is not cancelled: it is withdrawn first, which keeps the reservations and the preparation
history together. The lock order stays lab, request, strain, batch, reservation, vial; the
preparation is read under the request's lock, which every writer of it holds.

## Amendment 2026-10-23: the documents of a shipment (#90)

A shipment writes its documents in the transaction that ships it, in one step
(`request_ship`) and at the confirmation (`request_confirm_shipment`), after the vials left:
`distribution.ShipmentDocument(shipment, kind, line, text, text_sha256)`, a delivery note for
every shipment, an ABS sheet per line whose pinned terms are in scope, a register entry with
its handover protocol per line of a VRAT or RAT. One per shipment, kind and line (a unique
index with NULLs not distinct). The rendering is `distribution.documents` (pure: it reads the
facts once and formats them), the write is `services._write_documents`, one
`shipment_document_generated` event per document after `request_shipped`, with the strain for a
line's document. What each document says, who reads it and why the text stays out of the audit
trail: ADR 0009, amendment of the same day.

Revisit when: a shipment goes in parts, or a document must be corrected after it was sent (a
correction would be a new document that names the one it replaces, never a change).

## Amendment 2026-10-27: how a strain is grown (#79)

A strain records its growth conditions and a passage records the ones it used. Walkthroughs V9
(look up the medium and temperature to grow a strain) and T6 (revive a vial to start a
subculture) had nowhere to read or write them. The sources agree that they belong to the strain
record: the OECD Best Practice Guidelines for BRCs (2007) list culture medium and growth
conditions in the minimum data set (General Best Practice Guideline 10.2; the microorganism
domain, section 7 and Table 2), and the WFCC Guidelines, 3rd ed. (2010), section 11.1, include
growth medium and temperature in the minimum strain record.

- **A new app, `growth`**, so that `strains` and `lineage` both point at it without a cycle.
  `growth.GrowthMedium(lab, name, composition_reference, retired_at)`: the lab's list of media.
  The name is unique per lab in any case. The reference is free text for the number in a public
  catalogue, such as a DSMZ medium number. A medium is never deleted (a trigger refuses it), it
  is retired with a reason, and a retired row never changes. A strain or passage that names a
  retired medium keeps it, and nothing new is given one.
- **Four columns on `Strain` and on `Passage`** (the abstract `GrowthConditions`):
  `growth_medium` (protected FK, null), `growth_temperature_low_c` and
  `growth_temperature_high_c` (whole degrees, both null or both set, 0 to 125 and low <= high;
  one value is a range with both ends equal, as CCM and ATCC print it), and `growth_atmosphere`
  (empty or one of `aerobic`, `microaerophilic`, `anaerobic`). The range limit of 125 is a bound
  on typing errors that the hyperthermophiles fit: the highest growth temperature known is
  122 C (Methanopyrus kandleri, Takai et al., PNAS 105, 2008). The atmosphere words are the ones
  the collections print: DSMZ MediaDive ("aerobic", "anaerobic"), CCM ("microaerophilic", e.g.
  Campylobacter sputorum, Medium 50, 37 C), ATCC product sheets ("Atmosphere: Anaerobic"). No
  finer vocabulary (CO2 percentages, capnophilic) is invented: a collection that needs one
  adds it from its own source. Both constraints are built from the Python constants.
- **Writes.** `growth.services.medium_create`, `medium_update` and `medium_retire` need
  `MANAGE_MEDIA` (curator, so also manager) and record `medium_created`, `medium_changed` and
  `medium_retired` (reason required). `strains.services.strain_set_growth` needs
  `MANAGE_STRAINS`, records `strain_growth_changed` with the changed fields and a required
  reason, and records nothing when nothing changed. `passage_subculture` and `vial_revive` take
  an optional growth and copy the strain's current conditions when none is given. Passage 0
  (the deposit) has none: nobody grew it here. The passage table is insert-only, so what it
  recorded cannot change; a later correction of the strain does not rewrite its history.
- **Lock order unchanged**: lab, then the strain, the vial and so on. The medium is read again
  under the lab lock; one of another lab is a field error, and a trigger holds the same rule
  for rows written past the services. The two new reason-required event types extend the audit
  CHECK in the usual two migrations (add NOT VALID, then VALIDATE).

Revisit when: a collection needs a medium per growth phase, a recorded growth result, or a
finer atmosphere vocabulary.

## Amendment 2026-10-27: deaccession (#20)

A strain leaves the collection without losing its history (D8: `active` or `restricted` >
`deaccessioned`, terminal). Walkthrough C10 (deaccession a strain that no longer grows) had no
screen for it: the strain list filtered by "Deaccessioned", nothing set it. The design is the lab
domain study (s3, section 7) and the duties the sources ask at deaccession (s11).

- **The strain records how it left**: `deaccessioned_at`, `deaccessioned_by`, a cause
  (`deaccession_cause`: `non_viable`, `contaminated`, `misidentified`, `duplicate`,
  `depositor_request`, `legal`, `lost`) and a reason in words (`deaccession_reason`, names
  nobody). The study called the code the reason; here it is the cause, because `reason` is the
  free text everywhere else in the app. A check constraint holds all four set if and only if the
  status is deaccessioned (`strains_strain_deaccession_iff_status`). The row, its number and its
  history stay (D2: a number is never given again).
- **A quarantine pest records its final use** (`final_use`: `destruction`, `collection`,
  `storage`), the words of Regulation (EU) 2019/829, Annex I (h) ("the final use of the specified
  material on completion of the specified activity e.g.; destruction, collection or storage").
  Only a strain with an active `quarantine_pest` restriction has one; the service and the strain
  trigger both refuse it missing and refuse it on any other strain.
- **One transaction, lock order lab, strain, requests, vials** (`strains.services`): every open
  request with a line of the strain (submitted or approved) is cancelled with the reason, which
  names the strain (`distribution.services.requests_cancel_for_deaccession_locked`); the
  reservations of its vials end as `deaccessioned`, those of the request's other strains as
  `cancelled` with their vials available again; the strain's vials still held (available,
  reserved, quarantined) become `to_destroy` where they are (`lineage.services.
  strain_vials_leave_locked`), one `vial_status_changed` each and one
  `vials_marked_for_destruction` batch event. A final use of `collection` or `storage` keeps the
  material: its vials are not marked, a reserved one is available again. Distributed vials stay
  as they went. A request awaiting the confirmation of its shipment is refused
  (`request_awaits_confirmation`, 409): the edge `awaiting_confirmation > cancelled` does not
  exist, so one of its two people withdraws the preparation first.
- **Request lines are not cancelled one by one.** Lines have no status, and a request ships all
  its lines at once (#88), so the whole open request is cancelled, also its lines of other
  strains; the curator enters a new request for the others. Decided 2026-10-27: a cancellation
  of single lines would touch the gates, the shipment, the documents and their triggers. The
  final use of a quarantine pest decides its vials (destruction marks them, collection and
  storage keep them), as Regulation (EU) 2019/829 Art. 5(d) allows, decided the same day.
- **Terminal.** The strain services refuse every change of a deaccessioned strain
  (`strain_deaccessioned`, 409): reclassification, risk group, growth, a new restriction. The
  end of a restriction still works, because its vials wait for destruction and stay regulated.
  The strain trigger refuses any change of the status or of the deaccession once deaccessioned,
  a deaccession from any status but active or restricted, and an INSERT of a deaccessioned
  strain. `request_submit` refuses a deaccessioned strain (`strain_deaccessioned` on the line).
- **What people see.** The strain list leaves deaccessioned strains out unless the status filter
  asks for them; their page stays reachable by link and by number. The page shows how the strain
  left and, from `GET .../strains/<id>/shipments/` (paginated, `distribution.view`), where its
  distributed vials went: request, institution, country, day and how many, for a notice to the
  recipients after a contamination or a misidentification (s3, section 7).
- **Who.** A strain that is not regulated is deaccessioned by one person with `strains.manage`
  (curator and up): the curator walkthrough holds the task (C10), and curators accession strains.
  A regulated one takes two people (ADR 0009, amendment of the same day).

Out of scope, for a later issue: the destruction itself (method, who, a witness, the VRAT/RAT
register entry), `to_destroy > destroyed` with the placement closed.

Migration impact: additive. `strains` 0008 adds the five nullable or defaulted columns with their
two check constraints (a scan of `strains_strain` under its lock, small) and the proposal table;
0009 attaches its row audit and its trigger and replaces the strain guard of 0003, now also on
INSERT; `audit` 0026 adds the four event types to `audit_auditevent_reason_required` NOT VALID and
0027 validates it. Reversible while no strain is deaccessioned and no proposal exists:
`migrate strains 0007` and `migrate audit 0025`.

Revisit when: a single line of a request must be cancelled, the destruction record lands, or a
strain must come back (a deaccession entered in error).
