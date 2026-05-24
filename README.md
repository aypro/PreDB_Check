# PreDB Check for NZBGet

An NZBGet **QUEUE** extension that validates queued NZB names against the [srrDB](https://srrdb.com) scene release database. Non-scene / P2P / fake releases are automatically marked as **BAD** in NZBGet, allowing *arr apps (Radarr, Sonarr, etc.) to blacklist them via Failed Download Handling.

## What it does

When an NZB is added to the queue, this script:
1. Checks if the release name exists on srrDB with an **exact match**
2. If it matches a verified scene release → the download proceeds normally
3. If it does **not** match → NZBGet receives `MARK=BAD`, Radarr/Sonarr sees the failure and blacklists the release

This keeps your library clean by rejecting P2P repacks, fake uploads, and non-scene releases before they finish downloading.

## Requirements

- NZBGet **v24+** (uses the modern Extension API)
- Python **3.x** on the NZBGet host
- Working internet connection for srrDB API calls

## Installation

### Manual

1. Copy `main.py` and `manifest.json` into your NZBGet `scripts` folder under a subdirectory, e.g.:
   ```
   /config/scripts/PreDB_Check/
   ```
   (On Unraid this maps to `/mnt/user/appdata/nzbget/scripts/PreDB_Check/`)

2. Make `main.py` executable:
   ```bash
   chmod +x main.py
   ```

3. Restart NZBGet so it rescans the `ScriptDir` and picks up the extension.

4. Go to **Settings** in NZBGet, find **PreDB_Check** in the extension list, enable it, and **save** the settings at least once.

### Extension Manager

This extension is not yet published in the official NZBGet Extension Manager repository.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| **Target Category** | `movies` | Only validate downloads in this category. Leave blank to process all categories. |
| **Fail Open on API Error** | `yes` | If srrDB is unreachable, `yes` allows the download; `no` blocks it. |

## How it works with Radarr / Sonarr

This extension uses the **QUEUE** kind with `NZB_ADDED` events, because:
- The NZB needs to be queued (and then marked BAD) for NZBGet to report a failure
- *arr apps only blacklist releases when they see a **Failed** status in the download client's history

### Important Radarr/Sonarr settings

Make sure Failed Download Handling is enabled:
- **Settings → Download Clients → Failed Download Handling** → ✅ Enable
- Check **Redownload** so it searches for a different release

## Caching

Results are cached locally in `predb_cache.json` for 24 hours. This prevents duplicate srrDB API calls when Radarr re-searches the same release.

## Logging

Watch the NZBGet **Messages** tab for output like:
```
[INFO] Executing queue-script PreDB_Check for Some.Release.2023.1080p.BluRay.x264-Scene
[DETAIL] PreDB-Check: Success! Match locked in srrDB. Proceeding with download.
```

Or on rejection:
```
[DETAIL] PreDB-Check: REJECTED: Release hash could not be matched against verified scene entries.
[INFO] PreDB-Check: Marked download as BAD in NZBGet queue.
```

## License

GPL

## Author

Aypro
