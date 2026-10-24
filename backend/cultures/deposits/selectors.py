"""Reads of depositors, MTA templates and deposits. Every one takes the access object.

Depositors and deposits show personal contacts, so they need deposits.view
(curators and managers, ADR 0008, 2026-10-19). MTA templates are read with the
same permission. A strain's terms of use name no person: every role that sees the
strain reads them (deposits.view_terms, #19), without the deposit.
"""

from django.db.models import Prefetch, Q, QuerySet

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.strains.models import Strain

from .models import Deposit, Depositor, DepositTerms, MtaTemplate, TermsUse


def depositor_list(*, access: Access, lab: Lab) -> QuerySet[Depositor]:
    """By name; erased contacts last (their name is empty)."""
    return (
        Depositor.objects.for_access(access, Perm.VIEW_DEPOSITS)
        .filter(lab=lab)
        .select_related("contact")
        .order_by("contact__erased_at", "contact__name", "institution", "pk")
    )


def depositor_matching(depositors: QuerySet[Depositor], text: str) -> QuerySet[Depositor]:
    text = " ".join(text.split())
    if not text:
        return depositors
    return depositors.filter(Q(contact__name__icontains=text) | Q(institution__icontains=text))


def mta_template_list(*, access: Access, lab: Lab) -> QuerySet[MtaTemplate]:
    """By code, the newest version of each first."""
    return (
        MtaTemplate.objects.for_access(access, Perm.VIEW_DEPOSITS)
        .filter(lab=lab)
        .order_by("code", "-version", "pk")
    )


def _terms() -> QuerySet[DepositTerms]:
    return DepositTerms.objects.select_related("mta").prefetch_related(
        Prefetch("uses", queryset=TermsUse.objects.order_by("pk"))
    )


def deposit_list(*, access: Access, lab: Lab) -> QuerySet[Deposit]:
    """Newest receipt first."""
    return (
        Deposit.objects.for_access(access, Perm.VIEW_DEPOSITS)
        .filter(lab=lab)
        .select_related("depositor__contact", "strain")
        .order_by("-received_on", "-created_at", "-pk")
    )


def deposit_detail(*, access: Access, lab: Lab) -> QuerySet[Deposit]:
    """The same rows with every terms version, the active one first."""
    return deposit_list(access=access, lab=lab).prefetch_related(
        Prefetch("terms", queryset=_terms().order_by("-version"), to_attr="terms_history")
    )


def deposit_matching(deposits: QuerySet[Deposit], text: str) -> QuerySet[Deposit]:
    """The name as received, the depositor's name or institution, or the strain's number."""
    text = " ".join(text.split())
    if not text:
        return deposits
    return deposits.filter(
        Q(name_as_received__icontains=text)
        | Q(depositor__contact__name__icontains=text)
        | Q(depositor__institution__icontains=text)
        | Q(strain__accession_number__icontains=text)
    )


def strain_terms(*, access: Access, strain: Strain) -> QuerySet[DepositTerms]:
    """Every terms version of the deposit the strain was accepted from, newest first, with its
    uses and its MTA. At most one is active. A strain from no deposit has none."""
    return (
        DepositTerms.objects.for_access(access, Perm.VIEW_TERMS)
        .filter(lab_id=strain.lab_id, deposit__strain=strain)
        .select_related("mta", "deposit")
        .prefetch_related(Prefetch("uses", queryset=TermsUse.objects.order_by("pk")))
        .order_by("-version", "pk")
    )
