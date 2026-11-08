# Accofil BDEncode 4.0.2 release notes

New: the source chooser has a checkbox to show only full discs.

## What changed

- The toolbar of the **Server storage** step has a new **Only full discs** checkbox.
- When it is on, the list hides MKV files (remuxes and finished encodes alike). Blu-ray folders and plain folders stay, because folders are the only way to step deeper.
- The filter works together with the name search.
- The browser remembers the setting, so it stays on after a reload. It is off by default.
- In an empty folder the page says when the filter hid something.

## Good to know

- Only the UI changed, not the server or the jobs. The update does not touch a running job.
- "Full disc" here means a folder the server recognises as a Blu-ray source. The checkbox is also available when fitting tracks (`fit`), but there the finished encode MKVs disappear from the list, so it is off by default.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.0.2`.
2. New job › source: the checkbox is there, and MKV files disappear when you tick it.
