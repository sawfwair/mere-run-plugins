# After Hours starter

Serve this directory using Python 3:

```bash
python3 -m http.server 4173 --bind 127.0.0.1
```

Open [the local site](http://127.0.0.1:4173). Use a different port if the operator
assigns one to your entry. No dependency installation or build step is required.

`data/studio.json` defines the room catalog and booking policy.
`data/bookings.json` contains reservations owned by other customers.
Dates and times are studio-local strings. Prices use integer CAD cents.
`assets/` contains original room illustrations with descriptions in the catalog.

Implement the website in `index.html`, `styles.css`, and `app.js`. You can add
local source files. Keep the fixture data and supplied assets unchanged.
