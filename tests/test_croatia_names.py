# -*- coding: utf-8 -*-
from services.country_scope import CROATIA_VALIDATION_DOMAINS, default_validation_domains_for
from services.seller_name import seller_name_eligible_for_validation
from services.validemail_validator import _make_local_part_variants


def test_croatia_validation_domains():
    domains = default_validation_domains_for("hr")
    assert domains == CROATIA_VALIDATION_DOMAINS
    assert domains[0] == "net.hr"
    assert "gmail.com" in domains


def test_croatia_full_name_gets_dot():
    assert seller_name_eligible_for_validation("Marko Horvat", country="hr")
    vs = _make_local_part_variants(
        "Marko Horvat", require_first_and_last=False, country="hr"
    )
    assert "marko.horvat" in vs
    assert "markohorvat" in vs

    assert seller_name_eligible_for_validation("Ivan Horvat", country="hr")
    vs_ivan = _make_local_part_variants(
        "Ivan Horvat", require_first_and_last=False, country="hr"
    )
    assert "ivan.horvat" in vs_ivan


def test_croatia_short_single_name_rejected():
    assert not seller_name_eligible_for_validation("Ana", country="hr")


def test_croatia_nick_with_digits_and_underscore():
    assert seller_name_eligible_for_validation("Anaama_08", country="hr")
    vs = _make_local_part_variants(
        "Anaama_08", require_first_and_last=False, country="hr"
    )
    assert "anaama_08" in vs

    assert seller_name_eligible_for_validation("Ana_08", country="hr")
    vs2 = _make_local_part_variants(
        "Ana_08", require_first_and_last=False, country="hr"
    )
    assert "ana_08" in vs2

    assert not seller_name_eligible_for_validation("Ana_0", country="hr")


def test_croatia_placeholder_skipped():
    assert not seller_name_eligible_for_validation("Privatna osoba", country="hr")


def test_croatia_diacritics_first_last():
    assert seller_name_eligible_for_validation("Marko Kovačić", country="hr")
    vs = _make_local_part_variants(
        "Marko Kovačić", require_first_and_last=False, country="hr"
    )
    assert "marko.kovacic" in vs
