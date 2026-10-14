#!/usr/bin/env python3
"""
Susu (Rotating Savings Group) Manager
======================================

A susu: a fixed group of members each pay the same fixed amount every
week. Each week the whole pot is paid to one member, in join order, one
member per week.

ASSUMPTIONS (things the spec left open — each is a deliberate, enforced
rule, not just an implementation detail):

1. Membership window. New members may only be added before the first
   contribution toward Week 1 has been recorded. Once anyone has paid
   anything toward Week 1, the member list is locked. The payout order is
   fixed by join order, so inserting someone later would either jump the
   queue or break the fairness of an already-running rotation.

2. A group needs at least 2 members before Week 1 can be closed. A
   1-person "rotation" isn't a susu.

3. Payments only apply to the currently open week. You cannot pay toward
   a week that's already closed, or a week that hasn't opened yet. This
   keeps "who owes what" unambiguous at all times — there is only ever
   one open ledger.

4. Overpayment is rejected outright, not banked as credit toward a future
   week. The spec says to reject amounts above what's owed for *that*
   week, so that's exactly what happens; owed = weekly_amount - already_paid.

5. Payout rotation repeats. The recipient of week w is members[(w-1) % N].
   Once every member has received the pot once, the rotation restarts at
   the first member for a new cycle, rather than the group simply ending.
   A real recurring susu keeps going; nothing in the spec says to stop.

6. Money is handled as integer cents internally (Decimal only at the
   public API boundary) so arithmetic is always exact — no binary-float
   rounding error is possible. Inputs must be exact to the cent; a value
   like 50.005 is rejected rather than silently rounded.

7. Closing a week where nobody has paid anything is handled the same as
   any other unclosed week: it simply reports that everyone owes the full
   weekly amount; it is not treated as a special/error case.

No GUI is built. A small library (SusuGroup) plus a plain text menu/CLI
sits on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional


CENT = Decimal("0.01")


class SusuError(Exception):
    """Raised for any rule violation (bad input, unknown member, etc.)."""


def _to_cents(value) -> int:
    """Convert a Decimal/str/int/float amount to an exact integer number
    of cents. Raises SusuError if the value isn't an exact multiple of
    one cent, or isn't a positive number."""
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SusuError(f"'{value}' is not a valid amount")

    if d != d.quantize(CENT):
        raise SusuError(
            f"Amount {value} is not exact to the cent (max 2 decimal places)"
        )
    if d <= 0:
        raise SusuError(f"Amount must be greater than zero, got {value}")

    return int(d * 100)


def _to_decimal(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(CENT)


@dataclass
class CloseWeekResult:
    week: int
    closed: bool
    recipient: Optional[str] = None
    amount: Optional[Decimal] = None
    owing: Dict[str, Decimal] = field(default_factory=dict)


class SusuGroup:
    def __init__(self, weekly_amount, name: str = "Susu Group"):
        self.name = name
        self.weekly_cents = _to_cents(weekly_amount)

        self.members: List[str] = []
        self._member_set = set()
        self._locked = False  # True once any Week-1 payment has been recorded

        self.current_week = 1
        # week -> {member: cents_paid_this_week}
        self._contributions: Dict[int, Dict[str, int]] = {1: {}}
        # list of dicts: {"week": int, "recipient": str, "amount": Decimal}
        self.payout_history: List[dict] = []

    # ---------------------------------------------------------- members --

    def add_member(self, member: str) -> None:
        member = (member or "").strip()
        if not member:
            raise SusuError("Member name/ID cannot be empty")
        if self._locked:
            raise SusuError(
                "Cannot add members: Week 1 has already started "
                "(a contribution has been recorded)"
            )
        if member in self._member_set:
            raise SusuError(f"Member '{member}' already exists")

        self.members.append(member)
        self._member_set.add(member)

    # ------------------------------------------------------ contributions --

    def amount_owed(self, member: str, week: Optional[int] = None) -> Decimal:
        week = self.current_week if week is None else week
        self._require_member(member)
        paid = self._contributions.get(week, {}).get(member, 0)
        return _to_decimal(self.weekly_cents - paid)

    def record_contribution(self, member: str, week: int, amount) -> Decimal:
        """Record a (possibly partial) payment. Returns remaining balance
        owed by this member for the week, after the payment."""
        self._require_member(member)

        if week != self.current_week:
            if week < self.current_week:
                raise SusuError(f"Week {week} is already closed; cannot pay toward it")
            raise SusuError(
                f"Week {week} has not opened yet; current week is {self.current_week}"
            )

        cents = _to_cents(amount)
        week_ledger = self._contributions.setdefault(week, {})
        already_paid = week_ledger.get(member, 0)
        owed = self.weekly_cents - already_paid

        if cents > owed:
            raise SusuError(
                f"{member} only owes {_to_decimal(owed)} for week {week}; "
                f"cannot accept payment of {_to_decimal(cents)}"
            )

        week_ledger[member] = already_paid + cents
        self._locked = True  # member list is locked the moment any payment lands

        return _to_decimal(owed - cents)

    # ------------------------------------------------------------- weeks --

    def close_week(self) -> CloseWeekResult:
        if len(self.members) < 2:
            raise SusuError("Need at least 2 members before a week can be closed")

        week = self.current_week
        ledger = self._contributions.get(week, {})

        owing: Dict[str, Decimal] = {}
        for m in self.members:
            paid = ledger.get(m, 0)
            short = self.weekly_cents - paid
            if short > 0:
                owing[m] = _to_decimal(short)

        if owing:
            return CloseWeekResult(week=week, closed=False, owing=owing)

        pot_cents = self.weekly_cents * len(self.members)
        recipient = self.members[(week - 1) % len(self.members)]
        amount = _to_decimal(pot_cents)

        self.payout_history.append(
            {"week": week, "recipient": recipient, "amount": amount}
        )

        self.current_week += 1
        self._contributions.setdefault(self.current_week, {})

        return CloseWeekResult(week=week, closed=True, recipient=recipient, amount=amount)

    # ------------------------------------------------------------ report --

    def report(self) -> dict:
        week = self.current_week
        ledger = self._contributions.get(week, {})
        status = []
        for m in self.members:
            paid = ledger.get(m, 0)
            owed = self.weekly_cents - paid
            status.append(
                {
                    "member": m,
                    "paid": _to_decimal(paid),
                    "owed": _to_decimal(max(owed, 0)),
                    "paid_in_full": owed <= 0,
                }
            )
        return {
            "group": self.name,
            "weekly_amount": _to_decimal(self.weekly_cents),
            "current_week": week,
            "members": status,
            "payout_history": list(self.payout_history),
        }

    def print_report(self) -> None:
        r = self.report()
        print(f"\n=== {r['group']} — Week {r['current_week']} "
              f"(weekly contribution: GHS {r['weekly_amount']}) ===")
        print("Member status:")
        for s in r["members"]:
            tag = "PAID IN FULL" if s["paid_in_full"] else f"owes GHS {s['owed']}"
            print(f"  - {s['member']}: paid GHS {s['paid']}  [{tag}]")

        print("Payout history:")
        if not r["payout_history"]:
            print("  (none yet)")
        else:
            for p in r["payout_history"]:
                print(f"  - Week {p['week']}: {p['recipient']} received GHS {p['amount']}")
        print()

    # -------------------------------------------------------------- util --

    def _require_member(self, member: str) -> None:
        if member not in self._member_set:
            raise SusuError(f"Unknown member: '{member}'")


# ============================================================ CLI layer ==

def _prompt_decimal(prompt: str) -> str:
    return input(prompt).strip()


def run_cli() -> None:
    print("=== Susu Group Setup ===")
    name = input("Group name [Susu Group]: ").strip() or "Susu Group"
    while True:
        try:
            amt = _prompt_decimal("Weekly contribution amount (e.g. 50.00): ")
            group = SusuGroup(weekly_amount=amt, name=name)
            break
        except SusuError as e:
            print(f"Error: {e}")

    menu = """   
Choose an action:
  1) Add member
  2) Record a contribution
  3) Close current week
  4) Show report
  5) Quit
"""
    while True:
        print(menu)
        choice = input("> ").strip()

        if choice == "1":
            member = input("Member name/ID: ").strip()
            try:
                group.add_member(member)
                print(f"Added member: {member}")
            except SusuError as e:
                print(f"Error: {e}")

        elif choice == "2":
            member = input("Member name/ID: ").strip()
            week_str = input(f"Week [{group.current_week}]: ").strip() or str(group.current_week)
            amount = input("Amount paid: ").strip()
            try:
                week = int(week_str)
                remaining = group.record_contribution(member, week, amount)
                if remaining == 0:
                    print(f"{member} is now paid in full for week {week}.")
                else:
                    print(f"Recorded. {member} still owes GHS {remaining} for week {week}.")
            except (SusuError, ValueError) as e:
                print(f"Error: {e}")

        elif choice == "3":
            try:
                result = group.close_week()
                if result.closed:
                    print(
                        f"Week {result.week} closed. {result.recipient} "
                        f"receives GHS {result.amount}. Now on week {group.current_week}."
                    )
                else:
                    print(f"Week {result.week} NOT closed — outstanding balances:")
                    for m, owed in result.owing.items():
                        print(f"  - {m} owes GHS {owed}")
            except SusuError as e:
                print(f"Error: {e}")

        elif choice == "4":
            group.print_report()

        elif choice == "5":
            print("Goodbye.")
            break

        else:
            print("Please choose 1-5.")


# =========================================================== demo mode ==

def run_demo() -> None:
    """Reproduces the worked example from the spec, to make the behavior
    easy to verify at a glance."""
    g = SusuGroup(weekly_amount="50.00", name="Demo Susu")
    for m in ("Ama", "Kofi", "Esi"):
        g.add_member(m)

    print(">>> Ama pays 50, Kofi pays 50, Esi pays 30 (week 1)")
    g.record_contribution("Ama", 1, "50.00")
    g.record_contribution("Kofi", 1, "50.00")
    g.record_contribution("Esi", 1, "30.00")

    print(">>> Attempting to close week 1 (Esi is short)")
    result = g.close_week()
    assert not result.closed
    assert result.owing == {"Esi": Decimal("20.00")}
    print(f"Week not closed. Esi owes {result.owing['Esi']}")

    print(">>> Esi pays the remaining 20")
    g.record_contribution("Esi", 1, "20.00")

    print(">>> Closing week 1 again")
    result = g.close_week()
    assert result.closed
    assert result.recipient == "Ama"
    assert result.amount == Decimal("150.00")
    print(f"Week 1 closed. {result.recipient} received GHS {result.amount}.")
    assert g.current_week == 2

    g.print_report()
    print("Demo assertions all passed. Kofi is next in line for week 2.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        run_demo()
    else:
        run_cli()
