# Accofil BDEncode 4.3.2 release notes

Fix: a failed remux QC verdict is not saved, so a retry (for example after a fixed release) really measures again.

## The bug

After 4.3.1, The Last Whale Singer remux stopped again on restart with the same error ("03-audio.dtsma decodes differently from the disc"). 4.3.1's improved check never ran: QC saved its report as an intermediate result even when it failed, and the restart read that old failed report back.

## The fix

- The remux QC saves only a passed report as an intermediate result. A failed one is measured again on every retry, by the code that is running.
- The intermediate result's schema version is 2. Verdicts saved by earlier versions, possibly failed ones, are invalid, so jobs already stuck measure again too.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.3.2`.
2. The Whale Singer remux passes QC after a restart.
