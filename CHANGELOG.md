# Changelog

Notable changes to this project, in the shape of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Every entry names the issue it comes from. An entry that changes a rule about regulated material
also names that rule's id in [docs/compliance.md](docs/compliance.md), so the path from a version
to the law the rule rests on is one hop.

## Unreleased
- Every commit of a pull request is checked on its own runner, in parallel, instead of one at a time on one machine (#213).

Everything below is the first development of the app. Nothing is released and no version is
tagged yet.

### Added

- Strain registry: a global taxon tree, an accession number per lab that is never reused, an
  identification history, risk groups, and restrictions of five kinds (#11, R-KIND-01 to
  R-KIND-09, R-RISK-01 to R-RISK-05).
- Lab authorisations: a SÚJB permit for highly risky agents and an ÚKZÚZ authorisation for
  quarantine pests, valid on Czech days, never deleted, and required before such a strain enters
  the lab (#11, R-PERMIT-01 to R-PERMIT-06).
- Permits screen per lab with each permit's issuer, reference, validity and status, what expires
  within 30 days first (#82, R-PERMIT-07).
- Deposit intake: depositors, access terms per deposit with every use decided, numbered MTA
  template versions with a checked SHA-256, and receipt, checking and the decision (#10, #12).
- The depositor's answer to a use left on request, recorded once with a note or the letter, which
  lets that line pass or rejects the request (#144).
- Storage hierarchy per lab: freezers, nitrogen tanks, racks and boxes, each root stating the
  highest risk group it may hold (#14).
- Batches and vials: subculture and revival passages, preservation batches with their method and
  purpose, vials with a label and an optional barcode, and their placement in boxes (#16).
- Box grid: a box's positions as a keyboard grid, with placing, moving and scanning a vial
  (#15, R-MASK-04).
- Several vials placed into one box in one step, all or nothing (#77).
- What a storage unit holds: boxes, vials and free positions per unit, and the organism on a box
  position (#80).
- Batch checks and release: identity, purity and viability checks as append-only rows, release
  only while the latest valid check of every kind passed (#17).
- Distribution requests: requesters with their recipient permits, the terms and the MTA pinned
  per line, one gate policy that blocks a line or asks a manager for a reason, and an approval
  that reserves named vials (#18, R-DIST-01 to R-DIST-13).
- Shipment of an approved request with its transport class, packing instruction, coolant, carrier
  and responsible person, with the gates run again on the Czech day of shipment (#88, R-DIST-14,
  R-SHIP-02, R-SHIP-04).
- Shipment documents written in the transaction that ships and kept as sent, with their SHA-256:
  a delivery note, an ABS sheet per line in scope, and a register entry with a handover protocol
  for each VRAT or RAT line (#90, R-SHIP-05 to R-SHIP-08).
- Where the reserved vials of a request lie, in the order of one walk through the storage (#143).
- Deaccession with a cause and a reason, settling the open requests, reservations and vials of the
  strain, and the final use a quarantine pest states when it leaves (#20, R-END-01, R-END-02).
- Destruction records: one strain's vials with the day, the method code and how the inactivation
  was verified, a second manager's confirmation for a regulated strain, a witness from the lab's
  VRAT access list for a VRAT, and an outside firm only after inactivation in the lab (#158,
  #160, R-END-03, R-END-05 to R-END-10).
- The police report of a lost VRAT or RAT vial, stated in the dialog with the section of the act
  and listed for managers until the day and the reference are recorded (#159, R-END-04).
- The lab's list of the people with access to its VRAT agents, with its history and a printable
  list for SÚJB (#167, R-ACCESS-01, R-ACCESS-02).
- Reveal log: which regulated vial each person revealed and when, for managers, filtered by Czech
  days and by person, and never the place (#83, R-MASK-05).
- Home: what waits for the signed-in person by role and lab, their labs with figures, recent
  activity and quick actions (#69).
- Vials by state on a manager's lab card (#81).
- Search from the top bar over strains, vials, deposits and requests, with an exact match opening
  at once (#76).
- Strain page by task: a header with the accession number, taxon, risk group, restrictions and
  status, and Overview, Material, Terms and History tabs with their own URLs (#19, #72).
- Strain list: the vials available for distribution per strain, as a column and a filter (#13).
- Strain filters by isolation source, country of origin and depositor (#84).
- The deposit a strain came from, on the strain page, for readers who may open deposits (#154).
- Growth conditions: media per lab, a temperature range and an atmosphere per strain, recorded
  again at each revival or subculture (#79).
- Labs and memberships with one role per lab (viewer, technician, curator, manager), and every
  lab-owned record scoped to the reader's labs (#9).
- App shell and visual base: navigation with a lab picker, sign-in and sign-out, light and dark
  schemes, status chips, and a layout that works at 320 px (#6, #7, #30).
- Audit trail: an event per write with its actor and reason, and a row trigger that records
  changes made past the application (#8).
- `docs/compliance.md`: every rule the app enforces about regulated material with its source, the
  quoted sentence, the code and the tests, the legal duties not enforced yet, and the questions
  put to SÚJB and ÚKZÚZ (#168).
- Data files of the official regulatory lists with a manifest naming each source, its version and
  its checksums, produced from the official texts and never edited by hand (#187, #201).
- Decision records for the domain model, the regulated-agent security level and the requirements
  a host must meet (#50, #198).
- `README.md` states what this is: a culture collection built to production quality as a
  simulation, with invented data and no review by a real collection or an authority (#2, #91).
- Development and end-to-end seed data per app, where a real taxon carries checked facts only
  (#56, #119, #121).
- Role walkthroughs: real tasks of the four roles walked in the browser and measured in steps,
  page loads and requests (#68).
- The checks every commit and every pull request runs: secrets, static analysis for known Django
  traps, migrations, deploy checks, the API contract, lint, types, tests, end to end, and a
  dependency audit daily and on a pull request that changes a lock file (#1, #4, #5, #132, #191,
  #192).
- This changelog, and a pull request that changes code adds its line to it (#206).

### Changed

- A strain is created only by accepting a deposit. The direct create endpoint and screen are gone
  (#12).
- A found vial of a strain whose material was destroyed can only go to destruction, never back
  into use (#150).
- The delivery note of a GMO line carries the words act 78/2004 Sb. § 11(1) asks for, with the
  category and the reference of the contained use (#173, R-SHIP-09).
- Distribution and lineage services are packages with one module per task, with the same public
  names and the same behaviour (#103).
- Frontend dependencies: react-hook-form 7.91, TanStack query and router, Vite above the three
  dev server advisories, oxlint 1.89, and filelock and certifi off their advisories (#109, #110,
  #131).

### Fixed

- A lab keeps at least one active manager: deactivation, batch deactivation and the admin form
  refuse the last one (#35).
- Sign-out says what happened: a 5xx, a network error or a CSRF 403 keeps the session, the caches
  and the page (#38).
- Accessibility: a focus ring on every control, one title per page and state, focus on the new
  page's heading after a navigation, and no sideways scroll at 320 px (#39).
- Screens keep their data, their open dialogs and typed text when a refresh fails, and a write
  refreshes what other features show (#63, #64).
- The deposit, request and strain lists keep the chosen filter when Search is pressed at once
  (#85).
- An invalid typed value stops the submit in every form with a number, date or code field, so no
  form saves the last valid value while the field shows an error (#111).
- One arrow key in a box grid renders the two cells that changed instead of all 81 (#128).
- Server errors shown on another field, the system setting for reduced motion followed, a prompt
  before the deposit form is left with unsaved changes, notices inside the shell, a failed box or
  taxon load that says so, and long lists saying how many rows are not listed (#66).
- An expiring lab permit on Home links to the lab's permits screen (#148).
- The register entry prints the request number people read and the requester's registered office,
  never the delivery address (#90).
- The production image runs `migrate` and serves the admin with its styles (#104).
- Sanitized HTML keeps `colspan` and `rowspan` (#3).
- Tests take the day in Czech time, read the day when they run, and hold one measured budget per
  suite, so a night run and a busy machine no longer fail them (#60).
- Role walkthroughs follow the app after the features and the seed data changed (#68, #82, #84).

### Security

- A risk group 4 agent is refused at accession and on every later change (#54, R-RISK-02).
- A restriction ends only by two people: a proposal and a confirmation by another manager (#105,
  R-KIND-07).
- Lowering a risk group takes two people, every risk group change names the basis of the new
  group, and a raise goes one step at a time (#174, R-RISK-03, R-RISK-06 to R-RISK-08).
- A regulated request ships in two steps by two people, and the confirmer is neither the approver
  nor the preparer (#89, R-SHIP-01).
- A confirmed proposal is refused at commit unless the strain left the collection or the
  restriction ended as the proposal said (#151, R-KIND-07, R-END-01).
- A regulated vial's location is masked in every answer, revealed only to a person holding a
  location grant, and each reveal is recorded before the location is read (#16, R-MASK-01 to
  R-MASK-03).
- A quarantine pest goes out only on a Letter of Authority the state of origin endorsed (#173,
  R-DIST-15).
- A requester's § 17a notice to SÚJB lets out only the agent it names (#173, R-DIST-05).
- A strain pathogenic to humans, animals or plants is not shipped as exempt, non-pathogenic
  (#173, R-SHIP-03).
- A GMO line ships as UN 3245 or UN 3373 with the basis the shipper states, never as exempt
  (#173, R-SHIP-02).
- The audit trail carries a hash chain written by the database with a daily qualified timestamp,
  and a command verifies both chains and their anchors from outside the application (#175,
  R-AUDIT-01 to R-AUDIT-05).
- The application runs as a database role that owns nothing and cannot truncate or alter, and the
  readiness check refuses to report ready otherwise (#34).
- No personal value enters an append-only audit row, and a person is erased to a tombstone (#37).
- Login limits per account and address with a doubling back-off and a known-device cookie, in
  place of a lock that shut out every other user of the account (#36).
- Django admin and the user commands write through the audited services, and a password change
  leaves a redacted marker, never the hash (#33).
- A list or a detail no longer loses its scope through an overridden `filter_queryset` (#3).
- gunicorn trusts `X-Forwarded-Proto` alone, so a client header passed on by the proxy cannot
  make a plain request https (#108).
- A redirect target is checked after it is built, so dot segments cannot turn a path into a
  protocol-relative URL (#38).
- A failed CSRF ask stops the write instead of sending it without a token (#66).
