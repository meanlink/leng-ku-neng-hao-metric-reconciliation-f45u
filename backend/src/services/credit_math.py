from decimal import Decimal


def plan_credit_applications(notes, payable):
    """Plan a FIFO draw-down of credit notes against one site's requested offset.

    ``notes`` is an ordered iterable of ``(note_id, remaining_amount)`` pairs,
    oldest note first.  The requested offset must be fully covered: when the
    available balance is short, nothing is planned at all so a failed issuance
    never consumes credit.  Returns ``(applications, shortfall)`` where each
    application is ``(note_id, amount, balance_before, balance_after)``.
    """
    payable = Decimal(payable)
    ordered = [(note_id, Decimal(remaining)) for note_id, remaining in notes]
    available = sum((remaining for _, remaining in ordered), Decimal('0'))
    if payable <= 0:
        return [], Decimal('0')
    if available < payable:
        return [], payable - available
    outstanding = payable
    applications = []
    for note_id, remaining in ordered:
        if outstanding <= 0:
            break
        take = min(remaining, outstanding)
        if take <= 0:
            continue
        applications.append((note_id, take, remaining, remaining - take))
        outstanding -= take
    return applications, Decimal('0')
