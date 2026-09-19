from services.gag_domains import (
    domain_mode_menu_options,
    gag_api_domain_for_mode,
    profile_domain_label,
)


def test_gag_domains_are_exact_numbers_one_through_eight():
    options = domain_mode_menu_options()

    assert [code for code, _ in options] == [str(n) for n in range(1, 9)]
    for n in range(1, 9):
        assert gag_api_domain_for_mode(str(n)) == n
        assert profile_domain_label(str(n)) == f"Домен {n}"


def test_legacy_team_domain_migrates_to_domain_one():
    assert gag_api_domain_for_mode("team") == 1
