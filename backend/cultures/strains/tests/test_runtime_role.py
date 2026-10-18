"""As the runtime role (ADR 0005): the app's strain writes work, deletes do not, and the
guard triggers hold for it as for everybody. Grants come from audit.roles.APP_ROLE_GRANTS;
test_roles.py compares every table with it, this proves what the strain tables need."""

import pytest
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.audit.tests.conftest import TEST_ROLES, refused
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.strains import services
from cultures.strains.models import Strain, StrainCounter
from cultures.taxonomy.models import Taxon

from .conftest import GMO, new_strain

pytestmark = pytest.mark.django_db


def test_the_runtime_role_accessions_and_changes_a_strain(
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    subtilis: Taxon,
    runtime_role: CursorWrapper,
) -> None:
    runtime_role.execute("SELECT current_user")
    assert runtime_role.fetchone() == (TEST_ROLES.runtime,)
    strain = services.strain_create(
        access=curator_access, lab=lab, data=new_strain(subtilis, restrictions=[GMO])
    )
    services.strain_set_risk_group(
        access=curator_access, strain=strain, risk_group=2, reason="reassessed"
    )
    assert Strain.objects.get(pk=strain.pk).risk_group == 2
    assert AuditEvent.objects.filter(strain_id=strain.public_id).count() == 2
    # The trigger wrote the row changes as the audit owner, though the runtime role may not.
    labels = set(RowChange.objects.values_list("table_label", flat=True))
    assert {
        "strains.strain",
        "strains.straincounter",
        "strains.strainidentification",
        "strains.strainrestriction",
    } <= labels


@pytest.mark.parametrize(
    "table",
    [
        "strains_strain",
        "strains_straincounter",
        "strains_strainidentification",
        "strains_strainrestriction",
    ],
)
def test_the_runtime_role_deletes_no_strain_history(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    subtilis: Taxon,
    runtime_role: CursorWrapper,
    table: str,
) -> None:
    services.strain_create(
        access=curator_access, lab=lab, data=new_strain(subtilis, restrictions=[GMO])
    )
    delete = f"DELETE FROM {table}"  # noqa: S608 (a table name from the list above)
    refused(runtime_role, delete, f"permission denied for table {table}")
    refused(runtime_role, f"TRUNCATE {table}", f"permission denied for table {table}")


def test_the_guards_hold_for_the_runtime_role(
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    subtilis: Taxon,
    runtime_role: CursorWrapper,
) -> None:
    services.strain_create(
        access=curator_access, lab=lab, data=new_strain(subtilis)
    )  # the only one
    refused(
        runtime_role,
        "UPDATE strains_strain SET accession_number = 'MYC 99'",
        "an accession number never changes",
    )
    refused(
        runtime_role,
        "UPDATE strains_strain SET name_as_received = 'other'",
        "the name as received never changes",
    )
    assert StrainCounter.objects.get(lab=lab).last_seq == 1
