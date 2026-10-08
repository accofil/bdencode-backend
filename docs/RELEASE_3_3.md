# BDEncode 3.3.0 kiadási jegyzet

A GPU opcionális, GPU nélküli Linux-szerveren is teljes értékű a működés.

## Változások

- **Csak a meglévő GPU kerül bekötésre.** A worker szolgáltatás egységfájlja eddig fixen a WSL-es `/dev/dxg` eszközt kötötte be. Natív Linuxon egy esetleges NVIDIA GPU így el sem érhető volt, GPU nélküli gépen pedig egy nem létező eszközre hivatkozott. Most a telepítő minden futáskor megnézi, mely GPU-eszközök vannak a gépen, és csak ezeket köti be a `bdencode-worker.service.d/gpu.conf` kiegészítőben:
  - WSL-en a `/dev/dxg`-t;
  - natív Linuxon az NVIDIA-illesztő eszközeit (`/dev/nvidiactl`, `/dev/nvidia-uvm`, `/dev/nvidia0`…).

  GPU nélkül a kiegészítő nem készül el, és a crop-keresés CPU-n fut.
- **Rendszer oldal:** a Processzor kártya kiírja, hogy van-e GPU a crop-kereséshez, vagy CPU-n fut.
- **`doctor --json`:** új mező a `worker_gpu`, benne a bekötött eszközök, a `crop_hwaccel` beállítás és a dekódolás módja (`gpu_if_available`, `gpu`, `cpu`).
- Ha később kerül GPU vagy NVIDIA-illesztő a gépre, a telepítő újrafuttatása beköti.

A kódolás és a minőségellenőrzés eddig is CPU-n futott, ezen nem változtat.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.3.0`.
2. GPU-s gépen (WSL): a `/etc/systemd/system/bdencode-worker.service.d/gpu.conf` létezik és a `/dev/dxg`-t tartalmazza; a Rendszer oldalon „GPU a crop-kereséshez (/dev/dxg)” látszik.
3. GPU nélküli gépen: a `gpu.conf` nem létezik; a Rendszer oldalon „Nincs GPU: a crop-keresés CPU-n fut” látszik, és egy új munka crop-keresése a „Crop-keresés (CPU…)” lépéssel fut végig.

## További dokumentáció

- README 14.3: az előkészítés gyorsítása, GPU nélküli szerver
- [BDEncode 3.2 kiadási jegyzet](RELEASE_3_2.md)
