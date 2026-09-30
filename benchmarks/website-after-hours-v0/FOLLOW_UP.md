# Add room cleaning time

After Hours now needs at least 15 minutes between reservations in the same room
on the same date. Update availability and confirmation validation to enforce
this rule for every new booking, against both seed and visitor reservations.
Check the gap before and after the proposed reservation. An exact 15-minute gap
is allowed. Half-hour starts and the existing duration choices stay unchanged.

Do not move, cancel, reprice, or rewrite existing reservations. Keep their saved
records usable after refresh, even if they no longer satisfy the new gap rule.
Cleaning time does not change the visitor's price or booked duration. It does
not need to fit inside opening hours after the final booking of the day.

Explain the rule where the visitor chooses a time. Preserve the rest of the
experience. In your final response, describe what changed and what you tested.
