"""Registries of the audit trail: event types and the tables the row trigger watches.

This module imports no models, so models.py can build its constraints from it.

Event types: every code a service may record, with a timeline template. A code
registered twice raises at import. The types that need a reason are also a
check constraint on AuditEvent: adding one changes that constraint, and
`makemigrations --check` in check.sh fails until the migration exists. On a
large audit table write that migration as NOT VALID plus VALIDATE (RunSQL in
SeparateDatabaseAndState), because a plain AddConstraint scans the table under
an ACCESS EXCLUSIVE lock.

Row-audited tables: every regulated table, each column classified as audited,
excluded, secret or personal. The table's own migration attaches the triggers
with the same label, pk and classes (cultures.audit.operations.attach_row_audit).
The invariants in tests/test_invariants.py compare this dict with pg_trigger and
with the real tables and columns, so the three cannot drift apart.

No personal value enters an append-only row (ADR 0005, update of 2026-10-18):
personal columns are stored as a marker, service events record that a personal
field changed, never its value, and a user actor is labelled by its public id.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EventType:
    code: str
    template: str  # how a timeline renders it
    reason_required: bool = False


EVENT_TYPES: dict[str, EventType] = {}


def register(event_type: EventType) -> EventType:
    if event_type.code in EVENT_TYPES:
        raise ValueError(f"audit event type {event_type.code!r} is registered twice")
    EVENT_TYPES[event_type.code] = event_type
    return event_type


def reason_required_codes() -> list[str]:
    return sorted(code for code, kind in EVENT_TYPES.items() if kind.reason_required)


USER_DEACTIVATED = register(
    EventType("user_deactivated", "{actor} deactivated {subject}", reason_required=True)
)
USERS_DEACTIVATED = register(
    EventType("users_deactivated", "{actor} deactivated {count} users", reason_required=True)
)
LAB_CREATED = register(EventType("lab_created", "{actor} created lab {subject}"))
LAB_UPDATED = register(EventType("lab_updated", "{actor} changed lab {subject}"))
MEMBER_ADDED = register(EventType("member_added", "{actor} added {user} as {role}"))
MEMBER_ROLE_CHANGED = register(
    EventType("member_role_changed", "{actor} changed the role of {user} to {role}")
)
MEMBER_REMOVED = register(EventType("member_removed", "{actor} removed {user}"))
USER_CREATED = register(EventType("user_created", "{actor} created {subject}"))
USER_CHANGED = register(EventType("user_changed", "{actor} changed {subject}"))
USER_ACTIVATED = register(
    EventType("user_activated", "{actor} activated {subject}", reason_required=True)
)
USER_STAFF_CHANGED = register(
    EventType(
        "user_staff_changed", "{actor} changed staff status of {subject}", reason_required=True
    )
)
USER_SUPERUSER_CHANGED = register(
    EventType(
        "user_superuser_changed",
        "{actor} changed superuser status of {subject}",
        reason_required=True,
    )
)
USER_PASSWORD_CHANGED = register(
    EventType("user_password_changed", "{actor} changed the password of {subject}")
)
# Recorded by the login limits (system actor) when failures from many addresses reach
# LOGIN_ACCOUNT_MAX_FAILURES: until the window ends only known browsers may sign in.
LOGIN_ACCOUNT_UNDER_ATTACK = register(
    EventType(
        "login_account_under_attack",
        "{subject} is under a password attack: only browsers used before may sign in",
    )
)
USER_LOGIN_LIMITS_CLEARED = register(
    EventType(
        "user_login_limits_cleared",
        "{actor} cleared the login limits of {subject}",
        reason_required=True,
    )
)
# The person's values are gone from the user row, which stays as a tombstone (#37).
USER_ERASED = register(EventType("user_erased", "{actor} erased {subject}", reason_required=True))

# Taxonomy (ADR 0008, D4): global, changed by staff, no lab and no strain.
TAXON_CREATED = register(EventType("taxon_created", "{actor} added taxon {subject}"))
TAXON_CHANGED = register(EventType("taxon_changed", "{actor} changed taxon {subject}"))
TAXON_IDENTIFIER_ADDED = register(
    EventType("taxon_identifier_added", "{actor} added an external id to {taxon}")
)
TAXON_IDENTIFIER_REMOVED = register(
    EventType("taxon_identifier_removed", "{actor} removed an external id of {taxon}")
)

# Lab authorisations (ADR 0009): permits staff record for a lab. Ended, never deleted.
LAB_AUTHORISATION_ADDED = register(
    EventType("lab_authorisation_added", "{actor} recorded permit {permit_reference}")
)
LAB_AUTHORISATION_ENDED = register(
    EventType("lab_authorisation_ended", "{actor} ended a permit", reason_required=True)
)

# Strains (#11). Every event names its strain in strain_id (ADR 0008, D13).
STRAIN_CREATED = register(EventType("strain_created", "{actor} accessioned {accession_number}"))
STRAIN_RECLASSIFIED = register(
    EventType("strain_reclassified", "{actor} identified the strain anew", reason_required=True)
)
STRAIN_RISK_GROUP_CHANGED = register(
    EventType(
        "strain_risk_group_changed",
        "{actor} changed the risk group to {risk_group}",
        reason_required=True,
    )
)
STRAIN_RESTRICTION_ADDED = register(
    EventType("strain_restriction_added", "{actor} added a restriction", reason_required=True)
)
STRAIN_RESTRICTION_ENDED = register(
    EventType("strain_restriction_ended", "{actor} ended a restriction", reason_required=True)
)

# Depositors, MTA templates and deposits (#10, #12). A depositor event records a field of
# its contact as "changed" (PERSONAL_FIELDS). Deposit events name the strain from acceptance
# on (ADR 0008, D13).
DEPOSITOR_CREATED = register(EventType("depositor_created", "{actor} added a depositor"))
DEPOSITOR_CHANGED = register(EventType("depositor_changed", "{actor} changed a depositor"))
CONTACT_ERASED = register(
    EventType("contact_erased", "{actor} erased a contact", reason_required=True)
)
MTA_TEMPLATE_PUBLISHED = register(
    EventType("mta_template_published", "{actor} published MTA {code} version {version}")
)
DEPOSIT_RECEIVED = register(EventType("deposit_received", "{actor} received a deposit"))
DEPOSIT_TERMS_REPLACED = register(
    EventType("deposit_terms_replaced", "{actor} changed the terms", reason_required=True)
)
DEPOSIT_CHECK_STARTED = register(
    EventType("deposit_check_started", "{actor} started checking a deposit")
)
DEPOSIT_ACCEPTED = register(EventType("deposit_accepted", "{actor} accepted a deposit"))
DEPOSIT_REJECTED = register(
    EventType("deposit_rejected", "{actor} rejected a deposit", reason_required=True)
)
PASSAGE_CREATED = register(EventType("passage_created", "{actor} recorded passage {number}"))
# Storage (#14, ADR 0008, D14). Units hold no strains yet, so their events name none. A move
# records the parent and the path before and after: with the parent as the current pointer,
# these events are the units' location history (D5).
BOX_TYPE_CREATED = register(EventType("box_type_created", "{actor} added box type {name}"))
BOX_TYPE_CHANGED = register(EventType("box_type_changed", "{actor} renamed a box type"))
STORAGE_UNIT_CREATED = register(EventType("storage_unit_created", "{actor} added {kind} {name}"))
STORAGE_UNIT_CHANGED = register(EventType("storage_unit_changed", "{actor} changed {subject}"))
STORAGE_UNIT_MOVED = register(EventType("storage_unit_moved", "{actor} moved {subject}"))
STORAGE_UNIT_STATUS_CHANGED = register(
    EventType(
        "storage_unit_status_changed", "{actor} set {subject} to {status}", reason_required=True
    )
)

# Location grants (ADR 0009, amendment of 2026-10-19): who may see where a lab's regulated
# strains are stored. Per person, with a reason both ways.
LOCATION_GRANT_ADDED = register(
    EventType(
        "location_grant_added", "{actor} let {user} see regulated locations", reason_required=True
    )
)
LOCATION_GRANT_REVOKED = register(
    EventType(
        "location_grant_revoked",
        "{actor} revoked the regulated locations of {user}",
        reason_required=True,
    )
)
# Preservation, batches and vials (#16, ADR 0008 amendment of 2026-10-19). Every event names
# the strain. A placement event holds the box and position; the timeline (#19) masks them
# for a regulated strain. A reveal holds no location at all.
BATCH_CREATED = register(EventType("batch_created", "{actor} preserved batch {number}"))
VIAL_CREATED = register(EventType("vial_created", "{actor} added vial {seq}"))
VIALS_CREATED = register(EventType("vials_created", "{actor} added {count} vials"))
VIAL_PLACED = register(EventType("vial_placed", "{actor} placed {subject}"))
VIALS_PLACED = register(EventType("vials_placed", "{actor} placed {count} vials"))
VIAL_MOVED = register(EventType("vial_moved", "{actor} moved {subject}"))
VIAL_STATUS_CHANGED = register(
    EventType("vial_status_changed", "{actor} set {subject} to {status}", reason_required=True)
)
VIAL_BARCODE_SET = register(EventType("vial_barcode_set", "{actor} set the barcode of {subject}"))
VIAL_LOCATION_REVEALED = register(
    EventType("vial_location_revealed", "{actor} revealed where {subject} is stored")
)
# Checks of a batch and its release (#17, ADR 0008, D16). Every event names the strain. A batch
# moved by a check records its status change with the check's words as the reason.
BATCH_CHECK_RECORDED = register(
    EventType("batch_check_recorded", "{actor} recorded a {kind} check of {subject}")
)
BATCH_CHECK_ENTERED_IN_ERROR = register(
    EventType(
        "batch_check_entered_in_error",
        "{actor} entered a check of {subject} in error",
        reason_required=True,
    )
)
BATCH_STATUS_CHANGED = register(
    EventType("batch_status_changed", "{actor} set {subject} to {status}", reason_required=True)
)

# Distribution (#18, part A). A requester's and a signer's personal fields are recorded as
# "changed" (PERSONAL_FIELDS). A request spans strains, so its own events name none; each line
# event names its strain (ADR 0008, D13), and so does every vial event it causes.
REQUESTER_CREATED = register(EventType("requester_created", "{actor} added a requester"))
REQUESTER_CHANGED = register(EventType("requester_changed", "{actor} changed a requester"))
RECIPIENT_PERMIT_ADDED = register(
    EventType("recipient_permit_added", "{actor} recorded a recipient's {kind} {reference}")
)
RECIPIENT_PERMIT_ENDED = register(
    EventType("recipient_permit_ended", "{actor} ended a recipient's permit", reason_required=True)
)
REQUEST_SUBMITTED = register(EventType("request_submitted", "{actor} entered request {number}"))
REQUEST_LINE_ADDED = register(EventType("request_line_added", "{actor} asked for {quantity} vials"))
MTA_ACCEPTANCE_RECORDED = register(
    EventType("mta_acceptance_recorded", "{actor} recorded an acceptance of the MTA")
)
REQUEST_APPROVED = register(EventType("request_approved", "{actor} approved {subject}"))
REQUEST_LINE_RESERVED = register(
    EventType("request_line_reserved", "{actor} reserved vials for a request")
)
REQUEST_REJECTED = register(
    EventType("request_rejected", "{actor} rejected {subject}", reason_required=True)
)
REQUEST_CANCELLED = register(
    EventType("request_cancelled", "{actor} cancelled {subject}", reason_required=True)
)
REQUEST_LINE_RELEASED = register(
    EventType("request_line_released", "{actor} released the vials of a request")
)


@dataclass(frozen=True)
class RowAudit:
    """How the row trigger treats one table. Every column is in exactly one class.

    label: the stable name stored on every RowChange, kept when the table is renamed.
    pk: the primary key columns, stored as text (a JSON array when there are several).
    exclude: noise, never stored, in no INSERT, UPDATE or DELETE row.
    secret: values never stored either, but an UPDATE that changes one records
    the column with the marker SECRET_MARKER as its old and new value, so a
    password change leaves a row without the hash (audit migration 0006).
    personal: values that name or reach a person (names, email, username). Every
    INSERT, UPDATE and DELETE row stores the marker PERSONAL_MARKER in their
    place, so the trail shows that the column was set or changed, and erasing a
    person never needs to touch an audit row (audit migration 0010, #37).
    audited: the other columns, listed so that a new column fails the
    classification invariant until someone decides which list it belongs to.
    """

    label: str
    audited: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    pk: tuple[str, ...] = ("id",)
    secret: tuple[str, ...] = ()
    personal: tuple[str, ...] = ()


# The value the row trigger stores for a changed secret column. Not a password (S105).
SECRET_MARKER = "redacted"  # noqa: S105
# The value the row trigger stores for a personal column, in every row that has the column.
PERSONAL_MARKER = "personal"


ROW_AUDITED_TABLES: dict[str, RowAudit] = {
    "users_user": RowAudit(
        label="users.user",
        # Ids, privilege flags and the join date say what happened to the account, not who
        # it is. They stay readable, and stay after an erasure.
        audited=(
            "id",
            "is_staff",
            "is_active",
            "is_superuser",
            "date_joined",
            "public_id",
            "erased_at",
        ),
        exclude=("last_login",),  # noise on every login
        secret=("password",),
        # The username is often a person's name or email address, so it is personal too.
        personal=("username", "first_name", "last_name", "email"),
    ),
    "labs_lab": RowAudit(
        label="labs.lab",
        # name and code name an organisational unit, not a person: the trail keeps their
        # values so old labels stay traceable. A lab is named after its field or unit;
        # a lab named after a person keeps that name in its history (ADR 0005, 2026-10-18).
        audited=("id", "public_id", "created_at", "updated_at", "name", "code"),
    ),
    "labs_membership": RowAudit(
        label="labs.membership",
        # Internal ids and a role: the person is reached only through users_user.
        audited=("id", "public_id", "created_at", "updated_at", "user_id", "lab_id", "role"),
    ),
    "taxonomy_taxon": RowAudit(
        label="taxonomy.taxon",
        # authority is a nomenclatural citation ("(Ehrenberg 1835) Cohn 1872"), part of the
        # published name, not a record about a person: its values stay in the trail.
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "name",
            "authority",
            "rank",
            "parent_id",
            "status",
            "accepted_id",
        ),
    ),
    "taxonomy_taxonidentifier": RowAudit(
        label="taxonomy.taxonidentifier",
        audited=("id", "public_id", "created_at", "updated_at", "taxon_id", "system", "value"),
    ),
    "strains_strain": RowAudit(
        label="strains.strain",
        # name_as_received, isolation_source: free text about the material, naming nobody.
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "accession_number",
            "accession_seq",
            "status",
            "name_as_received",
            "taxon_id",
            "risk_group",
            "animal_pathogenicity",
            "plant_pathogenicity",
            "isolation_source",
            "country_of_origin",
            "isolation_date",
        ),
    ),
    # A counter changed outside the accession service would hand out a number twice.
    "strains_straincounter": RowAudit(
        label="strains.straincounter", audited=("lab_id", "last_seq"), pk=("lab_id",)
    ),
    "strains_strainidentification": RowAudit(
        label="strains.strainidentification",
        # method and reason: free text that names nobody.
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "strain_id",
            "taxon_id",
            "identified_on",
            "method",
            "reason",
            "is_current",
        ),
    ),
    "strains_strainrestriction": RowAudit(
        label="strains.strainrestriction",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "strain_id",
            "kind",
            "reference",
            "act",
            "gmo_category",
            "ended_at",
            "end_reason",
        ),
    ),
    "storage_boxtype": RowAudit(
        label="storage.boxtype",
        audited=("id", "public_id", "created_at", "updated_at", "name", "rows", "cols"),
    ),
    "storage_storageunit": RowAudit(
        label="storage.storageunit",
        # path is derived from parent_id by the trigger, but a move shows in it: kept.
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "kind",
            "name",
            "parent_id",
            "slot",
            "barcode",
            "status",
            "retired_at",
            "box_type_id",
            "rows",
            "cols",
            "temperature_c",
            "max_risk_group",
            "path",
        ),
    ),
    "biosafety_labauthorisation": RowAudit(
        label="biosafety.labauthorisation",
        # end_reason is free text that names nobody, like every reason (ADR 0005, 2026-10-18).
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "kind",
            "issuer",
            "permit_reference",
            "valid_from",
            "expires_on",
            "ended_on",
            "end_reason",
        ),
    ),
    # Deposits (#10, #12). The depositor holds ids and its institution, an organisation; the
    # person is in deposits_contact (NOT_ROW_AUDITED). Notes and reasons name nobody.
    "deposits_depositor": RowAudit(
        label="deposits.depositor",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "contact_id",
            "institution",
        ),
    ),
    "deposits_mtatemplate": RowAudit(
        label="deposits.mtatemplate",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "code",
            "version",
            "title",
            "text",
            "text_sha256",
        ),
    ),
    "deposits_deposit": RowAudit(
        label="deposits.deposit",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "depositor_id",
            "status",
            "received_on",
            "condition",
            "condition_note",
            "name_as_received",
            "depositor_passages",
            "strain_id",
            "decided_at",
            "rejection_reason",
        ),
    ),
    "deposits_depositterms": RowAudit(
        label="deposits.depositterms",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "deposit_id",
            "version",
            "is_active",
            "mta_id",
            "abs_scope",
            "country_of_origin",
            "collection_date",
            "pic_reference",
            "mat_reference",
            "ircc",
            "permit_reference",
            "mat_uses",
            "reason",
        ),
    ),
    "deposits_termsuse": RowAudit(
        label="deposits.termsuse", audited=("id", "terms_id", "use", "decision")
    ),
    "lineage_passage": RowAudit(
        label="lineage.passage",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "strain_id",
            "number",
            "source_deposit_id",
            "source_passage_id",
            "source_vial_id",
        ),
    ),
    # #16. Free text (the protectant) names nobody; placed_by and removed_by are internal
    # user ids, the person is reached only through users_user.
    "lineage_batch": RowAudit(
        label="lineage.batch",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "strain_id",
            "passage_id",
            "number",
            "method",
            "cryoprotectant",
            "preserved_on",
            "vial_count_created",
            "purpose",
            "status",
            "status_reason",
            "status_changed_at",
        ),
    ),
    # #17. Method details, notes and reasons are free text that names nobody; performed_by is
    # an internal user id, the person is reached only through users_user.
    "lineage_batchcheck": RowAudit(
        label="lineage.batchcheck",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "batch_id",
            "kind",
            "stage",
            "checked_on",
            "performed_by_id",
            "method",
            "method_detail",
            "result",
            "value",
            "unit",
            "vial_id",
            "note",
            "status",
            "supersedes_id",
            "reason",
        ),
    ),
    "lineage_vial": RowAudit(
        label="lineage.vial",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "batch_id",
            "seq",
            "barcode",
            "status",
            "status_changed_at",
        ),
    ),
    "lineage_vialplacement": RowAudit(
        label="lineage.vialplacement",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "vial_id",
            "box_id",
            "row",
            "col",
            "placed_at",
            "placed_by_id",
            "removed_at",
            "removed_by_id",
            "removal_reason",
        ),
    ),
    # ADR 0009: who may see regulated locations. Ids, times and reasons that name nobody.
    "labs_locationgrant": RowAudit(
        label="labs.locationgrant",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "user_id",
            "granted_by_id",
            "reason",
            "revoked_at",
            "revoked_by_id",
            "revoke_reason",
        ),
    ),
    # #18. The requester holds ids and its institution, an organisation; the responsible
    # scientist and the delivery address are its contact (NOT_ROW_AUDITED). Evidence, end use,
    # covers and reasons are free text that names nobody; user ids reach people only through
    # users_user.
    "distribution_requester": RowAudit(
        label="distribution.requester",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "contact_id",
            "institution",
            "legal_form",
            "registration_number",
            "country",
            "lab_evidence",
            "lab_confirmed_on",
        ),
    ),
    "distribution_document": RowAudit(
        label="distribution.document",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "content_type",
            "size_bytes",
            "sha256",
        ),
        # The file itself: its SHA-256 is audited, the bytes would flood the trail.
        exclude=("content",),
    ),
    "distribution_recipientpermit": RowAudit(
        label="distribution.recipientpermit",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "requester_id",
            "kind",
            "issuer",
            "issuer_country",
            "reference",
            "valid_from",
            "expires_on",
            "covers",
            "quantity_allowed",
            "sendings_allowed",
            "endorsement_reference",
            "endorsed_on",
            "gmo_category",
            "risk_group",
            "document_id",
            "ended_on",
            "end_reason",
        ),
    ),
    "distribution_distributionrequest": RowAudit(
        label="distribution.distributionrequest",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "year",
            "number",
            "requester_id",
            "destination_country",
            "use",
            "end_use",
            "containment_level",
            "status",
            "submitted_by_id",
            "decided_by_id",
            "decided_at",
            "decision_reason",
            "cancelled_by_id",
            "cancelled_at",
            "cancel_reason",
        ),
    ),
    # A counter changed outside the services would hand out a request number twice.
    "distribution_requestcounter": RowAudit(
        label="distribution.requestcounter", audited=("id", "lab_id", "year", "last_number")
    ),
    "distribution_requestline": RowAudit(
        label="distribution.requestline",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "request_id",
            "strain_id",
            "quantity",
            "terms_id",
            "mta_id",
        ),
    ),
    "distribution_linepermit": RowAudit(
        label="distribution.linepermit", audited=("id", "line_id", "permit_id")
    ),
    "distribution_mtaacceptance": RowAudit(
        label="distribution.mtaacceptance",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "request_id",
            "mta_id",
            "signer_id",
            "signer_role",
            "authorised_signatory",
            "accepted_on",
            "document_id",
        ),
    ),
    "distribution_vialreservation": RowAudit(
        label="distribution.vialreservation",
        audited=(
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "lab_id",
            "line_id",
            "vial_id",
            "reserved_at",
            "reserved_by_id",
            "ended_at",
            "ended_by_id",
            "end_reason",
        ),
    ),
}


# The columns of deposits_contact: all of them name or reach a person.
CONTACT_PERSONAL = ("name", "email", "postal_address")
# What a service event records for a personal field that was set or changed, never the value.
PERSONAL_CHANGED = "changed"
# The personal fields of each event subject type. record_event() and record_batch() write
# PERSONAL_CHANGED in their place, whatever the service passed (cultures.audit.events).
PERSONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "user": ROW_AUDITED_TABLES["users_user"].personal,
    # A contact's values, also in the events of the depositor that holds it (ADR 0008, D11).
    "contact": CONTACT_PERSONAL,
    "depositor": CONTACT_PERSONAL,
    # A requester's responsible scientist and delivery address, an MTA's signer (#18).
    "requester": CONTACT_PERSONAL,
    "mta_acceptance": ("signer",),
}


# Tables of the project's apps that the row trigger does not watch, each with the reason.
# tests/test_invariants.py walks every table of the project's models: each one is in
# ROW_AUDITED_TABLES or here, so a new table needs a decision before it ships.
NOT_ROW_AUDITED: dict[str, str] = {
    "audit_auditevent": "the service events themselves: append-only, never changed",
    "audit_rowchange": "the row changes themselves: written only by the row trigger",
    "users_user_groups": (
        "Django groups grant nothing here: rights come from lab roles (ADR 0006), and the "
        "user admin offers no groups"
    ),
    "users_user_user_permissions": (
        "per-user Django permissions are not used and the user admin offers none"
    ),
    "users_loginfailures": (
        "login failure counters: HMAC keys, windows and counts, no record of anyone. A row "
        "change per failed login would flood the trail. Staff clears are service events"
    ),
    "deposits_contact": (
        "names, e-mail and postal addresses of people (ADR 0008, D11): kept out of every "
        "append-only row, so an erasure needs no audit row changed. Its services record "
        "events with the fields as changed"
    ),
}
