# 0009 Regulated agents and security level

Date: 2026-10-18
Status: accepted (#50). Open questions listed at the end.
Amended 2026-10-19: location masking as built (#16). Amended 2026-10-20: the box grid (#15).
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
- The app records decisions about people and locations. The locks and the
  access list SÚJB checks (§ 14a(4)) stay the lab's duty. The app does not
  replace them.

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

