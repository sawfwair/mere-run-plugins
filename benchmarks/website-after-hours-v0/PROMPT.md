# Build After Hours

Build a polished booking website for After Hours, a fictional creative studio
with six spaces. Help a visitor choose a suitable room, find a free time, and
manage their reservations. Give the studio a distinctive visual identity.
Choose the layout, typography, colors, and interaction design yourself.

Work in `site/`. Use HTML, CSS, and browser JavaScript, with no build step or
external dependencies. The starter provides local images and JSON data, but
does not implement the product. You can replace its HTML, CSS, and JavaScript.
Keep the supplied data and image files unchanged. Use system fonts and supplied
assets; do not fetch external fonts, images, scripts, or services.

## Required experience

- Browse all six rooms with their image, name, capacity, and hourly CAD price.
- Combine minimum-capacity, equipment, and maximum-hourly-price filters.
  Selected equipment uses AND matching. Include a useful empty state and a
  way to clear filters.
- Open a room's details to review its description, amenities, price, and
  availability for the selected date.
- Choose a date, start time, and duration. Show the end time and total CAD price
  before confirmation. Charge by duration with no taxes or fees.
- Create a reservation and show its room, date, times, and total in **My bookings**.
  Let the visitor cancel their own reservations. Seed reservations block time
  but belong to other customers; do not offer cancellation for them.
- Persist the visitor's reservations and cancellations in localStorage across
  refreshes. Seed reservations remain in effect and must not be duplicated.
  Clearly describe this as a demo saved in this browser. Do not add accounts,
  payments, customer contact fields, or backend services.

## Booking rules

Read the facts from `data/studio.json`. All dates and times are studio-local
calendar values, independent of the browser's time zone. The booking window is
October 12–13, 2026, inclusive. Do not reject these dates based on today's date.
The studio opens at 09:00 and closes at 21:00 on both days.

Starts must fall on a half hour: `:00` or `:30`. Durations are 30, 60, 90, or
120 minutes. A booking must fit entirely inside opening hours on one date.
Reject missing or invalid values with helpful messages, or prevent invalid
choices with an understandable explanation. Recheck validity on confirmation.

Two bookings conflict only when their time intervals overlap in the same room
on the same date. A booking ending at 11:00 permits another starting at 11:00.
Different rooms can be booked at the same time. Existing reservations are in
`data/bookings.json`.
Seed reservations include a legacy time that is not on a half hour. Preserve
that time exactly; the half-hour rule applies to new visitor bookings.

## Quality expectations

Make the complete workflow usable at 390 × 844 and 1440 × 1000 CSS pixels.
Use semantic controls, visible labels, clear keyboard focus, readable contrast,
and errors associated with their fields. Make confirmations perceivable without
relying on color. If you use a modal, manage focus and keyboard dismissal.
Keep the page free of horizontal overflow at the supplied viewport sizes.

Test your work in the browser when the available tools support it. In your final
response, state what you implemented, what you tested, and any known gaps.
