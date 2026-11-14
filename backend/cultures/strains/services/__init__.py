"""Every write on strains: accession, reclassification, risk group and restrictions.

Each service runs in audited_atomic() and records one event that names the
strain (Change(strain_id=...), ADR 0008, D13). Lock order, as everywhere: the
lab row first (labs.locks.lock_lab), then the strain's rows. Under the lab
lock each service
- re-reads the actor's role in the lab, so a curator demoted after the request
  built its access object is refused (the members services do the same);
- checks the lab's permits for a cz_vrat or quarantine_pest restriction
  (biosafety.policy), so a permit ended at the same moment is seen;
- takes the next accession number from the lab's counter row, so two
  accessions never get the same number, also when they run at once.
A refusal raises before anything is written, or rolls back what was, so it
changes nothing and records nothing.

Rules (ADR 0009): a risk group 4 agent is refused, at accession and as a
change, and so is a group above the cap of a box holding the strain's vials.
A changed risk group, a reclassification, an added or an ended restriction
each need a reason (audit.registry, reason_required). A restriction ends in two
steps by two people (#105): someone who manages strains proposes it, a manager
other than the proposer confirms it.

A risk group changes only with a stated basis, and a lower group takes the same
two steps (#174): one person proposes it, a manager other than the proposer
confirms it, and only then does any rule read the lower group. A raise is one
person's and goes one step at a time."""

from ._shared import (
    ACCESSION_REASON,
    MAX_RESTRICTIONS,
    RISK_GROUP_REFUSED,
    STRAIN,
    DualUseEntryUnknown,
    InvalidStrain,
    RestrictionHeldByDualUse,
    RestrictionInput,
    RestrictionRequiredByEntry,
    RiskGroupEntryMismatch,
    RiskGroupRefused,
    StrainDeaccessioned,
    StrainPending,
    check_partial_date,
    check_restriction,
    normalised,
)
from .accession import (
    AccessionTaken,
    NewStrain,
    strain_create,
    strain_reclassify,
    strain_set_growth,
)
from .deaccession import (
    ConfirmOwnDeaccession,
    Deaccession,
    DeaccessionInOneStep,
    DeaccessionNeedsSecondPerson,
    DeaccessionNotProposed,
    DeaccessionProposalChanged,
    DeaccessionProposalOutdated,
    DeaccessionProposed,
    strain_deaccession,
    strain_deaccession_confirm,
    strain_deaccession_propose,
    strain_deaccession_withdraw,
)
from .restrictions import (
    ConfirmOwnEndProposal,
    EndNotProposed,
    EndProposalChanged,
    EndProposed,
    RestrictionEnded,
    strain_restriction_add,
    strain_restriction_end_confirm,
    strain_restriction_end_propose,
    strain_restriction_end_withdraw,
)
from .risk_group import (
    RISK_GROUP_FIELDS,
    ConfirmOwnRiskGroup,
    RiskGroupAboveBoxCap,
    RiskGroupNeedsSecondPerson,
    RiskGroupNotLower,
    RiskGroupNotProposed,
    RiskGroupProposalChanged,
    RiskGroupProposalOutdated,
    RiskGroupProposed,
    RiskGroupStepTooBig,
    strain_risk_group_lower_confirm,
    strain_risk_group_lower_propose,
    strain_risk_group_lower_withdraw,
    strain_set_risk_group,
)

__all__ = [
    "ACCESSION_REASON",
    "MAX_RESTRICTIONS",
    "RISK_GROUP_FIELDS",
    "RISK_GROUP_REFUSED",
    "STRAIN",
    "AccessionTaken",
    "ConfirmOwnDeaccession",
    "ConfirmOwnEndProposal",
    "ConfirmOwnRiskGroup",
    "Deaccession",
    "DeaccessionInOneStep",
    "DeaccessionNeedsSecondPerson",
    "DeaccessionNotProposed",
    "DeaccessionProposalChanged",
    "DeaccessionProposalOutdated",
    "DeaccessionProposed",
    "DualUseEntryUnknown",
    "EndNotProposed",
    "EndProposalChanged",
    "EndProposed",
    "InvalidStrain",
    "NewStrain",
    "RestrictionEnded",
    "RestrictionHeldByDualUse",
    "RestrictionInput",
    "RestrictionRequiredByEntry",
    "RiskGroupAboveBoxCap",
    "RiskGroupEntryMismatch",
    "RiskGroupNeedsSecondPerson",
    "RiskGroupNotLower",
    "RiskGroupNotProposed",
    "RiskGroupProposalChanged",
    "RiskGroupProposalOutdated",
    "RiskGroupProposed",
    "RiskGroupRefused",
    "RiskGroupStepTooBig",
    "StrainDeaccessioned",
    "StrainPending",
    "check_partial_date",
    "check_restriction",
    "normalised",
    "strain_create",
    "strain_deaccession",
    "strain_deaccession_confirm",
    "strain_deaccession_propose",
    "strain_deaccession_withdraw",
    "strain_reclassify",
    "strain_restriction_add",
    "strain_restriction_end_confirm",
    "strain_restriction_end_propose",
    "strain_restriction_end_withdraw",
    "strain_risk_group_lower_confirm",
    "strain_risk_group_lower_propose",
    "strain_risk_group_lower_withdraw",
    "strain_set_growth",
    "strain_set_risk_group",
]
