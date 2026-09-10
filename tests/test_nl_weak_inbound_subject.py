from types import SimpleNamespace

from services.incoming_lead_resolve import inbound_thread_binds_offer
from services.subject_offer import (
    inbound_subject_is_availability_only,
    inbound_subject_is_weak_for_bind,
    offer_title_from_inbound_subject,
)


def test_dutch_still_available_is_weak():
    subj = "Re: Nog steeds beschikbaar?"
    assert inbound_subject_is_availability_only(subj)
    assert inbound_subject_is_weak_for_bind(subj)
    assert offer_title_from_inbound_subject(subj) == ""


def test_english_still_available_is_weak():
    assert inbound_subject_is_weak_for_bind("Re: Still available?")
    assert inbound_subject_is_weak_for_bind("Is this still available?")
    assert offer_title_from_inbound_subject("Re: Still available?") == ""


def test_german_noch_verfuegbar_still_weak():
    assert inbound_subject_is_weak_for_bind("Re: Noch verfügbar?")
    assert offer_title_from_inbound_subject("Aw: Noch zu haben") == ""


def test_weak_nl_subject_allows_email_bind():
    off = SimpleNamespace(id=1, title="Gazelle Orange C8", raw_json=None)
    assert inbound_thread_binds_offer(
        "Re: Nog steeds beschikbaar?",
        "Ja, het is nog beschikbaar.\n\nVerzonden vanuit Outlook voor iOS",
        off,
    )


def test_real_product_subject_still_not_weak():
    subj = "Re: Gazelle Orange C8 HMB"
    assert not inbound_subject_is_weak_for_bind(subj)
    assert "Gazelle" in offer_title_from_inbound_subject(subj)
