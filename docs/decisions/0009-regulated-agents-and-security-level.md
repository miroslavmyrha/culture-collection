# 0009 Regulated agents and security level

Date: 2026-10-18
Status: accepted (#50). Open questions listed at the end.
Amended 2026-10-19: location masking as built (#16). Amended 2026-10-20: the box grid (#15);
distribution of regulated strains (#18, part A). Amended 2026-10-22: the shipment before the
second person (#88); the second person at shipment (#89). Amended 2026-10-23: the
documents of a shipment (#90). Amended 2026-10-24: a restriction ends by two people (#105).
Amended 2026-11-03: the app keeps the VRAT access list (#167).
Deciders: maintainer

## Context

The collection may hold agents that the law controls:
- Czech highly risky agents (VRAT) and risky agents (RAT) under act
  281/2002 Sb. on biological weapons, listed in Annexes 1 and 2 of decree
  474/2002 Sb. Handling a VRAT, holding included, needs an SÚJB permit
  (§ 6). Handling a RAT needs a notice to SÚJB 14 days before the first
  handling (§ 17a). A VRAT holder keeps the agents locked and keeps an
  up-to-date list of the people with access (§ 14a). Both keep registers
  (§ 16, decree 474/2002 Sb. § 4 to § 6a).
- EU dual-use items under Regulation (EU) 2021/821, Annex I entries 1C351
  (human and animal pathogens), 1C353 (genetic elements and GMOs) and
  1C354 (plant pathogens). Export out of the EU needs an authorisation
  (Art. 3).
- Union quarantine pests (Regulation (EU) 2016/2031, Implementing
  Regulation (EU) 2019/2072 Annex II). Holding them for science needs an
  ÚKZÚZ permit (act 326/2004 Sb. § 8).
- Genetically modified organisms in contained use (act 78/2004 Sb.).

Risk groups 1 to 4 come from Directive 2000/54/EC, Article 2, as
transposed by nařízení vlády 361/2007 Sb., Příloha 7. They rate harm to
humans only. Animal and plant pathogens are not graded there.

No Czech act sets requirements on the lab's own information system. Act
281/2002 Sb. § 22(1) lets SÚJB issue decrees only on the lists, the forms,
the quantity caps and the register details. The cybersecurity act
264/2025 Sb. reaches the system only if the host institution provides a
regulated service and puts the system in its scope. WHO's Laboratory
biosecurity guidance (2024, 6.3.1 and 6.4.2) treats the inventory and the
storage locations of high-consequence agents as sensitive, with access for
a few named people.

So the security level is ours to set. OWASP ASVS 5.0 leaves the level to
the organisation and names level 2 as what most applications should reach.

## Decision

**Security level.** The system targets OWASP ASVS 5.0 level 2, plus three
level 3 requirements: 6.3.3 (a phishing-resistant hardware factor), 7.5.3
(further authentication before highly sensitive operations) and 16.3.2
(authorization decisions and access to sensitive data logged, without the
data itself). For now 16.3.2 covers the location reveals below. How far
read logging goes beyond them is open. Each feature issue names the
requirements it meets.

**Risk group and pathogenicity.** Every strain has a risk group 1 to 4 (a
check constraint), changed only by a service with a required reason. Two
separate fields record pathogenicity for animals and for plants, which the
risk group does not cover. A risk group 4 strain is refused at accession,
and so is a later change of a strain's risk group to 4 (2026-10-19, #54):
a lab that may not hold such an agent may not hold it after a
reclassification either.

**Restriction kinds.** A strain carries zero or more restrictions, each one
kind with a reference:
- `cz_vrat`: a highly risky agent, decree 474/2002 Sb., Annex 1.
- `cz_rat`: a risky agent, decree 474/2002 Sb., Annex 2.
- `dual_use`: an item of Annex I of 2021/821, with the entry (for example
  1C351.c) and the delegated act it was read in, because the annex is
  replaced every year.
- `quarantine_pest`: a Union quarantine pest of 2019/2072.
- `gmo`: a GMO in contained use, with its category.

One strain can carry several kinds. Ralstonia solanacearum race 3 biovar 2
is dual-use, a RAT and a quarantine pest at once. A strain with any
restriction is a regulated strain in this ADR.

**Lab authorisation.** A `cz_vrat` or `quarantine_pest` strain is accepted
only while its lab holds a valid authorisation row for that kind: permit
reference, issuer (SÚJB or ÚKZÚZ), valid from and expiry. The accession
service checks it. Rows are never deleted. A permit that ends gets an end
date. What an expired authorisation does to strains already held is decided
with the biosafety gates.

**Storage location of regulated strains.** Where a regulated strain is
stored is visible only to a person holding a separate permission, granted
to that person in that lab. No lab role implies it. Even then the location
is masked until the person reveals it explicitly, and each reveal is an
audit record (who, which strain, when, the request) written before the
response. List endpoints and exports never return it. This also meets
ASVS 14.2.6 (masked unless specifically viewed).

**Two-person rule.** Destruction, deaccession and distribution of a
regulated strain take effect only after a second person confirms them. The
first person requests, a different person who may perform the action
confirms. Nobody confirms their own request. The event holds both
identities and both times. The set of actions is a lab setting: these
three always, and a lab (a VRAT holder in particular) can add more.

**Second factor.** Sign-in needs a second factor on every login path, the
admin included. WebAuthn is the primary method, with several keys per
user. TOTP is the fallback. Recovery codes are valid for 24 hours. SMS is
never offered.

**Tamper evidence.** Every audit row (service events and row changes) joins
a hash chain: each row's hash covers its content and the previous hash, so
a row edited, removed or inserted inside the database breaks the chain from
that point. A command verifies the chain. Once a day the head of the chain
gets a qualified electronic timestamp from a qualified trust service
provider (eIDAS, Regulation (EU) No 910/2014, Article 41), which carries a
legal presumption of its date and of the integrity of the data it covers.
Someone who can edit rows can recompute the chain, but the stamped heads
then no longer match.

## Migration impact

None in this ADR. Each decision lands with its feature: risk group,
pathogenicity, restrictions and lab authorisations with the strain registry
(#11), location masking with storage (#14), the two-person rule with
distribution (#18) and deaccession (#20). The second factor and the hash
chain get issues of their own. The chain must exist before the first
production data, or the rows written before it stay outside it.

## Consequences

+ A regulated strain cannot enter a lab that may not hold it, and its
  location reaches only the people named for it.
+ No single account can destroy, deaccession or ship a regulated strain.
+ An edit of the history is detectable from outside the database.
- More friction: a reveal per look at a location, a second person for the
  gated actions, a hardware key per person.
- A qualified timestamp is a paid service from an external provider. A
  missed day leaves a gap in the anchors, not in the chain.
- The chain proves that history is intact. It does not stop someone with
  database access from changing data, only makes it visible.
- The app records decisions about people and locations. The locks stay the
  lab's duty; the app does not replace them. The list of the people with
  access to the VRAT agents (§ 14a(4)) is kept in the app (amendment of
  2026-11-03).

## Alternatives considered

- ASVS level 2 alone: no hardware factor, no step-up and no log of reads of
  sensitive data, which are the gaps that matter for agents like these.
  Full level 3: costly in places that add little here.
- Locations visible to every lab member, or a permission without masking:
  WHO's guidance asks for few people, and a masked value cannot be shoulder
  surfed or scraped from a list.
- Two persons for every register entry or every reveal: makes daily work
  hard. A lab that needs it can add the action.
- TOTP only: phishable. SMS: forbidden at ASVS level 3 (6.6.1). The host's
  single sign-on: moves the factor out of our control. It stays an option
  if the host requires it.
- Append-only tables and roles alone (today, ADR 0005): an owner can still
  rewrite rows. A chain without an anchor: whoever can edit rows can
  recompute it. A qualified electronic ledger (eIDAS Articles 45k, 45l):
  more than a lab register needs.

## Open questions

Not decided. Each needs an answer before the feature that depends on it:
- Standard alignment: align with ISO 35001 (biorisk management, clauses
  7.5.3, 7.5.4, 8.5 and 7.2.2) and do not certify yet. That is the
  recommendation, because edition 2 is in preparation.
- Hosting: where the system runs and who can reach the data. Making
  controlled technology available to a person outside the EU is an export
  (2021/821, Art. 2(2)(d)).
- Read logging: how far it goes beyond the location reveals decided above.
- Retention: a period and a disposal rule per record class. The longest
  known periods: ABS records 20 years after the end of use, closed VRAT and
  RAT registers 10 years, export records 5 years.
- The SÚJB register: an electronic register in the app, or the bound book
  SÚJB's guidance describes, with the app printing and reconciling it. The
  electronic one needs SÚJB's acceptance in writing.
- Cybersecurity act scope: whether the host registers a service under
  264/2025 Sb. and puts this system in its scope. That is the host's
  decision. If it does, its measures become legal duties with deadlines.
- Backups: where they are kept, encrypted, who can delete them, and how a
  restore is proven.

## Sources

Czech law (zakonyprolidi.cz, version in force on 2026-10-18):
- Act 281/2002 Sb.: https://www.zakonyprolidi.cz/cs/2002-281
- Decree 474/2002 Sb., lists replaced by 570/2025 Sb. from 1.1.2026:
  https://www.zakonyprolidi.cz/cs/2002-474,
  https://www.zakonyprolidi.cz/cs/2025-570
- SÚJB on the register:
  https://sujb.gov.cz/zakaz-biologickych-zbrani/evidence-biologickych-agens-a-toxinu
- Nařízení vlády 361/2007 Sb.: https://www.zakonyprolidi.cz/cs/2007-361
- Act 326/2004 Sb. (plant health): https://www.zakonyprolidi.cz/cs/2004-326
- Act 78/2004 Sb. (GMO): https://www.zakonyprolidi.cz/cs/2004-78
- Act 264/2025 Sb. (cybersecurity): https://www.zakonyprolidi.cz/cs/2025-264,
  decree 408/2025 Sb. (regulated services):
  https://www.zakonyprolidi.cz/cs/2025-408

EU law (Official Journal as first published):
- Directive 2000/54/EC: https://eur-lex.europa.eu/eli/dir/2000/54/oj
- Regulation (EU) 2021/821:
  http://publications.europa.eu/resource/celex/32021R0821, Annex I as
  replaced by Delegated Regulation (EU) 2025/2003:
  http://publications.europa.eu/resource/celex/32025R2003
- Regulation (EU) 2016/2031 and Implementing Regulation (EU) 2019/2072:
  http://publications.europa.eu/resource/celex/32016R2031,
  http://publications.europa.eu/resource/celex/32019R2072
- eIDAS, Regulation (EU) No 910/2014:
  http://publications.europa.eu/resource/celex/32014R0910, amended by
  Regulation (EU) 2024/1183:
  http://publications.europa.eu/resource/celex/32024R1183

Standards and guidance:
- OWASP ASVS 5.0.0: https://github.com/OWASP/ASVS/tree/v5.0.0/5.0/en
- WHO Laboratory biosecurity guidance (2024):
  https://www.who.int/publications/i/item/9789240095113
- ISO 35001:2019, under revision:
  https://committee.iso.org/standard/71293.html

Revisit when: the host answers the scope question, SÚJB answers on the
electronic register, ISO 35001 edition 2 is published, a new ASVS version
is released, or the lab plans work with risk group 4.

## Amendment 2026-10-19: location masking as built (#16)

Vials get places in #16, so the storage location of regulated strains is decided now. A
regulated strain is one with an active restriction of any kind.

**The permission is a row per person, not a role.** `labs.LocationGrant` names a user and a
lab, with who granted it, when and why, and when, by whom and why it was revoked. One open
grant per user and lab (a partial unique index); rows are never deleted and a revoked grant
never reopens (a guard trigger). A lab's managers grant and revoke it (`labs.manage_members`)
to members of the lab, each with a reason, recorded as `location_grant_added` and
`location_grant_revoked`. It is in no role's `GRANTS` and no role implies it. It counts only
while the holder is active and still a member: removing the member revokes the grant in the
same transaction, so adding the person back does not bring it back.

**Masked everywhere, revealed one vial at a time.** For a vial of a regulated strain every
response leaves the location out and says it is masked: the vial list, the vial detail, the
placement and transition responses, also for holders of the grant. A holder gets a reveal
action (`POST .../vials/<id>/reveal-location/`), which under the lab lock re-reads the grant
and the role, writes `vial_location_revealed` (actor, vial, strain, request id, no location)
in its own transaction, and only after the commit answers with the location. A failed write
is a failed response. The list endpoints never carry a regulated location, and there are no
exports yet; the one export path to come must keep it out (studies s8).

**Placing without the permission.** A technician or curator places and moves vials of a
regulated strain without the grant: the work at the bench needs no screen to find a
position, and the person who puts a vial in knows where it went. The response and every list
show the location masked afterwards, so the place is not kept on screen or in the browser's
cache. The placement events hold the box and position, as every placement does; the
strain's timeline (#19) must mask them for readers without the grant. Refused: making
placement need the grant, which would put the bench work of a regulated strain on the few
holders, and a placement that does not say where it put the vial, which a technician cannot
check.

**Known limits.** A refused position ("taken") tells that something occupies it, not what.
The box grid (#15) must show a regulated vial's cell as occupied without its strain to
anyone without a reveal. The event of a reveal names the vial, so the trail of reveals is
itself readable only by those who read the audit trail. A deactivated holder keeps the row;
it counts again only if the account is activated and still a member, which staff do.

Meets ASVS 5.0 14.2.6 (sensitive data masked unless specifically viewed) and 16.3.2 for
these reads (each reveal logged before the data is returned).

Migration impact: additive, `labs` 0003 and 0004 (the table, then its row audit and
guard) and the reason check of `audit_auditevent` (audit 0018). Reversible with `migrate
labs 0002` once the lineage tables of the same issue are gone.

## Amendment 2026-10-20: the box grid (#15)

The grid shows where vials are, so it masks the other way round: a box's position that holds a
vial of a regulated strain says `masked: true` and carries no vial, no strain and no label, in
every answer and for every reader, a holder of the location grant too. The grid has no reveal:
a holder reveals one vial at a time from its strain page, as before, and each reveal stays an
audited request. A masked position cannot be picked in the grid, so a regulated vial is moved
from its strain page. A vial found by its code and placed from the grid is announced without
its position when its strain is regulated, and the grid then shows that position as taken
only, so the place is not kept on screen.

Known limit, the same as for a refused position: the grid tells that some regulated vial is in
C4, not which. Someone who knows that a strain has one placed vial, and sees one masked
position, can guess. The masking keeps the place off the screen, not from the person at the
freezer. Refused:
leaving masked positions out (a technician would be sent to a taken position), and a reveal in
the grid (a reveal names a vial, not a position, and one per look keeps the trail readable).


## Amendment 2026-10-20: distribution of regulated strains (#18, part A)

Decided by the maintainer with the distribution study (s10):
- **Scope.** Category B (UN 3373) and exempt shipments to member states of the EU only. A request
  whose destination is outside the EU is refused when it is entered: for a regulated strain
  because export needs an MPO licence and an end-user statement this app does not record, for
  the others until export is built. Category A (UN 2814, UN 2900) is not shipped; a risk group 3
  line needs a manager, and the shipper classifies in part B.
- **Recipients.** Only institutions with a confirmed microbiology laboratory receive material,
  never private persons (ADR 0008 amendment of the same day).
- **Every legal gate blocks, with no override**: a VRAT only to a holder of a valid SÚJB permit
  naming it, or under an SÚJB exception (§ 13 h)); a RAT only to a requester with a valid § 17a
  notice (SÚJB asks senders to check; the maintainer chose to block); a quarantine pest only
  with a valid Letter of Authority naming it, with quantity and a sending left; a GMO only to a
  holder of a contained-use authorisation of its category or higher; ricin and saxitoxin entries
  not at all. A **regulated line needs a manager's approval** with a reason.
- **Two-person rule at shipment.** One person approves (`decided_by`, written once and held by
  the request trigger), a different person confirms the shipment of a regulated line in part B,
  and the confirmer runs the gates again on the ship day. Part B refuses a confirmation by the
  approver. Approval alone moves nothing out of the collection.
- **Masking.** Requests show reserved vials by their label only; no answer of distribution names
  a box or a position.

## Amendment 2026-10-22: the shipment before the second person (#88)

- **A regulated request is not shipped yet.** Until the confirmation by a second person exists
  (#89), the shipment of a request with any line of a regulated strain
  (`strains.selectors.regulating_restrictions()`) is refused with `second_person_required`, and
  the request page says so instead of offering the shipment. Unregulated requests ship with one
  person holding `distribution.manage`.
- **The gates first.** The shipment runs the gates again on the ship day before it asks for a
  second person: a regulated request whose permit expired since the approval answers
  `shipment_blocked` with the sentence, so nobody is asked to confirm what may not go.
- **Only two classes.** The shipment records `not_subject` or `un3373` and nothing else;
  Category A (UN 2814, UN 2900) and UN 3245 are not choices, in the API, the model's check and
  the form.
- **Masking.** The shipped vials are shown by their label only, like reserved ones; a shipped
  vial has no place (its placement is closed).

## Amendment 2026-10-22: the second person at shipment (#89)

A request with any line of a regulated strain (`strains.selectors.regulating_restrictions()`)
leaves in two steps, by two people who hold `distribution.manage`:

- **Prepare.** One person records the shipment, the same facts as a shipment in one step (class
  and basis, packing, coolant, the responsible person as a contact, carrier, tracking number).
  The gates run on that day and any blocker refuses (`shipment_blocked`). The request goes
  `approved > awaiting_confirmation`. Nothing leaves: the vials stay reserved.
- **Confirm.** A different person confirms the preparation they read: the request names its
  public id, and another one open now is `preparation_changed` (409). The confirmer is neither
  the approver (`decided_by`, `confirm_own_approval`) nor the preparer
  (`confirm_own_preparation`), both 403. The gates run again on the confirmation day (a permit
  that expired since the preparation blocks), and a risk group raised since then makes an
  exemption as non-pathogenic refused again (`not_exempt`). Then exactly what a shipment in one
  step does happens: reservations end as shipped, vials distributed, placements closed, the
  shipment with its vials, the request `shipped`, emptied distribution batches exhausted.
- **Withdraw.** The preparer or anyone else with `distribution.manage` withdraws a prepared
  shipment with a reason (`awaiting_confirmation > approved`). The preparation stays with its
  facts, who withdrew it, when and why; a new one may be prepared. A request awaiting
  confirmation is not cancelled, approved again or shipped in one step: it is confirmed or
  withdrawn first.

The approver may prepare. Two people are then still involved, and the confirmer is a third
whenever the approver prepared. Re-authentication before the confirmation (ASVS 7.5.3) waits for
the second factor.

**The model: a preparation row, the shipment written from it.** `distribution.ShipmentPreparation`
holds the package's facts (an abstract `Package` shared with `Shipment`, the same check
constraints by the same rules), `prepared_by` and `prepared_at`, and the withdrawal (by, at,
reason) written once. Its trigger refuses DELETE, any change but the one withdrawal, a
withdrawal of a confirmed preparation, and an insert for a request that is not approved; a
partial unique index keeps one preparation per request not withdrawn. The runtime role has
SELECT, INSERT and UPDATE. The confirmation inserts the `Shipment` with `preparation` pointing at
it: `classified_by` and `classified_at` are the preparer and the time of preparation (the person
who classified the package), `shipped_by` and `shipped_at` the confirmer and the time of
confirmation. So the shipment row records both people and both times without new columns.

Chosen over columns on the shipment written once (prepared_by and at, confirmed_by and at, the
row inserted at preparation): the #88 triggers hold a shipment frozen from its insert and
complete at commit (the request shipped, every reserved vial in it, each distributed). A
shipment row that exists before anything leaves, is changed once by the confirmation, and goes
away or stays orphaned when withdrawn, would have meant reopening all three guarantees and
"one shipment per request". The preparation row needs one trigger of its own and four lines in
the shipment guard; the #88 triggers stay as they are.

**What the database holds**, against any writer (the shipment guard, replaced in distribution
0008 from its 0005 body):
- a shipment without a preparation is of an approved request with no line of a strain with an
  active restriction;
- a shipment with one is of a request awaiting confirmation, confirms that request's
  preparation not withdrawn, repeats every package fact of it and its preparer and time as the
  classification, and its `shipped_by` is neither the preparer nor the request's `decided_by`;
- the request guard (also from 0005) allows `approved > awaiting_confirmation` only with a
  preparation not withdrawn, `awaiting_confirmation > approved` only once it is withdrawn, and
  `awaiting_confirmation > shipped` with the shipment; the approval stays as it was given in
  both states. `REQUEST_EDGES` and the trigger hold the same pairs (a test tries all 36).

**Codes.** A one-step shipment of a regulated request still answers `second_person_required`
(422), as in #88: the rule it names did not change, and clients that handle it keep working.
Its detail now says how: prepare, then a different person confirms. Preparing a request with no
regulated line answers `ship_in_one_step` (422).

**Events.** `request_shipment_prepared` on the request: the status, the preparation and the
package's facts, the responsible person as "changed". `request_shipment_withdrawn` with its
reason (required, audit 0021). The confirmation is `request_shipped`, actor the confirmer, with
the facts, the preparation, `prepared_by` and `prepared_at`, `confirmed_by` and `confirmed_at`
(users by public id, never by name), followed by the line and vial events of #88. A Letter of
Authority counts a request awaiting confirmation as it counts approved and shipped ones, and the
stock gate counts its reservations, not the free vials.

**Screens.** An approved regulated request offers Prepare the shipment (the shipment form). While
it waits, the page shows the prepared facts, Confirm the shipment to a person allowed to confirm
(an alertdialog showing what will be recorded), and Withdraw with a reason; the approver and the
preparer are told why they may not confirm (`confirm_refusal` in the answer, computed for the
caller). Withdrawn preparations stay listed.

Migration impact: `distribution` 0006 widens the request status to 30 characters (21 for
`awaiting_confirmation`; no rewrite of the table or its index, checked on PostgreSQL 18), 0007
adds the preparation table and the shipment's `preparation` column (nullable, no default) and
lets the status check accept `awaiting_confirmation`, 0008 attaches its row audit and triggers
and replaces the shipment and request guards (the reverse restores the 0005 bodies); `audit`
0021 adds the withdrawal to the reason check. Reversible while no preparation exists: `migrate
distribution 0005`, `migrate audit 0020`.

Revisit when: the second factor exists (step-up before the confirmation), a lab adds actions to
the two-person set (destruction and deaccession come with #20), or a shipment must go in parts.

## Amendment 2026-10-23: the documents of a shipment (#90)

The shipment writes the documents the law asks the sender to keep and hand over, in the same
transaction that ships (in one step and at the confirmation), from the data as it is at that
moment: after the vials left, under the locks of the shipment. Each is rendered once to plain
text, stored with its SHA-256 (`distribution.ShipmentDocument`) and never changed. Reading one
returns the stored text, never a new rendering: a strain renamed or a restriction ended later
changes no document that was sent.

**The three kinds** (s10, sections 2, 3, 5 and 8):
- **Delivery note**, for every shipment: request number, the recipient institution with its
  company number and delivery address, the package (transport class, packing instruction,
  coolant, carrier, tracking number, the responsible person and phone), and per line the strain
  (accession number and current name), its risk group, the terms and MTA version the line was
  pinned to, and each vial by its label. A line of a strain with an active `dual_use`
  restriction prints its Annex I entry and the notice Art. 11(9) of Regulation (EU) 2021/821
  asks for, in the regulation's words: "This item is subject to controls if exported from the
  customs territory of the Union". A line with an active `quarantine_pest` restriction says that
  the Letter of Authority it was approved against travels with the package (Regulation (EU)
  2019/829, Art. 6(1)), naming its reference.
- **ABS sheet**, for each line whose pinned terms are in scope of Regulation (EU) No 511/2014:
  the Art. 4(3) facts held on the terms version, under (a) when an IRCC is held, else under (b)
  (date and place of access, the source, PIC, access permit, MAT and the uses the MAT covers),
  and the sentence that the recipient keeps them 20 years after the end of use (Art. 4(6)).
- **Register entry and handover protocol**, for each line of a strain with an active `cz_vrat`
  or `cz_rat` restriction: the data decree 474/2002 Sb., Annex 3 asks of the sender's register
  (date, the agent as named, quantity issued, the strain's vials still in the lab, recipient,
  its registered office (the requester's seat, or "not known", never the delivery address; until
  2026-10-23 the delivery address stood there), IČO if known, document number = the request's
  number as the request page shows it, such as 2026/7; documents written before 2026-10-23 keep
  the shipment's public id there, as sent), and a protocol with places for both signatures, as
  SÚJB asks. The document says that the bound register book stays the legal register and the
  page gives the data of its entry (s10, section 3).

**What the database holds** (distribution 0010): the document's trigger refuses UPDATE and
DELETE; on insert it checks that `text_sha256` is the SHA-256 of the text, that the shipment is
of the document's lab and was written by this same transaction (its row's xmin is still in
progress, which only this transaction's own rows are when visible), that a line is of the
shipment's request, and that an ABS sheet is only for terms in scope and a register entry only
for a VRAT or RAT line. A deferred trigger on the shipment checks at commit that every document
it needs exists. The runtime role has SELECT and INSERT.

**Personal data.** The delivery note prints the responsible person's name and phone and the
delivery address, so a document is personal data. It stays out of every append-only audit row:
the event `shipment_document_generated` holds the document's id, kind, shipment and SHA-256, and
the row trigger stores the text column as `personal`. Erasing the contact (`contact_erase`)
does not rewrite a stored document. The trade-off is deliberate: the document is the record the
sender handed over and must keep (decree 474/2002 Sb., register records kept 10 years after the
book closes; 511/2014 Art. 4(6), 20 years for ABS information; WHO transport guidance, section
8, for transport documents), so the legal basis for keeping the name in it after an erasure
request is the sender's legal obligation (GDPR Art. 6(1)(c) and Art. 17(3)(b)). An erasure
empties the contact and everything the screens read from it; the documents keep what was sent.

**Who reads them.** Every reader of a request sees which documents its shipment has, with
their SHA-256. The text needs `distribution.view_requesters` (curators and managers), as every
document that names a person does; others get 404 for a document. `GET
.../shipment-documents/<id>/` answers the text as JSON, `.../download/` as a text file, both
`Cache-Control: no-store`.

Migration impact: additive. `distribution` 0009 adds the table, 0010 attaches its row audit and
its two triggers. Shipments recorded before #90 have no documents and are not given any (a
document is written only with its shipment). Reversible while no document exists: `migrate
distribution 0008`.

Revisit when: SÚJB accepts an electronic register (the entry would become the register), a
lab ships outside the EU (export documents, the end-user statement), the 5-day SÚJB notice of a
cross-border VRAT or RAT is built, or a recipient asks for PDF.

## Amendment 2026-10-24: a restriction ends by two people (#105)

Every rule of this ADR reads "regulated" from the strain's active restrictions
(`strains.selectors.regulating_restrictions()`): the manager's approval of a line, the shipment
in two steps, the register entry, the masking of locations. Ending a restriction was one
curator's action, so one person could take a strain out of all of them at once. A curator alone
could end a VRAT's restriction, approve and ship the request in one step with no register entry,
see where its vials are without the location grant, and add the restriction back, with nothing
on the strain showing the window. That broke "no single account can ... ship a regulated
strain". Ending a restriction is now one of the gated actions of the two-person rule:

- **Propose.** Someone with `strains.manage` (curator or manager) proposes to end a restriction,
  with the reason it will end with (`strain_restriction_end_proposed`, the reason required).
  Nothing changes for the strain: the restriction stays active, and with it every rule. One
  proposal per restriction is open at a time (`end_proposed`, 409).
- **Confirm.** A manager (`strains.confirm_restriction_end`, a manager's permission like
  `distribution.approve_regulated`) other than the proposer confirms the proposal they read: the
  request names its public id, and another one open now is `end_proposal_changed` (409). The
  proposer is refused (`confirm_own_end_proposal`, 403), a manager too. The restriction ends at
  the confirmation's time with the proposal's reason. The event `strain_restriction_ended` holds
  both people (public ids) and both times.
- **Withdraw.** Anyone with `strains.manage` withdraws the open proposal with a reason
  (`strain_restriction_end_withdrawn`). It stays with who withdrew it, when and why; a new one
  may be proposed.
- **The database holds it.** `strains_restrictionendproposal` is inserted open for an active
  restriction of its lab, settled once (confirmed or withdrawn), never deleted. A check
  constraint refuses a confirmer who is the proposer. The restriction's guard lets a restriction
  end only at the confirmation of a proposal to end it, at that time and with its reason, so
  `QuerySet.update()` and psql cannot skip the second person either. The runtime role has
  SELECT, INSERT and UPDATE on the proposals.
- **What people see.** The strain's restrictions carry the open proposal (reason, when) and
  `confirm_refusal` for the caller; it names nobody, so every reader of the strain may see it.
  The strain page offers the confirmation to the managers who may give it.

Two managers together, or a curator and a manager, may still end a restriction: that is the rule
for every gated action. Restrictions ended before #105 keep their end as it was.

Migration impact: additive. `strains` 0004 adds the table, 0005 attaches its row audit and its
trigger and replaces the restriction guard of 0003; `audit` 0022 adds the two event types to
`audit_auditevent_reason_required` NOT VALID and 0023 validates it in a transaction of its own
(as `audit.registry` asks of the append-only table). The one-step `.../restrictions/<id>/end/`
is gone. Reversible while no proposal exists: `migrate strains 0003` and `migrate audit 0021`.

## Amendment 2026-10-27: a regulated strain leaves the collection by two people (#20)

A deaccession ends a strain's requests and marks its vials for destruction (ADR 0008, amendment
of the same day). For a regulated strain (an active restriction of any kind,
`strains.selectors.regulating_restrictions()`) one person could take a VRAT out of the
inventory alone. WHO Laboratory biosecurity guidance (2024), p. 31, names "removal of biological
material from the inventory by two employees, which reduces errors during removal" (guidance,
not law; s11). So the deaccession of a regulated strain is a gated action of the two-person
rule, in the pattern of the end of a restriction (#105, amendment of 2026-10-24):

- **Propose.** Someone with `strains.manage` (curator or manager) proposes it, with the cause,
  the reason and for a quarantine pest the final use (`strain_deaccession_proposed`, reason
  required). Nothing changes for the strain, its requests or its vials. One proposal per strain
  is open (`deaccession_proposed`, 409). A strain that is not regulated is not proposed
  (`deaccession_in_one_step`, 422), and a regulated one is not deaccessioned in one step
  (`second_person_required`, 422).
- **Confirm.** A manager (`strains.confirm_deaccession`, a manager's permission like
  `strains.confirm_restriction_end`) other than the proposer confirms the proposal they read: the
  request names its public id (`deaccession_proposal_changed`, 409, when another is open). The
  proposer is refused (`confirm_own_deaccession`, 403), a manager too. A proposal whose final use
  no longer fits the strain's restrictions is refused (`deaccession_proposal_outdated`, 409). The
  strain leaves at the confirmation's time with the proposal's cause, reason and final use, and
  `deaccessioned_by` is the confirmer; `strain_deaccessioned` holds both people (public ids) and
  both times.
- **Withdraw.** Anyone with `strains.manage` withdraws the open proposal with a reason
  (`strain_deaccession_withdrawn`); it stays with who, when and why.
- **The database holds it.** `strains_straindeaccessionproposal` is inserted open for a strain of
  its lab in the collection, settled once, never deleted; a check constraint refuses a confirmer
  who is the proposer. The strain trigger lets a regulated strain become deaccessioned only at
  the confirmation of a proposal to deaccession it, by that confirmer, at that time, with its
  cause, reason and final use, so `QuerySet.update()` and psql cannot skip the second person.
  "Regulated" in the trigger is `ended_at IS NULL`, the twin of the Python predicate; a test
  builds every case the predicate tells apart (no restriction, an ended one, an active one of
  each kind) and asserts that the trigger agrees (ADR 0010, proposed). The runtime role has
  SELECT, INSERT and UPDATE on the proposals.
- **Its restrictions stay.** A deaccessioned regulated strain keeps its active restrictions: its
  vials wait for destruction and stay masked. Ending one still takes two people.
- **What people see.** The strain's detail carries `regulated` and the open proposal (cause,
  reason, final use, when, `confirm_refusal` for the caller), naming nobody, so every reader of
  the strain may see it. The strain page proposes from its menu and offers the confirmation to
  the managers who may give it.

Nothing is notified at deaccession: no article found asks for a notice to SÚJB of a destruction
or a deaccession of a VRAT or RAT strain, nor for GMO or dual-use items (s11). The destruction
itself, its register entry and the yearly quantities are a later issue.

Migration impact: as in ADR 0008, amendment of the same day.

## Amendment 2026-10-27: the reveal log (#83)

Who reads the trail of reveals, left open above ("readable only by those who read the audit
trail"): the lab's managers. They grant and revoke the location grant, so they read what the
holders did with it. A new permission, `vials.view_reveals`, in the managers' `GRANTS`; holding
the location grant does not give it, and it does not give the grant.

`GET /labs/<lab>/reveals/` (an action of the lab, so a non-member gets 404 and another role 403)
lists the lab's `vial_location_revealed` events, newest first, a page at a time: who, which vial
(its label and the strain's accession number) and when. Filters: `since` and `until`, Czech days
(Europe/Prague) with both ends included, and `person`, a user's public id, so the URL holds no
name. The events hold no location, and the answer names no box, path or position. The person is
read through the event's actor at read time (ADR 0005): an erased person reads as erased. A reveal
records no reason, so the log shows none. Home's activity still leaves reveals out
(`overview.activity.HIDDEN`).

Migration impact: none, a permission in code and a read.

## Amendment 2026-10-31: a confirmed proposal holds what it confirmed (#151)

The guards of #105 and #20 hold one direction: a restriction ends, and a regulated strain is
deaccessioned, only at the confirmation of a proposal. Nothing held the other one. A write past
the services could mark a proposal confirmed while the restriction stayed active or the strain
stayed in the collection, and the record would say that two people confirmed something that did
not happen. The services write both in one transaction (`strain_restriction_end_confirm`,
`strain_deaccession_confirm`), so only such a write could do it. Now the database holds both
directions, checked at commit by deferred constraint triggers (`strains` 0010):

- **A confirmed end proposal** has its restriction ended at the confirmation's time with the
  proposal's reason.
- **A confirmed deaccession proposal** has its strain deaccessioned at the confirmation's time,
  by the confirmer, with the proposal's cause, reason and final use.

The confirmation is written before the restriction or the strain, because their guards ask for
it, so the check waits for the commit; the confirm services set it deferred, also in a session
that set its constraints immediate.

Migration impact: additive, two functions and two triggers. A constraint trigger checks only
rows written after it exists. Reversible: `migrate strains 0009`.

## Amendment 2026-11-02: no vial of a regulated strain is destroyed by one person (#158)

The consequence above says that no single account destroys a regulated strain. Until now one
person who handles vials took a regulated strain's vial from to destroy to destroyed: that edge
was open for every strain, and nothing read the restrictions on it. Until the destruction record
with a second person exists (#160), the edge is refused for a vial of a strain with an active
restriction of any kind (`strains.selectors.regulating_restrictions()`):

- The service (`lineage.services.vial_transition`) refuses it with `destruction_needs_record`
  (400 on `status`). `lineage.models.vial_edges` takes the strain's regulation and drops the
  edge to destroyed.
- The vial trigger refuses it against every writer (`lineage` 0010), with the same definition
  in SQL (`ended_at IS NULL`); a test asserts both sides agree for each restriction kind and for
  an ended restriction.
- The vial screen does not offer Destroyed for such a vial and says why.

Marking the vial to destroy stays allowed, also at a deaccession, which marks the held vials
to destroy (#150). A strain without restrictions, or whose restrictions all ended, is unchanged.

Migration impact: the vial guard function replaced, no data change. A vial already destroyed
stays so. Reversible: `migrate lineage 0009`.

## Amendment 2026-11-02: the loss of a VRAT or RAT vial is reported to the police (#159)

Act 281/2002 Sb., § 5(5): whoever finds a loss of a highly risky or risky agent or toxin reports
it to the Police of the Czech Republic without undue delay, and the police tell SÚJB. Until now
the collection recorded a vial as lost and said nothing about this duty. The collection cannot
report for anyone; it states the duty and keeps the fact that the report was made:

- A loss that owes a report is a vial in the status lost whose strain had a cz_vrat or cz_rat
  restriction in force when the vial went lost (created at or before that moment, not ended by
  then): `lineage.selectors.reportable_loss()`. The other kinds (dual use, quarantine pest, GMO)
  are not on the lists of § 5(5). A restriction ended after the loss does not end the duty; one
  added after the loss does not create it.
- The report is `lineage.VialLossReport`: the vial, the moment of the loss (the vial's
  `status_changed_at` then), the Czech day of the report, the police reference, who recorded it
  and when. One per loss (unique vial and moment), so a vial found and lost again owes a new
  one. Added once, never changed or deleted: its trigger (`lineage` 0012) refuses UPDATE and
  DELETE and checks on insert that the vial is lost in that loss, that the strain was a VRAT or
  RAT then, and that the day is not before the loss. A test asserts the trigger and the Python
  definition agree for every restriction kind and for a restriction ended or added around the
  loss. Every column is row-audited; the runtime role has SELECT and INSERT.
- `lineage.services.vial_loss_report` records it with a reason (`vial_loss_reported`, reason
  required). Managers record it (`distribution.approve_regulated`: they answer to the authority
  for regulated agents). The body names the loss it read (`lost_at`): a vial found and lost
  again since is refused with `loss_changed`, not filed on the new loss. The reference is the
  police's and names no person; the event holds the report's id, the loss, the day and the
  reference.
- A vial found before a report is no longer lost: nothing is owed and nothing is recorded.
- The vial's state dialog states the duty with the section when Lost is chosen for a vial of a
  strain with an active cz_vrat or cz_rat restriction. Home lists each unreported loss for the
  lab's managers, oldest first and above every other group, linking to the vial on its strain's
  Material tab, where the vial row shows the loss as reported or not and offers the record to
  managers.

Migration impact: additive, a new table with its trigger and row audit, and one more event type
in the reason constraint (added NOT VALID, validated in its own migration). Reversible:
`migrate lineage 0010` and `migrate audit 0027`.

## Amendment 2026-11-03: the app keeps the VRAT access list (#167)

Act 281/2002 Sb., § 14a, as in force from 2022-02-01 (zakonyprolidi.cz):

> (4) Držitel povolení je povinen vytvořit a aktualizovat seznam osob, které mají přístup k vysoce
> rizikovému biologickému agens nebo toxinu.
>
> (5) Držitel povolení, který provozuje pracoviště podle § 5 odst. 6, kde se nakládá s vysoce
> rizikovým biologickým agens nebo toxinem, je povinen vytvořit seznam osob, které mají na toto
> pracoviště přístup.

(4): the permit holder makes and keeps up to date a list of the people who have access to a VRAT
agent or toxin. Not making it or not updating it is an offence of the permit holder (§ 21a(2)(f)),
fined up to 500 000 Kč (§ 21a(4)(c)). Until now the consequences above left this list to the lab
outside the app. The witness of a VRAT destruction (#160) must be a person on it, so the app keeps
it (decided by the maintainer on 2026-11-03: the witness only from people with approved access).
The act says nothing about the list's form or content; the app keeps who, from when, until when,
and who decided it, with a reason both ways.

**A row per person and lab, not a role.** `labs.VratAccess` names a user and a lab, who put them
on the list, when and why, and when, by whom and why the entry ended. One open entry per user and
lab (a partial unique index); a new entry is a new row, so the rows are the list's history. It is
in no role's `GRANTS`. A lab's managers put members on it and end entries (`labs.manage_members`,
like the location grant), each with a reason: `vrat_access_granted` and `vrat_access_ended`, both
`reason_required`. The events hold the person's public id, never a name. Separate from
`labs.LocationGrant`: seeing where a regulated strain is stored is not access to the agent, and
access to the agent does not need the place on a screen. They are not linked (see below).

**Only an active member is on it.** The service locks the user's row, then the lab, re-reads the
manager's role and refuses a user who is inactive, unknown or not a member of the lab, with the
same field error. Leaving the lab (`membership_delete`, so also `member_remove`), a deactivation
(`user_deactivate`, `users_deactivate`) and an erasure (`user_erase`) end the person's open
entries in the same transaction, under the lab lock, with a reason that names nobody ("The member
left the lab.", "The account was deactivated.", "The account was erased."). Activating the account
again or adding the person back does not reopen anything: a manager puts them on the list anew.

**Held by the database.** A guard trigger (`labs` 0006) refuses DELETE, any change but the one
end, and a reopening; on INSERT it refuses an entry that starts ended or names a user who is not
an active member of the lab. Two deferred constraint triggers hold the other direction at commit:
an account that became inactive holds no open entry, and a membership that is gone leaves no open
entry in its lab. The services end the entries before they deactivate or delete, so these hold
also in a session that set its constraints immediate. Every column is row-audited; the runtime role
has SELECT, INSERT and UPDATE, no DELETE.

**Erasure.** An erased person's entries stay: they are the history SÚJB may check. The row points
at the tombstone user, so the list shows `erased-<public_id>` with no name, read at read time
(ADR 0005).

**The question #160 asks.** `labs.selectors.has_vrat_access(user=, lab=, at=)`: whether the user
was on the lab's list at that moment (an entry created at or before it, not ended by then). It
reads the list's history, so it answers for a past moment as well; a service that decides on the
present holds the lab lock.

**On screen and on paper.** The lab page shows managers the list: who is on it now with an End
action, the form to put a member on it, and the ended entries. A printable page
(`/labs/<lab>/vrat-access`) shows the lab, the lab's SÚJB VRAT permits in force today
(`biosafety.LabAuthorisation` of kind `cz_vrat`, valid or expiring soon) or that none is, every
entry with from and until, who decided and why, and when it was printed; on paper the bar, the tabs
and the buttons are left out. The API refuses every other role (403 on the list, 404 on an
entry) and the screens show them neither.

**Not done here.** The list of the people with access to the workplace (§ 14a(5)) and the yearly
training of everyone with access (§ 14a(6), an offence under § 21a(2)(h)) stay the lab's duty
outside the app. A lab may keep the list before it holds a permit; nothing requires a permit to put
someone on it. Linking the list to the location grant (granting one with the other, or requiring
one for the other) is left out until a lab says how it works: the law ties neither to the other.

Migration impact: additive, `labs` 0005 and 0006 (the table, then its row audit and guards, with
the two deferred triggers on `users_user` and `labs_membership`), and two more event types in the
reason constraint of `audit_auditevent` (`audit` 0030, NOT VALID, validated by 0031). Reversible:
`migrate labs 0004` and `migrate audit 0029`.

## Amendment 2026-11-03: the destruction record and its second person (#160)

The amendment of 2026-11-02 (#158) refused the destruction of a regulated strain's vial until a
record with a second person existed. That record now exists, and it is the only way any vial
becomes destroyed (ADR 0008, amendment of the same day). What it asks depends on the strain's
active restriction kinds (`strains.selectors.regulating_restrictions()`, the union when a strain
has several), from the destruction study and the owner's decisions of 2026-11-02:

| Rule | none | `cz_vrat` | `cz_rat` | `dual_use` | `quarantine_pest` | `gmo` |
|---|---|---|---|---|---|---|
| a method code | yes | yes | yes | yes | yes | yes |
| a verification of the inactivation | no | yes | yes | yes | yes | yes |
| a manager other than the recorder confirms; the vials go then | no | yes | yes | yes | yes | yes |
| a witness, a member other than the recorder | no | yes | no | no | no | no |
| inactivated in the lab before an outside firm takes it | no | yes | yes | no | no | no |
| the method the lab's permit declares | no | no | no | no | yes | no |

Sources and reasons:

- **Second person.** No law found asks one for any kind (act 281/2002 Sb., decree 474/2002 Sb.,
  act 78/2004 Sb., decree 209/2004 Sb., Directive 2009/41/EC, Regulations 2016/2031, 2019/829,
  2021/821). It is this ADR's own rule ("No single account can destroy ... a regulated strain"),
  backed by WHO's Laboratory biosecurity guidance (2024, p. 31: "removal of biological material
  from the inventory by two employees"). The confirmer holds `vials.confirm_destruction`
  (managers), as the deaccession's (#20). The recorder never confirms, also as a manager: the
  service refuses (403 `confirm_own_destruction`) and a check constraint holds it. The service
  re-reads the confirmer's role under the lab lock.
- **Witness for a VRAT** (decision Q2): not found in the law either; a choice for the highest
  risk. The witness is an active member of the lab who handles vials, other than the recorder,
  named by user (ADR 0005: a user reference, never a name). Decided 2026-11-03: the witness will
  be limited to the lab's list of people with access to VRAT (act 281/2002 Sb., § 14a(4)), which
  does not exist yet and is built in its own issue (#n to follow); until then any such member.
- **Inactivated before an outside firm, VRAT and RAT** (decision Q9, extended to RAT by the
  owner on 2026-11-03): act 281/2002 Sb., § 13 h) lets a VRAT holder give the agent only to
  another permit holder, and SÚJB's page "Přesun a předání VRAT nebo RAT v rámci ČR" says "RAT si
  mohou navzájem poskytovat pouze osoby, které SÚJB ohlásily nakládání s RAT podle § 17a". A
  waste firm usually holds no permit and made no such notice.
- **Verification for every regulated kind** (decision Q4): the law asks it only for a GMO
  (decree 209/2004 Sb., § 8(8) h)); WHO LBM4 asks a validated decontamination for any agent.
- **The declared method for a quarantine pest** (decision Q6): Regulation (EU) 2019/829, Annex I
  (i) asks the application for "the method of destruction or treatment of the specified material
  on completion of the specified activity", and both ÚKZÚZ forms ask for it. The lab's permit
  row now stores it (`biosafety.LabAuthorisation.destruction_method`, set by staff with the
  permit, only for a quarantine pest's permit, a check constraint). A record uses the method of
  the permit in force on the day of the destruction, else of the last one started before it
  (material is destroyed when the activity ends, after a permit too: 2019/829, Art. 5 (d)), and
  names that permit. Another method is refused (`method_not_authorised`); the refusal says a
  change is notified to ÚKZÚZ first. A permit recorded before #160 has no method: staff record
  the permit again with its method (`authorisation_method_missing`), as for any wrong permit row.
- **A found vial of a destroyed strain** (#150, decision Q11) takes the same record and the
  same rules: nothing distinguishes it.

The database holds the shape against every writer (`lineage` 0014): the record's trigger checks
the kinds' rules on insert with the same definition of "regulated" in SQL (`ended_at IS NULL`),
and a deferred trigger refuses a destroyed vial whose record is not completed at that moment
with a confirmer for a regulated strain. Tests assert the trigger and the Python rules agree for
every kind, for an ended restriction and for none, as #158's test did. #158's refusal in the
vial guard is gone: the record and its confirmation hold it now.

The event of a record holds its id and number, the day, the method, the verification, whether an
outside firm took it (never the firm's name, which may be a sole trader's), the handover document
number, the run, the vials and the witness by public id. The confirmation's event holds both
people by public id and both times. The firm's name is a personal column in the row audit.

Still open, for part 2 of #160: the frozen protocol of a VRAT or RAT record with names and
signature lines (decision Q10, as the shipment documents), and the yearly export per agent for
the SÚJB declaration (decision Q8). The record holds what both need (see ADR 0008).

Migration impact: additive. A column with an empty default and a check constraint on the lab
permits; the vial guard replaced without #158's refusal. Reversible: `migrate lineage 0012`,
`migrate biosafety 0002`.
