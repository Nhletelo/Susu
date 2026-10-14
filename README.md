
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

