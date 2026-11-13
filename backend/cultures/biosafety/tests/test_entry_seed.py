"""What the seeds read out of the official list data files by entry code (#211).

The tests read the committed data files as they are: the group, the pointer and the basis of a
seeded strain must come out of them and nowhere else.
"""

import pytest

from cultures.biosafety import entry_seed
from cultures.biosafety.entry_seed import SeedEntryError


@pytest.mark.rule("R-SEED-01")
def test_a_listed_agent_takes_the_group_its_annex_7_entry_states_and_points_at_it() -> None:
    made = entry_seed.listed(["1.56"])
    assert (made.taxon, made.risk_group, made.risk_group_entry) == ("Clostridium tetani", 2, "1.56")
    assert "entry 1.56" in made.basis
    assert "states risk group 2" in made.basis


@pytest.mark.rule("R-SEED-01")
def test_the_restrictions_come_from_the_lists_other_than_annex_7() -> None:
    made = entry_seed.listed(["1.31", "annex-1 I.II 2", "1C351.c.2"])
    assert made.risk_group == 3
    assert [(r.kind, r.reference, r.act) for r in made.restrictions] == [
        ("cz_vrat", "annex-1 I.II 2", ""),
        ("dual_use", "1C351.c.2", "(EU) 2025/2003"),
    ]


def test_codes_that_name_two_taxa_are_refused() -> None:
    with pytest.raises(SeedEntryError, match="not one taxon"):
        entry_seed.listed(["1.56", "annex-2 I.II 2"])


def test_a_code_the_data_files_do_not_hold_is_refused() -> None:
    with pytest.raises(SeedEntryError, match="no entry"):
        entry_seed.listed(["99.99"])


def test_an_entry_of_a_whole_genus_names_no_taxon_to_seed() -> None:
    with pytest.raises(SeedEntryError, match="no one taxon"):
        entry_seed.listed(["1.182"])


def test_a_restriction_alone_gives_no_group() -> None:
    made = entry_seed.listed(["annex-2 I.II 3"])
    assert (made.risk_group, made.risk_group_entry, made.basis) == (None, None, "")


@pytest.mark.rule("R-RISK-10")
def test_a_standard_organism_is_group_1_with_no_pointer_and_says_annex_7_does_not_list_it() -> None:
    made = entry_seed.standard("pseudomonas-putida-kt2440")
    assert (made.risk_group, made.risk_group_entry) == (1, None)
    assert "does not list Pseudomonas putida KT2440" in made.basis
    assert "collection's own assessment" in made.basis


@pytest.mark.rule("R-RISK-10")
def test_escherichia_coli_k12_quotes_the_entry_that_excepts_non_pathogenic_strains() -> None:
    made = entry_seed.standard("escherichia-coli-k12")
    assert made.risk_group_entry is None
    assert "entry 1.73" in made.basis
    assert "non-pathogenic" in made.basis


@pytest.mark.rule("R-RISK-10")
def test_the_standard_organisms_are_four_and_none_is_listed_as_group_1() -> None:
    assert set(entry_seed.STANDARD) == {
        "escherichia-coli-k12",
        "bacillus-subtilis-168",
        "lactococcus-lactis",
        "pseudomonas-putida-kt2440",
    }
    for key in entry_seed.STANDARD:
        assert entry_seed.standard(key).risk_group == 1


def test_an_unknown_standard_organism_is_refused() -> None:
    with pytest.raises(SeedEntryError, match="not a standard organism"):
        entry_seed.standard("streptomyces-griseus")


@pytest.mark.rule("R-RISK-10")
def test_a_species_under_a_genus_entry_keeps_the_entrys_group_and_says_why() -> None:
    made = entry_seed.species_under_genus("Staphylococcus epidermidis")
    assert (made.risk_group, made.risk_group_entry) == (2, "1.182")
    assert "known human pathogens" in made.basis
    assert "until a person decides" in made.basis


def test_a_species_an_entry_names_is_no_case_for_the_genus_entry() -> None:
    with pytest.raises(SeedEntryError, match="named by an entry of its own"):
        entry_seed.species_under_genus("Staphylococcus aureus")


def test_a_genus_the_lists_do_not_name_has_no_entry_to_stand_under() -> None:
    with pytest.raises(SeedEntryError, match="not one"):
        entry_seed.species_under_genus("Bacillus subtilis")


def test_a_taxon_matches_the_entries_the_view_matches() -> None:
    found = {row.code for row in entry_seed.entries_matching("Staphylococcus epidermidis")}
    assert found == {"1.182"}


@pytest.mark.rule("R-SEED-01")
def test_the_act_comes_from_the_celex_number_and_a_bad_number_is_refused() -> None:
    assert entry_seed._eu_act("32025R2003") == "(EU) 2025/2003"
    with pytest.raises(SeedEntryError, match="no CELEX number"):
        entry_seed._eu_act("2025/2003")


@pytest.mark.rule("R-SEED-01")
def test_a_classification_row_says_entries_a_standard_organism_or_a_genus() -> None:
    assert entry_seed.classify({"entries": ["1.56"]}, "Clostridium tetani").risk_group == 2
    standard = entry_seed.classify({"standard": "bacillus-subtilis-168"}, "Bacillus subtilis")
    assert (standard.risk_group, standard.risk_group_entry) == (1, None)
    under = entry_seed.classify({"under_genus": True}, "Staphylococcus epidermidis")
    assert under.risk_group_entry == "1.182"


@pytest.mark.rule("R-SEED-01")
def test_a_classification_row_of_another_taxon_or_of_no_kind_is_refused() -> None:
    with pytest.raises(SeedEntryError, match="the strain is Clostridium perfringens"):
        entry_seed.classify({"entries": ["1.56"]}, "Clostridium perfringens")
    with pytest.raises(SeedEntryError, match="names entries, a standard organism or a genus"):
        entry_seed.classify({"group": 1}, "Bacillus subtilis")
