# PreDB Check for NZBGet

An NZBGet **QUEUE** extension that validates queued NZB names against the [srrDB](https://srrdb.com) scene release database and falls back to [predb.net](https://predb.net). Non-scene / P2P / fake releases are automatically marked as **BAD** in NZBGet, allowing *arr apps (Radarr, Sonarr, etc.) to blacklist them via Failed Download Handling.

## What it does

When an NZB is added to the queue, this script:
1. Checks a **local srrDB releaselist index** (optional, but recommended) — one release per line, built into a local SQLite DB. A hit short-circuits everything and accepts.
2. If not found locally, queries **srrDB's live API** for an exact match.
3. If not found on srrDB, falls back to **predb.net** for an exact match.
4. If any source matches → the download proceeds normally.
5. If **no source matches** → NZBGet receives `MARK=BAD`, Radarr/Sonarr sees the failure and blacklists the release.

This keeps your library clean by rejecting P2P repacks, fake uploads, and non-scene releases before they finish downloading.

## Requirements

- NZBGet **v24+** (uses the modern Extension API)
- Python **3.x** on the NZBGet host
- Working internet connection for srrDB and predb.net API calls
- For the **local releaselist index**: ~2 GB of free disk (555 MB plaintext + ~1.3 GB SQLite). RAM cost is ~40 MB per script invocation (the connection is opened read-only with mmap).

## Installation

### Manual

1. Copy `main.py`, `manifest.json`, `refresh_releaselist.sh`, and `srrdb_releaselist_autosave.user.js` into your NZBGet `scripts` folder under a subdirectory, e.g.:
   ```
   /config/scripts/PreDB_Check/
   ```
   (On Unraid this maps to `/mnt/user/appdata/nzbget/scripts/PreDB_Check/`)

2. Make the scripts executable:
   ```bash
   chmod +x main.py refresh_releaselist.sh
   ```

3. Restart NZBGet so it rescans the `ScriptDir` and picks up the extension.

4. Go to **Settings** in NZBGet, find **PreDB_Check** in the extension list, enable it, and **save** the settings at least once.

### Extension Manager

This extension is not yet published in the official NZBGet Extension Manager repository.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| **Target Category** | `movies` | Only validate downloads in this category. Leave blank to process all categories. |
| **Fail Open on API Error** | `yes` | If **both** srrDB and predb.net are unreachable, `yes` allows the download; `no` blocks it. (The local index is unaffected by this setting — local misses never cause rejection.) |
| **Use Local Releaselist Index** | `yes` | Look up the release in the local SQLite index before hitting any API. Disabling this always uses live APIs. |
| **Local Releaselist Path** | _(empty)_ | Path to `releaselist.txt`. Blank means `<scriptdir>/releaselist.txt`. |

### Commands

- **Test srrDB Connection** — pings the live srrDB and predb.net APIs.
- **Build Local Releaselist Index** — rebuilds the SQLite index from `releaselist.txt`. ~16 s for 10.6M entries. You don't usually need to run this manually; the script rebuilds automatically when the `.txt` is newer than the `.sqlite`.

## Local releaselist (optional, but recommended)

### Why

The srrDB live API is fine for occasional lookups, but if you import a lot of NZBs (Radarr re-imports a season, Sonarr RSS syncs, etc.) you'll be making one HTTP call per file. The `https://www.srrdb.com/open/releaselist` endpoint exposes the same data as a single plaintext file (~555 MB, ~10.6M entries at last check). We mirror it locally and index it into SQLite for lookups at ~7 µs each — that's 30,000× faster than a network round trip, and it works fully offline.

### How to get the file

**This is the annoying part.** The `/open/releaselist` URL is gated by [Anubis](https://github.com/TecharoHQ/anubis), a JavaScript proof-of-work challenge. Plain `curl` / `urllib` cannot solve it — you'll just get back the challenge page instead of the data. srrDB's API docs explicitly say "Use but don't scrape" and point you at `/open` for bulk access; the catch is that bulk access still requires a real browser session.

**Recommended path: the Tampermonkey userscript.**

1. Install [Tampermonkey](https://www.tampermonkey.net/) (or Violentmonkey) in your daily browser.
2. Open the Tampermonkey dashboard, create a new script, paste in `srrdb_releaselist_autosave.user.js`.
3. Edit the script's settings and set `SAVE_DIR` to your NZBGet `PreDB_Check` directory (e.g. `/mnt/user/appdata/nzbget/scripts/PreDB_Check`).
4. Visit `https://www.srrdb.com/open/releaselist` in your browser. Anubis will run for ~5–15 s, then the userscript will save the file to `SAVE_DIR/releaselist.txt`.

After that, just revisit the page whenever you want to refresh (the data updates regularly on srrDB's side; weekly or monthly is plenty for most setups). The next NZB you add to NZBGet will detect the new file's mtime and rebuild the index automatically.

**Manual path: just download it in your browser once.**

1. Open `https://www.srrdb.com/open/releaselist` in your browser, pass the Anubis challenge if asked.
2. Right-click the page → "Save As..." → save as `releaselist.txt` in your PreDB_Check directory.
3. The script will index it on the next NZB addition.

**Headless path (not recommended).** `refresh_releaselist.sh` is provided for cron-driven refreshes, but it **will not work against a stock `https://www.srrdb.com/open/releaselist` URL** — Anubis will reject the request and the script will refuse to save the result. The script accepts a `--cookie-file` for users who have a way to extract a fresh Anubis cookie (which expires in ~30 min based on the `Set-Cookie` header), but maintaining that automatically is itself a scraping problem. Use the userscript unless you have a specific reason not to.

### Index lifecycle

- The script auto-builds the SQLite index on the **first** `NZB_ADDED` event after `releaselist.txt` is placed, and any subsequent time the `.txt` is updated (detected by mtime + size).
- The build takes ~16 seconds and uses ~1.3 GB on disk. It writes to a `.tmp` file and atomically renames, so a partial build never replaces a working index.
- A `predb_cache.json` (24 h TTL) is still used to cache **per-release** results so repeated lookups for the same name skip everything.

### Policy

The local index is a **positive** accelerator only:

- **Local hit** → accept immediately, never call any API.
- **Local miss** (file is fresh, stale, or missing) → fall through to the live APIs. The local list is *never* the cause of a rejection on its own.

This is deliberate: the local dump lags srrDB's live data, so a brand-new release that's in the live API but not yet in your local mirror should not be rejected just because the dump hasn't caught up.

## How it works with Radarr / Sonarr

This extension uses the **QUEUE** kind with `NZB_ADDED` events, because:
- The NZB needs to be queued (and then marked BAD) for NZBGet to report a failure
- *arr apps only blacklist releases when they see a **Failed** status in the download client's history

### Important Radarr/Sonarr settings

Make sure Failed Download Handling is enabled:
- **Settings → Download Clients → Failed Download Handling** → ✅ Enable
- Check **Redownload** so it searches for a different release

## Caching

Per-release results are cached locally in `predb_cache.json` for 24 hours. This prevents duplicate API calls when Radarr re-searches the same release, and it also short-circuits the local index for repeat lookups.

The SQLite index for the local releaselist is *not* a per-release cache — it's a long-lived structure rebuilt only when `releaselist.txt` changes.

## Logging

Watch the NZBGet **Messages** tab for output like:
```
[DETAIL] Verifying validation signature for: Some.Release.2023.1080p.BluRay.x264-Scene
[DETAIL] Local releaselist HIT (index age 36.2h). Short-circuiting live APIs.
```

Or on rejection:
```
[DETAIL] Local releaselist: no exact match. Falling through to live APIs.
[DETAIL] srrDB: exact release not found.
[DETAIL] predb.net: exact release not found.
[DETAIL] REJECTED: Release not found in srrdb and predb.net.
[INFO] Marked download as BAD in NZBGet queue.
```

## File layout

```
PreDB_Check/
├── main.py                                # the extension itself
├── manifest.json                          # NZBGet extension manifest
├── refresh_releaselist.sh                 # cron/manual refresher (see caveats)
├── srrdb_releaselist_autosave.user.js     # Tampermonkey userscript (recommended)
├── predb_cache.json                       # auto-generated per-release cache
├── releaselist.txt                        # the local dump (download manually)
└── releaselist.sqlite                     # auto-generated index (~1.3 GB)
```

## License

GPL

## Author

Aypro
