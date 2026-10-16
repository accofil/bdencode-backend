# BDEncode 3.8.3 kiadási jegyzet

Javítás: a 3.8.2 worker-újraindító időzítője megzavarta a frissítést. Aki a 3.8.2-t telepítette, annak ez a verzió rendbe teszi.

## Mi történt

A 3.8.2 bevezette a `bdencode-worker-ensure.timer`-t, amely kétpercenként elindítja a leállt workert. A canadai szerver frissítése ezzel meghiúsult: a telepítő „Job for bdencode-worker.service canceled” hibával visszagörgetett. A rendszer a 3.8.1-en maradt, és minden működött, de a frissítés nem sikerült.

Az ok két hiba együtt:

1. **Az időzítő azonnal elsült.** Az `OnBootSec=2min` már régen letelt, amikor a telepítő frissítés közben újraindította az időzítőt, ezért az rögtön lefutott.
2. **Leálló workert „leállt”-nak vett.** A parancs csak azt kérdezte, hogy a worker nem aktív-e. Egy épp leálló (`deactivating`) worker erre is igent mond, ezért az időzítő sorba állított egy indítást, miközben a telepítő a workert épp cserélte. A telepítő saját műveletével ezt felülírta, az indítás megszakadt, a telepítő pedig hibával visszagörgetett.

## Javítás

- Az időzítő (`OnActiveSec` + `OnUnitActiveSec`) az indulása után két perccel fut először, nem azonnal.
- A logika egy külön, tesztelt segédszkriptbe került (`/usr/local/libexec/bdencode-worker-ensure`). Csak akkor indít, ha:
  - a worker engedélyezett;
  - az állapota egyértelműen `inactive` vagy `failed` (leállás, indulás vagy újratöltés közben nem nyúl hozzá);
  - nincs folyamatban telepítés, frissítés vagy helyreállítás: a `/var/lib/bdencode` alatti tranzakciós jelzők hiányoznak, és a `bdencode-update.service` nem fut.
- Szándékos leállításhoz továbbra is: `sudo systemctl disable --now bdencode-worker`.

## Ha a 3.8.2 részben települt egy szerverre

A 3.8.2 sikertelen telepítése után a szerver 3.8.1-en fut, de a 3.8.2 időzítő- és szolgáltatásfájlja már fent lehet. A 3.8.3 telepítője felülírja őket. Addig, ha a frissítés közben zavart okoz: `sudo systemctl disable --now bdencode-worker-ensure.timer`.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.8.3`.
2. `systemctl list-timers bdencode-worker-ensure.timer`: aktív, a következő futás két percen belül.
3. Kísérlet: `sudo systemctl stop bdencode-worker`. Két percen belül a worker magától újra fut.
