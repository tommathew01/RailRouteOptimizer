"""User-facing disclaimers required by doc 01 §10. Single source for API and UI."""

from __future__ import annotations

SEPARATE_TICKETS = "Each segment is a separate reservation and may create a separate PNR."
NOT_THROUGH_TICKET = (
    "Separate tickets are not a through ticket and do not grant break-of-journey rights."
)
AVAILABILITY_CHANGES = (
    "Availability can change before you book. Booking one segment does not reserve the others."
)
SEAT_CHANGES = (
    "Each ticket may get a different coach, berth or status; you may have to change seats "
    "where one segment ends and the next begins."
)
SINGLE_PASSENGER = (
    "Availability is checked for a single-passenger ticket and does not guarantee seats "
    "for a group."
)
BOOKABLE_NOT_CONFIRMED = (
    "A segment can be bookable while waitlisted; bookable does not mean confirmed."
)
PREDICTION = (
    "Predictions are RailKit's own estimates, not guarantees, and never change the current status."
)
VERIFY_BEFORE_PAYING = "Verify every segment on an authorized booking platform before paying."
INDEPENDENT = "RailRoute is independent and is not affiliated with Indian Railways or IRCTC."
DEMO_MODE = (
    "Demo mode: trains and availability are simulated mock data, not live railway information."
)
DATE_POLICY_UNVERIFIED = (
    "Some segments board after midnight and were checked using the train's start date, which "
    "differs from the date rule the provider was observed to use. Re-check those segments before "
    "booking."
)

ALWAYS = (
    SEPARATE_TICKETS,
    AVAILABILITY_CHANGES,
    SEAT_CHANGES,
    SINGLE_PASSENGER,
    BOOKABLE_NOT_CONFIRMED,
    PREDICTION,
    NOT_THROUGH_TICKET,
    VERIFY_BEFORE_PAYING,
    INDEPENDENT,
)
