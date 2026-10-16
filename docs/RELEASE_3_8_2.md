# BDEncode 3.8.2 kiadási jegyzet

Javítás: ha a worker leáll, a program magától újraindítja, a felület pedig szól.

## Mi történt

Az nvme szerveren a BD scan nem indult el, a munka három napig `QUEUED` maradt. Az ok:

1. 2026. október 13-án 00:15-kor a szerver lemeze **megtelt** („No space left on device”).
2. A `bdencode-worker` indítási feltétele (`ExecCondition=bdencode-recovery-check --runtime`) ekkor elbukott.
3. A systemd egy elbukott `ExecCondition`-t **nem hibának**, hanem kihagyásnak tekint, ezért a `Restart=on-failure` sem lép életbe. A szolgáltatás kikapcsolva maradt, és akkor sem indult újra, amikor a hely már felszabadult.
4. A felület ezt nem jelezte, csak azt, hogy a munka vár.

## Javítás

- **Magától újraindul.** Új `bdencode-worker-ensure.timer` és `.service` (root, kétpercenként):
  - az engedélyezett, de nem futó workert elindítja (előbb törli a „failed” állapotot);
  - a worker saját indítási feltétele továbbra is érvényes: frissítés vagy helyreállítás közben nem indul el, és a következő körben újra próbálja.
  - **Szándékos leállítás karbantartáshoz:** `sudo systemctl disable --now bdencode-worker`. Egy sima `systemctl stop`-ot az időzítő két percen belül visszavonja.
- **A felület szól.**
  - Ha van várakozó vagy futó munka, de a worker nem fut, minden oldal tetején piros „A worker szolgáltatás nem fut” sáv jelenik meg, a teendővel.
  - A sávot az API `GET /api/v1/health` új `worker_active` mezője adja. Ha a gép nem tudja megmondani (nincs systemd), nem jelenik meg.
- **Lemezhely-figyelmeztetés.** A `health` új `disk_free_bytes` és `disk_total_bytes` mezői alapján:
  - 100 GiB szabad hely alatt sárga „Kevés a szabad lemezhely” sáv;
  - 30 GiB alatt piros „Majdnem megtelt a lemez”.

## Telepítés

A telepítő felrakja és bekapcsolja az időzítőt; az eltávolító törli. Egy már futó szervernél a következő frissítés hozza be, a `bdencode-worker-ensure.timer` ellenőrzése: `systemctl list-timers bdencode-worker-ensure.timer`.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.8.2`.
2. `systemctl is-active bdencode-worker-ensure.timer` → `active` (itt a „timer” a `.timer` egység).
3. Kísérlet: `sudo systemctl stop bdencode-worker`. A worker két percen belül újra fut, és közben a felületen megjelenik a piros sáv (ha van várakozó munka).
