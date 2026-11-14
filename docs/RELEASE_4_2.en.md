# Accofil BDEncode 4.2.0 release notes

A new option for audio tracks fitted from an external source: the parts the source lacks can be filled from the film's own sound instead of silence.

## Why

When part of the external source (DVD, WEB-DL) is missing, for example its credits are shorter, the fitted track used to be digitally silent there. The track fitted from The Last Whale Singer (2025) Hungarian WEB-DL had 9 such gaps under the credits (0.5–2.2 s, 11.3 s in all), while the English track played music throughout.

## The option

Among the external track's settings in the wizard there is a new field: **"Parts the source lacks"**.

- **Silence** (default, as before).
- **Fill from the film's own sound:** any of the film's own audio tracks can be chosen.

The fill:

- is the chosen track, mixed to the fitted track's channel count;
- comes in each gap at the level that makes it as loud as the fitted sound on the gap's two sides (2 s each). Where both sides are silent, the whole track's average level is used. The level matching is at most ±12 dB;
- joins the fitted sound with a 25 ms crossfade (5 ms against silence, as before);
- shows on the approval card and in the public log: how many parts, how many seconds, how much level matching.

Changing the fill setting does not repeat the fit; it only renders the track again and asks for a new approval. The sync check is unchanged and measures only inside fitted parts. The listening excerpts are cut from the filled track.

Useful for music (credits). In speech the other language would be heard; keep silence there.

## Tried

On The Last Whale Singer's two sources, with the app's own steps:

- The filled parts sit exactly on the 9 gaps of the finished file.
- The level matching ranged from −0.6 to +2.8 dB, everywhere from the two sides.
- The joins have no step or click: the largest sample step matches the surrounding music's.
- **Important:** for this film the Hungarian WEB-DL credits carry different sound from the Blu-ray's English track; they do not match anywhere within ±50 ms. The fill therefore brings in the English credits music here. Listen before deciding.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.2.0`.
2. In a fit job, "Parts the source lacks" appears among the external track's settings.
3. With a fill, the approval card lists the filled parts and the level matching.
