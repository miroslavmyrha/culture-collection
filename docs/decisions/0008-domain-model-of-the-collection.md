# 0008 Domain model of the collection

Date: 2026-10-18
Status: accepted (#50)
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
