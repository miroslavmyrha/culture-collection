"""Catalogue import (#70): a CSV file of an existing catalogue, checked row by row, then applied
all or nothing. Each row is a deposit received, checked and accepted through the services."""

import csv
import io
from collections.abc import Iterator
from datetime import timedelta

import pytest
from django.utils import timezone

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.audit.reconcile import reconcile
from cultures.core.exceptions import DomainError
from cultures.core.testing import assert_problem, logged_in
from cultures.deposits import catalogue
from cultures.deposits.catalogue import (
    COLUMNS,
    CatalogueChanged,
    CatalogueHasErrors,
    CatalogueRefused,
    catalogue_check,
    catalogue_import,
    read_rows,
    sha256_of,
)
from cultures.deposits.models import (
    AbsScope,
    Condition,
    Decision,
    Deposit,
    Depositor,
    DepositStatus,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage.models import Passage
from cultures.search.selectors import search
from cultures.strains import services as strains
from cultures.strains.models import Strain, StrainCounter
from cultures.strains.selectors import matching
from cultures.strains.tests.conftest import new_strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

pytestmark = pytest.mark.django_db
REASON = "The former paper catalogue, moved in before the pilot."


def row(**changes: str) -> dict[str, str]:
    values = dict.fromkeys(COLUMNS, "")
    values.update(
        name_as_received="Testella exempli K1",
        depositor="Jana Vzorová",
        received_on="2019-05-14",
        taxon="Testella exempli",
        identified_on="2019-06-01",
        identification_method="16S rRNA gene sequence",
        risk_group="1",
        risk_group_basis="The lab's own assessment of this invented isolate.",
    )
    values.update(changes)
    return values


def csv_of(*rows: dict[str, str], header: tuple[str, ...] = COLUMNS) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


@pytest.fixture
def as_manager(manager: User) -> Iterator[AuditContext]:
    with audit_context(channel=Channel.API, actor=manager, request_id="req-import") as context:
        yield context


def check(manager: User, lab: Lab, content: bytes) -> catalogue.Checked:
    return catalogue_check(access=access_for(manager), lab=lab, content=content)


def apply(manager: User, lab: Lab, content: bytes) -> list[Strain]:
    return catalogue_import(
        access=access_for(manager),
        lab=lab,
        content=content,
        sha256=sha256_of(content),
        reason=REASON,
    )


@pytest.mark.usefixtures("as_manager")
class TestImport:
    @pytest.mark.rule("R-KIND-12")
    def test_a_clean_file_imports_every_row_as_an_accepted_deposit_with_passage_0(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        content = csv_of(row(), row(name_as_received="Testella exempli K2", note="Date estimated."))
        assert check(manager, lab, content).errors == []
        created = apply(manager, lab, content)
        assert [s.accession_number for s in created] == ["MYC 1", "MYC 2"]
        for strain in created:
            deposit = Deposit.objects.get(strain=strain)
            assert (deposit.status, deposit.depositor, deposit.condition) == (
                DepositStatus.ACCEPTED,
                depositor,
                Condition.OTHER,
            )
            assert Passage.objects.get(strain=strain, number=0).source_deposit == deposit
            terms = deposit.terms.get(is_active=True)
            assert terms.abs_scope == AbsScope.UNKNOWN
            assert {u.decision for u in terms.uses.all()} == {Decision.ON_REQUEST}
        assert Deposit.objects.get(strain=created[1]).condition_note == (
            "Imported from the former catalogue. Date estimated."
        )

    @pytest.mark.rule("R-KIND-12")
    def test_the_import_is_one_event_with_the_hash_the_rows_and_the_reason(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        content = csv_of(row())
        apply(manager, lab, content)
        event = AuditEvent.objects.get(event_type="catalogue_imported")
        assert (event.reason, event.lab_id) == (REASON, lab.pk)
        assert event.changes["file_sha256"] == [None, sha256_of(content)]
        assert event.changes["rows"] == [None, 1]

    def test_the_check_writes_nothing(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        before = (Strain.objects.count(), Deposit.objects.count(), AuditEvent.objects.count())
        assert check(manager, lab, csv_of(row(), row())).errors == []
        assert (
            Strain.objects.count(),
            Deposit.objects.count(),
            AuditEvent.objects.count(),
        ) == before

    @pytest.mark.rule("R-KIND-12")
    def test_one_bad_row_imports_none(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        content = csv_of(row(), row(taxon="Nosuchia fakeus"), row())
        checked = check(manager, lab, content)
        assert [(e.row, e.column) for e in checked.errors] == [(3, "taxon")]
        with pytest.raises(CatalogueHasErrors) as refused:
            apply(manager, lab, content)
        assert [(e.row, e.column) for e in refused.value.errors] == [(3, "taxon")]
        assert not Strain.objects.filter(lab=lab).exists()
        assert not AuditEvent.objects.filter(event_type="catalogue_imported").exists()

    @pytest.mark.parametrize(
        ("changes", "column"),
        [
            ({"depositor": "Nobody Known"}, "depositor"),
            ({"taxon": "Nosuchia fakeus"}, "taxon"),
            ({"restrictions": "dual_use|1C999.x|(EU) 2025/2003"}, "restrictions"),
            ({"risk_group_entry": "no such entry"}, "risk_group_entry"),
            ({"mta": "NONE"}, "mta"),
            ({"received_on": ""}, "received_on"),
            ({"identified_on": "14. 5. 2019"}, "identified_on"),
            ({"identification_method": ""}, "identification_method"),
            ({"risk_group": "4"}, "risk_group"),
            ({"uses": "teaching=maybe"}, "uses"),
        ],
    )
    @pytest.mark.rule("R-KIND-12")
    @pytest.mark.usefixtures("depositor", "exempli")
    def test_a_row_the_lab_could_not_enter_by_hand_is_an_error_on_its_column(
        self, manager: User, lab: Lab, changes: dict[str, str], column: str
    ) -> None:
        errors = check(manager, lab, csv_of(row(**changes))).errors
        assert len(errors) == 1
        assert (errors[0].row, errors[0].column) == (2, column)

    @pytest.mark.rule("R-KIND-12")
    @pytest.mark.usefixtures("depositor", "exempli")
    def test_a_restriction_names_an_entry_of_its_list_not_words_of_ones_own(
        self, manager: User, lab: Lab
    ) -> None:
        # By hand a VRAT may be named in the annex's words; a catalogue must name the entry, so
        # what entered unchecked by a person is not taken on trust (#70).
        errors = check(manager, lab, csv_of(row(restrictions="cz_vrat|Příloha 1, bod 2"))).errors
        assert [(e.row, e.column) for e in errors] == [(2, "restrictions")]
        assert errors[0].message == "No entry of the cz_vrat list has the code Příloha 1, bod 2."

    def test_a_number_of_the_lab_is_kept_and_the_counter_moves_past_it(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon, curator: User
    ) -> None:
        created = apply(manager, lab, csv_of(row(accession_number="myc 40"), row()))
        assert [(s.accession_number, s.former_number) for s in created] == [
            ("MYC 40", ""),
            ("MYC 41", ""),
        ]
        assert StrainCounter.objects.get(lab=lab).last_seq == 41
        by_hand = strains.strain_create(
            access=access_for(curator), lab=lab, data=new_strain(exempli)
        )
        assert by_hand.accession_number == "MYC 42"

    def test_another_form_is_a_former_number_and_the_strain_takes_the_next(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        (strain,) = apply(manager, lab, csv_of(row(accession_number="CCM 4517")))
        assert (strain.accession_number, strain.former_number) == ("MYC 1", "CCM 4517")

    def test_a_former_number_is_found_and_shown(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        (strain,) = apply(manager, lab, csv_of(row(accession_number="CCM 4517")))
        assert list(matching(Strain.objects.filter(lab=lab), "4517")) == [strain]
        (group,) = search(access=access_for(manager), text="CCM 4517")
        assert [h.public_id for h in group.hits] == [strain.public_id]
        detail = logged_in(manager).get(f"/api/v1/labs/{lab.public_id}/strains/{strain.public_id}/")
        assert detail.json()["former_number"] == "CCM 4517"

    def test_a_number_twice_in_the_file_or_taken_in_the_lab_is_an_error(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        apply(manager, lab, csv_of(row(accession_number="MYC 7")))
        errors = check(
            manager,
            lab,
            csv_of(
                row(accession_number="MYC 9"),
                row(accession_number="MYC 9"),
                row(accession_number="MYC 7"),
            ),
        ).errors
        assert [(e.row, e.column) for e in errors] == [
            (3, "accession_number"),
            (4, "accession_number"),
        ]

    @pytest.mark.rule("R-KIND-12")
    def test_a_file_changed_after_the_check_is_refused(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        checked = check(manager, lab, csv_of(row()))
        with pytest.raises(CatalogueChanged):
            catalogue_import(
                access=access_for(manager),
                lab=lab,
                content=csv_of(row(name_as_received="Another")),
                sha256=checked.sha256,
                reason=REASON,
            )
        assert not Strain.objects.filter(lab=lab).exists()

    def test_a_reason_is_required(self, manager: User, lab: Lab, depositor: Depositor) -> None:
        content = csv_of(row())
        with pytest.raises(DomainError) as refused:
            catalogue_import(
                access=access_for(manager),
                lab=lab,
                content=content,
                sha256=sha256_of(content),
                reason=" ",
            )
        assert refused.value.code == "reason_required"

    @pytest.mark.rule("R-KIND-12")
    def test_a_regulated_strain_passes_the_gates_of_a_strain_by_hand(
        self, manager: User, lab: Lab, depositor: Depositor, mockia: Taxon
    ) -> None:
        (strain,) = apply(
            manager,
            lab,
            csv_of(row(taxon="Mockia vulgaris", restrictions="dual_use|1C351.c|(EU) 2025/2003")),
        )
        assert list(strain.restrictions.values_list("kind", "reference")) == [
            ("dual_use", "1C351.c")
        ]

    @pytest.mark.rule("R-KIND-12")
    def test_every_row_is_explained_to_the_reconcile(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        # One test is one transaction: the fixtures' rows (a lab made without an actor) share its
        # time, so only the tables the import writes are read.
        since = timezone.now() - timedelta(minutes=1)
        apply(manager, lab, csv_of(row(), row(accession_number="CCM 4517")))
        written = ("deposits.", "strains.", "lineage.")
        findings = [f for f in reconcile(since) if f.table_label.startswith(written)]
        # reconcile names only transactions with something to say: a clean import, none.
        assert [f for f in findings if f.alarm] == []


@pytest.mark.rule("R-KIND-12")
@pytest.mark.usefixtures("as_curator")
def test_a_curator_does_not_import(curator: User, lab: Lab, depositor: Depositor) -> None:
    with pytest.raises(DomainError) as refused:
        catalogue_check(access=access_for(curator), lab=lab, content=csv_of(row()))
    assert refused.value.status_code == 403


class TestReading:
    def test_the_template_reads_back_as_one_row(self) -> None:
        rows = read_rows(catalogue.template().encode())
        assert len(rows) == 1
        assert rows[0].values["accession_number"] == "MYC 12"

    def test_a_byte_order_mark_is_fine(self) -> None:
        assert len(read_rows(b"\xef\xbb\xbf" + csv_of(row()))) == 1

    @pytest.mark.parametrize(
        "content",
        [
            b"name_as_received\nx\n",
            csv_of(row(), header=(*COLUMNS, "extra")),
            csv_of(),
            csv_of(row()).replace("Vzorová".encode(), "Vzorová".encode("cp1250")),
        ],
        ids=["wrong header", "unknown column", "no rows", "not utf-8"],
    )
    def test_a_file_not_in_the_template_is_refused(self, content: bytes) -> None:
        with pytest.raises(CatalogueRefused):
            read_rows(content)

    def test_a_blank_line_is_no_row(self) -> None:
        content = csv_of(row()) + b",,,,,,,,,,,,,,,,,,,,,,\n" + csv_of(row()).split(b"\n", 1)[1]
        assert [r.line for r in read_rows(content)] == [2, 4]

    def test_too_large_a_file_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(catalogue, "MAX_BYTES", 10)
        with pytest.raises(CatalogueRefused, match="larger than"):
            read_rows(csv_of(row()))

    def test_too_many_rows_are_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(catalogue, "MAX_ROWS", 2)
        with pytest.raises(CatalogueRefused):
            read_rows(csv_of(row(), row(), row()))


CHECK_URL = "/api/v1/labs/{lab}/deposits/catalogue-check/"
IMPORT_URL = "/api/v1/labs/{lab}/deposits/catalogue-import/"
TEMPLATE_URL = "/api/v1/labs/{lab}/deposits/catalogue-template/"


def upload(content: bytes) -> io.BytesIO:
    file = io.BytesIO(content)
    file.name = "catalogue.csv"
    return file


class TestApi:
    def test_a_manager_downloads_the_template(self, manager: User, lab: Lab) -> None:
        response = logged_in(manager).get(TEMPLATE_URL.format(lab=lab.public_id))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert response.content.decode().splitlines()[0] == ",".join(COLUMNS)

    def test_a_manager_checks_then_imports(
        self, manager: User, lab: Lab, depositor: Depositor, exempli: Taxon
    ) -> None:
        client = logged_in(manager)
        bad = csv_of(row(taxon="Nosuchia fakeus"))
        checked = client.post(CHECK_URL.format(lab=lab.public_id), {"file": upload(bad)}).json()
        assert checked["row_errors"] == [
            {"row": 2, "column": "taxon", "message": "No taxon has this name here."}
        ]
        good = csv_of(row())
        sha = client.post(CHECK_URL.format(lab=lab.public_id), {"file": upload(good)}).json()[
            "sha256"
        ]
        response = client.post(
            IMPORT_URL.format(lab=lab.public_id),
            {"file": upload(good), "sha256": sha, "reason": REASON},
        )
        assert response.status_code == 201
        assert [s["accession_number"] for s in response.json()["strains"]] == ["MYC 1"]

    def test_a_changed_file_is_a_problem(
        self, manager: User, lab: Lab, depositor: Depositor
    ) -> None:
        response = logged_in(manager).post(
            IMPORT_URL.format(lab=lab.public_id),
            {"file": upload(csv_of(row())), "sha256": "0" * 64, "reason": REASON},
        )
        assert_problem(response, 422, "catalogue_changed")

    @pytest.mark.parametrize("url", [CHECK_URL, IMPORT_URL, TEMPLATE_URL])
    @pytest.mark.parametrize(
        ("who", "status"),
        [(None, 401), ("outsider", 404), ("viewer", 403), ("technician", 403), ("curator", 403)],
    )
    @pytest.mark.usefixtures("depositor")
    def test_no_one_but_a_manager_of_the_lab_reaches_it(
        self, request: pytest.FixtureRequest, who: str | None, status: int, url: str, lab: Lab
    ) -> None:
        user = request.getfixturevalue(who) if who else None
        client = logged_in(user)
        target = url.format(lab=lab.public_id)
        before = (Strain.objects.count(), AuditEvent.objects.count())
        if url == TEMPLATE_URL:
            response = client.get(target)
        else:
            content = csv_of(row())
            body = {"file": upload(content), "sha256": sha256_of(content), "reason": REASON}
            response = client.post(target, body)
        assert response.status_code == status
        assert (Strain.objects.count(), AuditEvent.objects.count()) == before
