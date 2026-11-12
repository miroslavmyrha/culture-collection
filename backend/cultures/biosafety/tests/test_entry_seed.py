"""What the seeds read out of the official list data files by entry code (#211).

The tests read the committed data files as they are: the group, the pointer and the basis of a
seeded strain must come out of them and nowhere else.
"""

import pytest

from cultures.biosafety import entry_seed
from cultures.biosafety.entry_seed import SeedEntryError


def test_a_listed_agent_takes_the_group_its_annex_7_entry_states_and_points_at_it() -> None:
    made = entry_seed.listed(["1.56"])
    assert (made.taxon, made.risk_group, made.risk_group_entry) == ("Clostridium tetani", 2, "1.56")
    assert "entry 1.56" in made.basis
    assert "states risk group 2" in made.basis


def test_the_restrictions_come_from_the_lists_other_than_annex_7() -> None:
    made = entry_seed.listed(["1.31", "annex-1 I.II 2", "1C351.c.2"])
    assert made.risk_group == 3
    assert [(r.kind, r.reference, r.act) for r in made.restrictions] == [
        ("cz_vrat", "annex-1 I.II 2", "474/2002 Sb."),
        ("dual_use", "1C351.c.2", "2021/821"),
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


def test_a_standard_organism_is_group_1_with_no_pointer_and_says_annex_7_does_not_list_it() -> None:
    made = entry_seed.standard("pseudomonas-putida-kt2440")
    assert (made.risk_group, made.risk_group_entry) == (1, None)
    assert "does not list Pseudomonas putida KT2440" in made.basis
    assert "collection's own assessment" in made.basis


def test_escherichia_coli_k12_quotes_the_entry_that_excepts_non_pathogenic_strains() -> None:
    made = entry_seed.standard("escherichia-coli-k12")
    assert made.risk_group_entry is None
    assert "entry 1.73" in made.basis
    assert "non-pathogenic" in made.basis


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
