# BDEncode

**Encode Blu-ray and UHD Blu-ray discs from your browser, step by step.**

BDEncode turns a disc folder (the disc's `BDMV` folder) into a finished MKV file: you pick the movie, the audio and subtitle tracks, and the program encodes the video and audio, checks the quality, makes comparison screenshots and assembles a release kit (NFO, description, MediaInfo, images). You control everything from a web page; the command line is only needed during installation.

> [!IMPORTANT]
> BDEncode is in **testing (beta)**. Try it first on a shorter or less important disc, and always watch the finished MKV in a player.

> [!NOTE]
> **The web interface speaks English and Hungarian.** Switch with the **HU / EN** buttons at the bottom of the menu; on the first visit it follows your browser's language. This guide uses the English names of buttons and menu items.

*Magyar változat: [README.md](README.md). The detailed technical reference (in Hungarian): [docs/REFERENCE.md](docs/REFERENCE.md).*

## Contents

1. [What it does, and what it does not](#1-what-it-does-and-what-it-does-not)
2. [What you need](#2-what-you-need)
3. [Which installation is yours?](#3-which-installation-is-yours)
4. [Installation: Windows](#4-installation-windows)
5. [Installation: Debian server](#5-installation-debian-server)
6. [Installation: Swizzin seedbox](#6-installation-swizzin-seedbox)
7. [First login and checks](#7-first-login-and-checks)
8. [Image uploads (optional)](#8-image-uploads-optional)
9. [AI adviser (optional)](#9-ai-adviser-optional)
10. [Your first encode, step by step](#10-your-first-encode-step-by-step)
11. [Everyday use](#11-everyday-use)
12. [Updates](#12-updates)
13. [When something goes wrong](#13-when-something-goes-wrong)
14. [Uninstalling](#14-uninstalling)
15. [Privacy and security](#15-privacy-and-security)
16. [Glossary](#16-glossary)

---

## 1. What it does, and what it does not

**What it does:**

- scans the disc and shows its versions (playlists), audio and subtitle tracks;
- encodes the video: x264 for 1080p Blu-ray, x265 for UHD, keeping HDR10 (and, on request, Dolby Vision and HDR10+);
- keeps or converts the audio (for example FLAC, AC-3, E-AC-3, DTS);
- crops the black bars automatically;
- checks every frame and proves the quality with metrics (SSIM, PSNR, VMAF);
- makes comparison screenshots of source and encode, and uploads them to an image host if you ask it to;
- orders the tracks by the Aither or nCore rules, suggests a release name and builds a release kit;
- runs one encode at a time, while you already prepare the next discs.

**What it does not do:**

- **it does not break disc copy protection**: it needs an already unpacked disc folder containing `BDMV` (not an ISO file);
- **it does not create torrents or upload to a tracker**: you make the torrent from the finished MKV, following your tracker's rules;
- no 3D;
- no GPU encoding (video is always encoded on the CPU; an NVIDIA GPU, if present, only speeds up the crop search).

> [!NOTE]
> The program is meant for backups of discs you own. Following your trackers' rules is your responsibility.

## 2. What you need

Tick these off before you start:

| | What? | Note |
|---|---|---|
| ☐ | **A machine**: a Windows 10/11 PC, or a Debian 12/13 server (a seedbox works too) | see [section 3](#3-which-installation-is-yours) |
| ☐ | **CPU**: the more cores, the better | encoding uses the CPU fully; you set the upper limit |
| ☐ | **Memory**: at least 8 GB, 16 GB or more for UHD | |
| ☐ | **Free space**: about 2.5 times the disc size | about 150–200 GB for a UHD film, 60–100 GB for 1080p; the finished file is only part of this |
| ☐ | **Disc folder**: the unpacked disc folder (with `BDMV` and usually `CERTIFICATE`) | unpack ISOs first |
| ☐ | **Internet** during installation | the installer downloads programs |
| ☐ | **Patience**: a UHD film can take 1–2 days | see below |

**How long does it take?** That depends on the machine and the settings. As a guide: a two-hour UHD film with x265 and the `slow` preset takes about a day on a 16-core/32-thread machine, heavier settings can take two days. A 1080p film with x264 usually takes a few hours. While encoding, the program shows the speed and the expected finish.

## 3. Which installation is yours?

| Your situation | Follow |
|---|---|
| You want to run it on your Windows 10/11 PC at home | [4. Installation: Windows](#4-installation-windows) |
| You have a Debian server (VPS, own machine, rented server) **without Swizzin** | [5. Installation: Debian server](#5-installation-debian-server) |
| You have a seedbox **with Swizzin** (it serves, for example, the qBittorrent web UI) | [6. Installation: Swizzin seedbox](#6-installation-swizzin-seedbox) |

Not sure whether your server has Swizzin? Log in with SSH (see [5.2](#52-connect-to-the-server)) and run `ls /etc/swizzin`. If the folder exists, you have Swizzin.

---

## 4. Installation: Windows

On Windows, BDEncode runs in a built-in Linux environment (WSL2, Debian), but you do not have to deal with it: the installer sets everything up, and you use the program from your browser.

### 4.1. Preparation

1. You need administrator rights on the PC.
2. Keep at least **100 GB** free on drive C: (the Linux environment and the work files go there).
3. Make a folder for your discs on a drive with a letter, for example `D:\Movies`. Each disc goes into its own subfolder:

   ```text
   D:\Movies\A.Film.2001\BDMV
   D:\Movies\Another.Film.1999\BDMV
   ```

   Network paths (`\\server\share`) are not accepted by the installer.
4. On a laptop, make sure it does **not sleep** while plugged in (Settings → System → Power), otherwise encoding stops while it sleeps.

### 4.2. Download

1. Open the [project's GitHub page](https://github.com/accofil/bdencode-backend).
2. Click the green **Code** button, then **Download ZIP**.
3. Unpack the ZIP to a permanent place, for example `C:\BDEncode` (do not start it from inside the ZIP!).

### 4.3. Start the installer

1. Open the `install` folder inside the unpacked folder.
2. **Right-click** `windows-install.cmd` and choose **Run as administrator**.
3. Answer **Yes** when Windows asks whether the app may make changes.
4. A window opens in which the installer works. **Do not close it**, even if no new line appears for minutes.

The installer turns on WSL2, installs Debian, creates a Linux user (based on your Windows user name; it asks for no password), installs the media tools and BDEncode.

### 4.4. If it asks for a restart

This is normal on the first installation (WSL has to be switched on):

1. Press **Enter** and restart the PC.
2. Log back in to the same Windows account.
3. The installer continues on its own. If it does not, run `windows-install.cmd` as administrator again: it continues where it stopped.

### 4.5. Choose the disc folder

During the installation a folder picker opens. Choose the folder **that contains the disc folders** (`D:\Movies` in the example above), not the folder of one disc.

### 4.6. Done!

The first installation can take up to an hour. At the end you see:

```text
BDEncode Windows/WSL installation is healthy.
Web: http://localhost:8787/encoder/
```

Two shortcuts appear on your desktop:

- **BDEncode** – opens the web interface (`http://localhost:8787/encoder/`);
- **BDEncode elkészült filmek** (BDEncode finished films) – opens the folder of the finished files.

Continue with [section 7](#7-first-login-and-checks).

---

## 5. Installation: Debian server

This path is for a Debian 12 or 13 server without Swizzin. On the server, the web interface is only reachable from inside; you open it from your own computer through a secure SSH tunnel (see [5.8](#58-open-the-page-through-an-ssh-tunnel)). So you do not have to open a port or set a password for the web page.

### 5.1. What you need to know about the server

- its address (IP address or domain name) and, if it is not the usual 22, the SSH port;
- your user name and password (or SSH key);
- whether your user may use `sudo` (administrator rights). Your provider can tell you, or you try it in [5.3](#53-checks).

> [!WARNING]
> Do not install as `root`. The installer asks for `sudo` itself where it needs it.

### 5.2. Connect to the server

Windows 10/11 PowerShell already has the `ssh` command. Open a PowerShell window (Start menu → "PowerShell") and type (with your own user name and server):

```bash
ssh user@server
```

If SSH does not run on port 22, give the port too: `ssh -p 2222 user@server`. On the first connection you are asked to confirm the server's identity: type `yes`. Then enter your password (nothing shows while you type; that is normal).

### 5.3. Checks

Run these one at a time and look at the answer:

```bash
cat /etc/os-release
```

The `VERSION_CODENAME` line should be `bookworm` (Debian 12) or `trixie` (Debian 13).

```bash
sudo -v
```

If it asks for your password and then shows no error, you have `sudo`. If it says you are not in the "sudoers" file, ask the server's owner for the right.

### 5.4. Basic packages

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y git tmux
```

### 5.5. Folders and discs

By default BDEncode looks for discs and works here:

| Folder | What for? |
|---|---|
| `~/storage` | the disc folders (source) – the program only reads them |
| `~/encode` | the program's own area: database, work files, finished films (`~/encode/completed`) |

Create the source folder:

```bash
mkdir -p ~/storage
```

Copy the discs (whole folders including `BDMV`) there with a file transfer program, for example **WinSCP** or **FileZilla** (SFTP, with the same user and password as SSH). The result should look like this:

```text
~/storage/A.Film.2001/BDMV
~/storage/Another.Film.1999/BDMV
```

If your discs are somewhere else (for example in a torrent client's download folder), you can give that folder to the installer, see [5.6](#56-run-the-installer).

### 5.6. Run the installer

Installation can take a while (a few minutes on a fast machine, up to an hour on a slow one). So that a dropped SSH connection does not stop it, we run it inside a `tmux` "session":

```bash
tmux new -s bdencode
```

Download the program:

```bash
git clone https://github.com/accofil/bdencode-backend.git ~/bdencode-backend
```

```bash
cd ~/bdencode-backend
```

Start the installer with the default folders (`~/storage` and `~/encode`):

```bash
bash install/install.sh
```

**If your discs are elsewhere**, give the folder like this (`~/torrents` in the example):

```bash
BDENCODE_SOURCE_ROOT="$HOME/torrents" bash install/install.sh
```

Also useful: `BDENCODE_CPU_PERCENT=60` (use at most this percentage of the machine's CPU; 80 by default, and you can change it later on the web page).

The installer may ask for your `sudo` password several times. At the end it prints:

```text
Web page (loopback only): http://127.0.0.1:8787/encoder/
From your own computer: ssh -L 8787:127.0.0.1:8787 user@<server>, then open http://localhost:8787/encoder/
```

**If the connection drops:** log in again with SSH and reattach to the running installation: `tmux attach -t bdencode`. To leave `tmux` without stopping the installation, press `Ctrl+B`, then `D`.

### 5.7. Allow automatic updates (recommended, optional)

BDEncode checks every day whether there is a new release. It can install it on its own only if your user may use `sudo` **without a password**. The risk: anyone who gets into your user becomes administrator without a password. If you accept that:

```bash
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/bdencode-$USER
```

```bash
sudo chmod 0440 /etc/sudoers.d/bdencode-$USER
```

If you skip this, the program shows new releases on the web page, and you update by hand as described in [section 12](#12-updates).

### 5.8. Open the page through an SSH tunnel

On the server, the web interface is only reachable from inside. On your own computer, open a **new** PowerShell window and run:

```bash
ssh -L 8787:127.0.0.1:8787 user@server
```

Log in and **leave this window open**. While it is open, this address in your browser shows the server's BDEncode page:

```text
http://localhost:8787/encoder/
```

If you close the window, the page becomes unreachable, but encoding keeps running on the server. Next time, open it again with the same command.

Continue with [section 7](#7-first-login-and-checks).

---

## 6. Installation: Swizzin seedbox

On a Swizzin server, the installer recognises Swizzin's web server and publishes the interface at the seedbox's own address, protected by your Swizzin password: `https://your-seedbox/encoder/`.

### 6.1. Installation

Follow the Debian steps [5.1 to 5.6](#51-what-you-need-to-know-about-the-server), with these differences:

- **The disc folder:** on Swizzin, downloads often live under `~/torrents` or `~/storage`. If your discs are under `~/torrents`, start the installer like this:

  ```bash
  BDENCODE_SOURCE_ROOT="$HOME/torrents" bash install/install.sh
  ```

- **Sharing the CPU:** your torrent client runs on the seedbox too. If seeding slows down while encoding, give a smaller CPU share: `BDENCODE_CPU_PERCENT=60` (or later on the web page, see [7.3](#73-set-the-cpu-share)).
- **On a slow, HDD-only machine** the installation can take up to an hour (it runs tests meanwhile). That is why `tmux` matters.

### 6.2. Automatic updates

Same as on a Debian server: [5.7](#57-allow-automatic-updates-recommended-optional).

### 6.3. Open the page

Open in your browser:

```text
https://your-seedbox/encoder/
```

User name and password are the same as for Swizzin's other web pages. No SSH tunnel is needed here.

Continue with [section 7](#7-first-login-and-checks).

---

## 7. First login and checks

### 7.1. The interface

The menu on the left:

| Menu item | What for? |
|---|---|
| **Overview** | summary of the running job and the queue |
| **New encode** | add a new disc |
| **Queue** | all jobs and their states |
| **Finished jobs** | the finished films |
| **Comparisons** | the comparison screenshots |
| **Statistics** | sizes, quality, speed |
| **System** | server status and settings |
| **Help** | help for every encoding setting |

The installed version is shown at the top of the menu, under the BDEncode title. The **HU / EN** buttons at the bottom of the menu switch the language.

### 7.2. Check the System page

Open **System** and look at:

- **Backend: Online** – the program runs;
- **Installed programs**: **Available** next to each, and **VapourSynth OK** in the card's header;
- **Storage**: enough free space?
- **Processor**: the number of logical CPUs, the CPU share, and whether there is a GPU for the crop search (no GPU is fine).

If anything is red, see [section 13](#13-when-something-goes-wrong).

### 7.3. Set the CPU share

On **System**, the **CPU-keret** (CPU share) card sets the largest share of the CPU the encoder may use. You can set a separate night value too (for example 100% at night, 60% during the day) if other things run on the machine by day. The change takes effect within seconds, even for a running encode.

---

## 8. Image uploads (optional)

The program can upload the comparison screenshots to an image host and turn them into ready BBCode for your tracker description. You need the key of at least one host:

| Host | What you need | Setting name |
|---|---|---|
| ImgBB | API key (on ImgBB's API page after registering) | `imgbb-api-key` |
| Catbox | user hash ("userhash", on your account page) | `catbox-userhash` |
| Freeimage | API key (on Freeimage's API page) | `freeimage-api-key` |

One is enough, two are better: if one host fails, the program tries the next. Everything works without image uploads too; the images stay in the finished folder.

> [!IMPORTANT]
> Never paste a key into a chat or a bug report, or show it in a screenshot. The method below stores it encrypted and does not show it while you type.

**1. Open a command line on the BDEncode machine.** On Windows, open PowerShell and type `wsl -d Debian` (this takes you into BDEncode's Linux environment). On a server, log in with SSH.

**2. Paste this whole block at once and press Enter** (it creates a helper command):

```bash
install_bdencode_secret() {
    credential_name="$1"
    credential_dir="$HOME/.config/bdencode"
    temporary_file="$(mktemp)"
    mkdir -p "$credential_dir"
    chmod 700 "$credential_dir"
    read -r -s -p "value of $credential_name: " credential_value
    printf '\n'
    printf '%s' "$credential_value" > "$temporary_file"
    unset credential_value
    sudo systemd-creds encrypt \
        --name="$credential_name" \
        "$temporary_file" \
        "$credential_dir/$credential_name.cred"
    rm -f "$temporary_file"
    sudo chown "$USER:$(id -gn)" \
        "$credential_dir/$credential_name.cred"
    chmod 600 "$credential_dir/$credential_name.cred"
}
```

**3. Enter your keys.** Run only the lines you have a key for; the program asks for the value (nothing shows while typing):

```bash
install_bdencode_secret imgbb-api-key
```

```bash
install_bdencode_secret catbox-userhash
```

```bash
install_bdencode_secret freeimage-api-key
```

**4. Run the installer again** so that the program picks up the keys:

- On Windows: leave the Linux environment (`exit`) and run `windows-install.cmd` as administrator again.
- On a server:

  ```bash
  cd ~/bdencode-backend && bash install/install.sh
  ```

Check: on **System**, the image hosts show **Ready to use**.

## 9. AI adviser (optional)

An AI (OpenAI or Claude) can suggest encoding settings from the disc's technical data and the goal you describe. You need your own API key (the provider may charge for it). Everything else works without a key.

1. Open **System** and find the **AI adviser** card.
2. In the row of the provider you want, enter the key and click **Save key**.
3. After a few seconds the row shows **Key set**.

The AI never receives the film, images or file names, only a short technical summary. Its suggestion only fills in the fields; you still approve them.

---

## 10. Your first encode, step by step

### 10.1. Create a job

1. Click **New encode**.
2. **Source**: click the disc's folder. Folders containing `BDMV` are marked **Blu-ray source**. If you do not see your disc, click **Refresh**.
3. Click **Next**.
4. **Content**: enter a job name (for example the film's title), check the disc type (BD or UHD), and choose what is on the disc: **Film**, **Concert**, **Anime** or **Series disc**.
5. **Mode**: the first time, choose **Beginner**. Here you can also switch **Upload comparison images** on or off.
6. Click **Create job and scan**.

The scan maps the disc in a few minutes. This is not the encode yet.

### 10.2. The settings wizard

When the scan is done, the job page shows the **Your turn** card. Open the **Settings** tab. The wizard has four steps:

**1. Playlist** – the film versions on the disc. Usually the longest one is the film, but take care:

- if several have a similar length, they can be the theatrical cut, the director's cut or another edit: compare the length, the number of chapters and audio tracks;
- some discs contain fake "trap" playlists; the program marks them.

**2. Tracks** – audio and subtitle tracks.

- At the top you can choose a **tracker profile** (Aither or nCore). The **Arrange tracks** button then orders the tracks by the tracker's rules, and the **What changed** list shows what it changed.
- For each audio track choose what happens to it: **Copy** (kept unchanged), **FLAC**, **AC-3**, **E-AC-3**, **DTS** or **Omit**. If unsure, keep the suggested value.
- For each kept subtitle you must choose **Teljes felirat** (Full subtitle) or **Forced / signs**.
- **Track analysis from the disc:** at the end of the scan the program takes a few short windows of the film (6 × 30 seconds), detects the audio languages by speech recognition and counts the subtitle events. In the rows you see:
  - for audio "From the audio: English, 95%"; if that differs from the disc's label, a yellow warning and an **Accept** button;
  - for subtitles "Suggestion: Full subtitle (31 events in 3 min sampled…)" or "Suggestion: Forced / signs", with an **Accept suggestion** button. A full subtitle has several events a minute, a forced one only a few in the whole film.

  **Accept all suggestions** takes them all at once. They are suggestions: if in doubt, check the finished file, or leave the track out.
- If a track's language is missing or uncertain, the program tells you; choose it by hand.

**3. Video** – the encoding settings.

- In Beginner mode the program gives safe defaults; just keep them.
- The **?** button next to every setting opens an explanation.
- If you set up the AI adviser, you can ask it here (**Ask for an AI suggestion**).
- Cropping the black bars is automatic.

**4. Check**

1. Enter the output name. With a tracker profile, **Suggest name** builds a name that follows the rules (your browser remembers your release tag).
2. Click **Check plan**. The program checks all settings.
3. Fix anything shown in red. Read the yellow warnings.
4. Click **Approve and start automatically**.

The job is now **Waiting to encode**, and if no other encode is running, it starts.

### 10.3. Follow the job

On the job page, the **Most fut** (Running now) panel shows what the program is doing (for example reference remux, crop search, encoding, quality check), how much is left, and while encoding the speed and the expected file size. You can close the page: the job keeps running in the background.

The job's states in order (the queue and the job page show these): **Waiting for scan** → **Analysing disc** → **Waiting for settings** (your turn) → **Waiting to encode** → **Encoding video** (with the preparation, this is the longest) → **Building MKV** → **Quality check** → **Comparison** → **Uploading images** (if requested) → **Finished**.

### 10.4. The finished film

When the job is **Finished**:

- **On Windows**, the desktop shortcut **BDEncode elkészült filmek** opens the folder of finished files.
- **On a server**, finished films are here: `~/encode/completed/<film-name>/`.

The folder holds the MKV and next to it the MediaInfo, the BBCode and the comparison images. On **Finished jobs**, click the job to see the quality results, images and logs, and even peek into the film with the built-in player.

**Always watch the finished film in a player:** the start, the end, a chapter change, and switch between the audio and subtitle tracks.

### 10.5. Release kit (optional)

On the finished job's page, the **Prepare release** panel assembles what you need for uploading: NFO, BBCode description, MediaInfo, verified images, checksums. You make the torrent from the finished MKV according to your tracker's rules and upload it yourself.

---

## 11. Everyday use

**One encode runs at a time**, but meanwhile you can add and set up new discs: they wait as **Waiting to encode** and start automatically in turn.

**When the program asks you something** (the job shows **Needs review**), a card on the job page shows what to do. Common cases:

- **language:** a track's language is unclear – choose it and click **Confirm languages and continue**;
- **image upload:** the upload failed – retry, choose another host, or finish without images (none of these re-encodes the video).

**Pause, cancel, restart** – in the job page's **Actions** menu:

| Action | What for? |
|---|---|
| **Pause** / **Resume** | stops the job for a while; finished steps are kept |
| **Cancel** | stops the job |
| **Restart** (for a cancelled job) | **Restart unchanged**: back to the queue with the same settings; **Change settings**: the wizard opens with the previous settings filled in and you can change anything |
| **Continue from the error** (for a failed job) | continues where the error happened |
| **Delete job** | deletes the job and its temporary files; the finished film and the original disc stay |

On restart the program keeps what the change does not affect (for example the disc read and the crop search) and redoes only what it must.

**Free up space:** a finished job's temporary files can be removed with **Clean up** on its page; the finished film stays. Never delete files by hand under a running job.

---

## 12. Updates

**Automatically:** once a day the program checks for a new release and, if no job is running, updates itself (on a server this needs [5.7](#57-allow-automatic-updates-recommended-optional)). If something goes wrong, the old version stays. The **Release check and update** card on **System** shows the state.

If a browser tab left open still shows the old interface, the menu shows an **Reload page** button.

**By hand, on Windows:** download the ZIP again ([4.2](#42-download)), unpack it over the old one and run `windows-install.cmd` as administrator. Your settings and jobs are kept.

**By hand, on a server:**

```bash
cd ~/bdencode-backend && git pull --ff-only && bash install/install.sh
```

Wait for a running encode to finish before updating.

---

## 13. When something goes wrong

| Symptom | What to do |
|---|---|
| **Windows:** `localhost:8787` does not open | Wait half a minute and reload. If it still fails, open PowerShell as administrator and run `Start-ScheduledTask -TaskName "BDEncode WSL"`, then `wsl -d Debian -- sudo systemctl restart bdencode-api bdencode-worker nginx` |
| **Server:** `localhost:8787` does not open | Is the SSH tunnel window open ([5.8](#58-open-the-page-through-an-ssh-tunnel))? If yes, on the server: `sudo systemctl restart bdencode-api bdencode-worker nginx` |
| **Swizzin:** `/encoder/` shows an error | On the server: `sudo systemctl restart bdencode-api bdencode-worker` and `sudo systemctl reload nginx` |
| The disc does not show under **New encode** | Did you give the right folder at installation? `BDMV` must be directly inside the disc's folder. Click **Refresh**. |
| The laptop went to sleep and encoding stopped | After waking up the job continues. Set the laptop not to sleep while plugged in. |
| Out of space | Remove old finished jobs' temporary files (**Clean up**) or unneeded jobs (**Delete job**). One job needs the space given in [section 2](#2-what-you-need). |
| **Needs review** | Open the job: the card says what to do ([section 11](#11-everyday-use)). |
| **Upload failed** | On the job page: retry, another host, or finish without images. Check the image host keys ([section 8](#8-image-uploads-optional)). |
| **Failed** | Read the error on the job page. **Continue from the error** continues where it stopped. |
| Encoding is very slow | Check the CPU share on **System** ([7.3](#73-set-the-cpu-share)). Slower settings (for example the `slower` preset) take much longer. |

**Logs** (needed if you ask for help):

- Windows installation: `%LOCALAPPDATA%\BDEncode\install.log` (in PowerShell: `notepad "$env:LOCALAPPDATA\BDEncode\install.log"`);
- the running program's log (on a server, or on Windows after `wsl -d Debian`):

  ```bash
  journalctl -u bdencode-worker.service -n 200 --no-pager
  ```

- full system report:

  ```bash
  "$HOME/encode/app/current/venv/bin/bdencode" doctor --json
  ```

**Quick health check** (if the page does not open, this tells whether the program runs):

- on a server, inside: `curl --fail --silent http://127.0.0.1:8796/api/v1/health`
- on Windows, in PowerShell: `curl.exe --noproxy "*" http://127.0.0.1:8787/encoder/api/v1/health`
- on Swizzin, from outside (curl asks for the password): `curl --fail --silent --user USER https://your-domain.example/encoder/api/v1/health`

If the answer contains `"status":"ok"`, the program runs.

**Reporting a bug:** open an *issue* on the [GitHub page](https://github.com/accofil/bdencode-backend/issues). Describe what you did, what happened, which version runs (top of the menu), and paste the relevant part of the logs above. **Never send API keys, passwords or credential files.**

---

## 14. Uninstalling

- **On a server** (your jobs and finished films are kept):

  ```bash
  cd ~/bdencode-backend && bash install/uninstall.sh
  ```

  Removing the whole data folder and other options are covered in [chapter 12 of the reference](docs/REFERENCE.md#12-eltávolítás-linux-vagy-szerver-esetén) (Hungarian).
- **On Windows:** see [chapter 13 of the reference](docs/REFERENCE.md#13-eltávolítás-windows-esetén) (Hungarian).

Uninstalling never touches your original discs.

## 15. Privacy and security

- **What leaves the machine?** Only what you ask for: comparison images to the image host you set up (if enabled), a short technical summary for the AI adviser (if set up), and the daily release check against GitHub. The program sends no statistics or telemetry.
- **The web interface** is reachable on Windows only from your own PC, on a Debian server only through the SSH tunnel, on Swizzin with your Swizzin password. Never expose the internal port `8796` to the internet.
- **Keys** are stored encrypted with the machine's own systemd key in `~/.config/bdencode`.
- **Automatic updates** mean that a new release published in the GitHub repository is installed on your machine. If you do not want that, turn it off: `sudo systemctl disable --now bdencode-update.timer` (then you update by hand). Details: [chapter 11 of the reference](docs/REFERENCE.md#11-frissítés).
- **Your discs** are only read, never changed or deleted.

## 16. Glossary

| Term | Meaning |
|---|---|
| **BDMV** | the folder holding a Blu-ray disc's content |
| **Playlist** | a play list on the disc; one film version or episode |
| **Remux** | repacking the disc's tracks without encoding (the program works from it) |
| **x264 / x265** | the video encoders: x264 (AVC) for 1080p, x265 (HEVC) for UHD |
| **CRF** | the quality level; lower number = better quality and bigger file |
| **Preset** | how thorough the encoder is (`slow`, `slower`…); slower = more efficient but takes longer |
| **HDR10, Dolby Vision, HDR10+** | formats for the wider brightness and colour range of UHD |
| **Crop** | cutting the black bars off the picture's edges |
| **Comparison** | screenshot pairs of source and encode |
| **VMAF, SSIM, PSNR** | metrics that measure picture quality |
| **WSL2** | Windows' built-in Linux environment; BDEncode runs in it on Windows |
| **SSH** | encrypted remote login to a server |
| **SSH tunnel** | a secure path through an SSH connection to the server's internal web page |
| **tmux** | a program in which commands keep running after the connection drops |
| **sudo** | runs a command as administrator |
| **Swizzin** | a management system common on seedboxes, with web interfaces |

---

BDEncode is available under the MIT licence, see [LICENSE](LICENSE). The list of changes is in the `RELEASE_*.md` files of the [docs](docs) folder.
