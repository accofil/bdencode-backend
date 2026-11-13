# Accofil BDEncode 4.1.7 release notes

Fixes: the source browser shows and finds every file of a large folder; the Windows keep-alive task also starts where Task Scheduler does not run a PowerShell script from a file.

## The bugs

**MKV files missing from the source chooser.** canada2's `aither` folder holds 2259 entries (522 folders, 1737 MKV files). The server silently cut a folder's listing at 1000 entries. Folders came first and then the MKV files in alphabetical order, so only the first 478 MKV files showed. "The.Last.Whale.Singer…PENICILLIN.mkv" therefore did not appear. The name search ran in the browser on the already cut list, so searching for it did not bring it up either. The external-track browser got the same list, with no name search at all. Clicking an MKV's name there tried to open it as a folder.

**The "BDEncode WSL" task stopped at once (Windows).** On one machine the PowerShell started by Task Scheduler did not run `%LOCALAPPDATA%\BDEncode\keepalive.ps1` (`-File`, result `0xFFFD0000`). `-Command` and `-EncodedCommand` worked in the same place. Without the task, WSL and BDEncode in it can stop when nothing else uses them.

## The fixes

- **Source listing:** `GET /api/v1/sources` returns up to 5000 entries (1000 before). The new `q` parameter filters names on the server, over the whole folder, before the limit. The answer carries the new fields `truncated` and `total`.
- **New job page:** the name search also goes to the server (after a short delay). A cut listing says how many of how many entries are shown.
- **External-track browser:** it gained a name search and the truncation notice. Clicking an MKV's name chooses the file instead of trying to open it.
- **Windows installer:** the keep-alive loop lives in the task itself (`-EncodedCommand`); the installer deletes the `keepalive.ps1` file.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.1.7`.
2. In canada2's `aither` folder a search for "whale" finds the PENICILLIN MKV.
3. On Windows the "BDEncode WSL" task is `Running`.
