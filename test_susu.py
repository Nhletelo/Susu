from decimal import Decimal

import pytest

from susu import SusuError, SusuGroup


def test_amounts_must_be_positive_and_exact_to_cent():
    for amount in ("0", "-1.00", "50.005", "not-a-number"):
        with pytest.raises(SusuError):
            SusuGroup(amount)


def test_members_are_trimmed_and_duplicates_rejected():
    group = SusuGroup("10.00")
    group.add_member(" Ama ")

    assert group.members == ["Ama"]
    with pytest.raises(SusuError):
        group.add_member("Ama")
    with pytest.raises(SusuError):
        group.add_member("   ")


def test_membership_locks_after_first_partial_payment():
    group = SusuGroup("10.00")
    group.add_member("Ama")
    group.add_member("Kofi")
    group.record_contribution("Ama", 1, "1.00")

    with pytest.raises(SusuError, match="Week 1 has already started"):
        group.add_member("Esi")


def test_partial_contributions_track_balance_and_reject_overpayment():
    group = SusuGroup("10.00")
    group.add_member("Ama")

    assert group.record_contribution("Ama", 1, "4.25") == Decimal("5.75")
    with pytest.raises(SusuError, match="only owes 5.75"):
        group.record_contribution("Ama", 1, "5.76")
    assert group.amount_owed("Ama") == Decimal("5.75")


def test_close_week_reports_balances_then_pays_first_member():
    group = SusuGroup("10.00")
    group.add_member("Ama")
    group.add_member("Kofi")
    group.record_contribution("Ama", 1, "10.00")

    result = group.close_week()
    assert result.closed is False
    assert result.owing == {"Kofi": Decimal("10.00")}

    group.record_contribution("Kofi", 1, "10.00")
    result = group.close_week()
    assert result.closed is True
    assert result.recipient == "Ama"
    assert result.amount == Decimal("20.00")
    assert group.current_week == 2


def test_payout_order_repeats_after_every_member_receives_once():
    group = SusuGroup("1.00")
    members = ["Ama", "Kofi", "Esi"]
    for member in members:
        group.add_member(member)

    recipients = []
    for week in range(1, 5):
        for member in members:
            group.record_contribution(member, week, "1.00")
        recipients.append(group.close_week().recipient)

    assert recipients == ["Ama", "Kofi", "Esi", "Ama"]