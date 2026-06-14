#!/usr/bin/env python3
import os
import sys
import json
import time
<<<<<<< Updated upstream
<<<<<<< Updated upstream
import tempfile
=======
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
import sqlite3
import urllib.request
import urllib.parse

# Standard NZBGet Extension Exit Codes
NZB_ACCEPT = 93
NZB_REJECT = 94

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "predb_cache.json")
CACHE_TTL_SECONDS = 86400  # 24 hours

# ---------------------------------------------------------------------------
# Local releaselist (srrdb "open" data dump)
# ---------------------------------------------------------------------------
# The local dump at https://www.srrdb.com/open/releaselist is a plaintext
# file of every known scene release (~10.6M entries / ~555 MB at last check).
# We mirror it locally and index it into a SQLite DB for O(log N) lookup.
#
# Layout next to main.py:
#   releaselist.txt          - the raw dump (one release per line)
#   releaselist.sqlite       - generated index (rebuilt automatically when
#                              the .txt mtime/size changes)
#
# Policy: the local index is a *positive* accelerator only. A local HIT
# short-circuits the live APIs. A local MISS (whether the dump is fresh or
# stale) does NOT cause rejection on its own — we always fall through to
# the live APIs, which keep their existing reject authority. This avoids
# the failure mode of rejecting brand-new releases that haven't been synced
# into the dump yet.
# ---------------------------------------------------------------------------
LOCAL_LIST_PATH = os.path.join(SCRIPT_DIR, "releaselist.txt")
LOCAL_DB_PATH = os.path.join(SCRIPT_DIR, "releaselist.sqlite")
LOCAL_STALE_HOURS = 168  # 7 days; only used to *warn* in logs, not to gate
LOCAL_BUILD_LOCK = os.path.join(SCRIPT_DIR, ".releaselist.building")


def log(level, message):
    print(f"[{level}] PreDB-Check: {message}")

<<<<<<< Updated upstream
<<<<<<< Updated upstream
# ---------------------------------------------------------------------------
# Cache (predb_cache.json)
# ---------------------------------------------------------------------------
def prune_cache(cache):
    """Remove entries older than CACHE_TTL_SECONDS to prevent unbounded growth."""
    now = time.time()
    return {k: v for k, v in cache.items() if now - v.get("ts", 0) < CACHE_TTL_SECONDS}

=======
=======
>>>>>>> Stashed changes

# ---------------------------------------------------------------------------
# Cache (predb_cache.json) — unchanged
# ---------------------------------------------------------------------------
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
def load_cache():
    """Load cached predb/srrdb results to avoid duplicate API calls."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
                return prune_cache(cache)
    except Exception:
        pass
    return {}

def save_cache(cache):
    try:
        dir_name = os.path.dirname(os.path.abspath(CACHE_FILE)) or "."
        with tempfile.NamedTemporaryFile(mode="w", dir=dir_name, delete=False) as f:
            json.dump(cache, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(f.name, CACHE_FILE)
    except Exception as e:
        log("WARNING", f"Failed to write cache file: {e}")

def get_cached_result(release_name):
    cache = load_cache()
    entry = cache.get(release_name.lower())
    if entry and (time.time() - entry.get("ts", 0) < CACHE_TTL_SECONDS):
        # Backwards compatibility: old entries may not have 'source'
        return entry.get("result"), entry.get("source", "unknown")
    return None, None

def set_cached_result(release_name, result, source="unknown"):
    cache = load_cache()
    cache[release_name.lower()] = {"result": result, "ts": time.time(), "source": source}
    save_cache(cache)


def mark_bad():
    """Print control command to tell NZBGet to mark this release as BAD."""
    print("[NZB] MARK=BAD")
    log("INFO", "Marked download as BAD in NZBGet queue.")


# ---------------------------------------------------------------------------
# Local releaselist index
# ---------------------------------------------------------------------------
def _local_db_needs_rebuild():
    """Return True if the .sqlite index is missing or out of date relative
    to the .txt source. Compares mtime + size (no need to re-hash)."""
    if not os.path.exists(LOCAL_DB_PATH):
        return True
    if not os.path.exists(LOCAL_LIST_PATH):
        return True
    txt_stat = os.stat(LOCAL_LIST_PATH)
    db_stat = os.stat(LOCAL_DB_PATH)
    # Rebuild if the source is newer OR larger (size catches the rare case
    # where the dump was overwritten with an older file at the same path).
    if txt_stat.st_mtime > db_stat.st_mtime:
        return True
    if txt_stat.st_size > db_stat.st_size:
        return True
    return False


def _build_local_db():
    """Build the SQLite index from the plaintext releaselist. ~16 seconds
    for 10.6M entries. Holds a lock file so concurrent invocations wait
    rather than duplicating work."""
    if os.path.exists(LOCAL_BUILD_LOCK):
        # Another process is already building. Wait briefly, then re-check.
        log("DETAIL", "Local index build already in progress, waiting...")
        for _ in range(60):  # up to ~5 minutes
            time.sleep(5)
            if not os.path.exists(LOCAL_BUILD_LOCK) and not _local_db_needs_rebuild():
                return
        log("WARNING", "Local index build still in progress after 5 min; skipping rebuild.")
        return

    try:
        with open(LOCAL_BUILD_LOCK, "w") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        log("WARNING", f"Cannot write build lock: {e}")
        return

    try:
        if not os.path.exists(LOCAL_LIST_PATH):
            log("WARNING", f"Local releaselist not found at {LOCAL_LIST_PATH}")
            return

        log("DETAIL", f"Building local releaselist index from {LOCAL_LIST_PATH}...")
        t0 = time.time()
        # Build to a temp file, then atomic-rename so a partial build never
        # leaves a corrupt .sqlite in place.
        tmp_db = LOCAL_DB_PATH + ".tmp"
        if os.path.exists(tmp_db):
            os.remove(tmp_db)

        con = sqlite3.connect(tmp_db)
        cur = con.cursor()
        cur.execute("PRAGMA journal_mode=OFF")
        cur.execute("PRAGMA synchronous=OFF")
        # Compound PK on (lowercase, original) for fast case-insensitive
        # exact-match lookups. WITHOUT ROWID saves ~30% space vs rowid table.
        cur.execute(
            "CREATE TABLE r (rel TEXT NOT NULL, rel_lc TEXT NOT NULL, "
            "PRIMARY KEY (rel_lc, rel)) WITHOUT ROWID"
        )

        BATCH = 50_000
        batch = []
        line_count = 0
        with open(LOCAL_LIST_PATH, "rb") as f:
            for line in f:
                # .rstrip(b'\n') and explicit decode — Windows CRLF safe
                raw = line.rstrip(b"\n")
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                if not raw:
                    continue
                try:
                    s = raw.decode("ascii")
                except UnicodeDecodeError:
                    # Skip non-ASCII garbage rather than abort the whole build
                    continue
                batch.append((s, s.lower()))
                line_count += 1
                if len(batch) >= BATCH:
                    cur.executemany("INSERT OR IGNORE INTO r VALUES (?, ?)", batch)
                    batch.clear()
            if batch:
                cur.executemany("INSERT OR IGNORE INTO r VALUES (?, ?)", batch)
        con.commit()
        con.close()

        # Preserve source mtime so subsequent _local_db_needs_rebuild() is
        # accurate even before the rename reflects in stat().
        os.utime(tmp_db, (os.stat(LOCAL_LIST_PATH).st_atime,
                          os.stat(LOCAL_LIST_PATH).st_mtime))
        os.replace(tmp_db, LOCAL_DB_PATH)
        elapsed = time.time() - t0
        log("INFO", f"Local index built: {line_count:,} entries in {elapsed:.1f}s")
    except Exception as e:
        log("WARNING", f"Local index build failed: {e}")
    finally:
        try:
            os.remove(LOCAL_BUILD_LOCK)
        except OSError:
            pass


def _open_local_db():
    """Return a read-only sqlite3 connection to the local index, or None
    if the file/table isn't available. Auto-rebuilds on first run or when
    the source .txt has changed."""
    if not os.path.exists(LOCAL_LIST_PATH):
        return None, None  # dump not yet downloaded
    if _local_db_needs_rebuild():
        _build_local_db()
    if not os.path.exists(LOCAL_DB_PATH):
        return None, None
    try:
        # Open read-only with a 2 GB mmap window — the db is ~1.3 GB so the
        # whole thing fits in the page cache and lookups are pure CPU.
        con = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True)
        con.execute("PRAGMA mmap_size=2147483648")
        con.execute("PRAGMA query_only=ON")
        return con, con.cursor()
    except Exception as e:
        log("WARNING", f"Cannot open local index: {e}")
        return None, None


def check_local(release_name, con, cur):
    """Look up release_name in the local SQLite index.

    Returns True if found, False if not found.
    Returns None if the local index is unavailable (no file, build failed,
    db corrupt, etc.) — caller should fall through to live APIs.
    """
    if con is None or cur is None:
        return None
    try:
        row = cur.execute(
            "SELECT 1 FROM r WHERE rel_lc = ? LIMIT 1",
            (release_name.lower(),),
        ).fetchone()
        return row is not None
    except Exception as e:
        log("WARNING", f"Local lookup error: {e}")
        return None


def get_local_index_age_hours():
    """Return the age of the local index in hours, or None if unavailable.
    Used only for informational logging."""
    try:
        if not os.path.exists(LOCAL_DB_PATH):
            return None
        return (time.time() - os.path.getmtime(LOCAL_DB_PATH)) / 3600.0
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Live APIs (unchanged)
# ---------------------------------------------------------------------------
def api_request(url, timeout=10, headers=None):
    """Generic HTTP GET request wrapper."""
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) NZBGet-PreDB-Check/2.0',
        'Accept': 'application/json'
    }
    if headers:
        default_headers.update(headers)
    req = urllib.request.Request(url, headers=default_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise Exception(f"HTTP request failed with status: {response.status}")
        try:
            data = json.loads(response.read().decode('utf-8'))
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response from {url}: {e}")
        return data

def check_srrdb(release_name):
    """Query srrDB API for exact release match.

    Returns True if found, False if not found.
    Raises exception on API/network error.
    """
    api_url = f"https://api.srrdb.com/v1/search/{urllib.parse.quote(release_name)}"
    res_data = api_request(api_url, timeout=10)

    results_count = res_data.get('resultsCount', 0)
    results = res_data.get('results', [])

    if results_count > 0 and len(results) > 0:
        exact_match = any(
            item.get('release', '').strip().lower() == release_name.strip().lower()
            for item in results
        )
        return exact_match
    return False

def check_predb_net(release_name):
    """Query predb.net API for exact release match.

    Returns True if found, False if not found.
    Raises exception on API/network error.
    """
    api_url = f"https://api.predb.net/?q={urllib.parse.quote(release_name)}"
    # predb.net sometimes blocks overly generic User-Agents; keep it clean
    res_data = api_request(
        api_url,
        timeout=10,
        headers={'User-Agent': 'NZBGet-PreDB-Check/2.0'}
    )

    results = res_data.get('results', 0)
    data = res_data.get('data', [])

    if results > 0 and data:
        exact_match = any(
            item.get('release', '').strip().lower() == release_name.strip().lower()
            for item in data
        )
        return exact_match
    return False

def test_api_connections():
    """Test connectivity to both APIs.
    Returns True if at least one API responds, False otherwise.
    Logs per-API status for NZBGet Messages panel.
    """
    srrdb_ok = False
    predb_ok = False

    # Test srrDB
    try:
        api_request("https://api.srrdb.com/v1/search/test", timeout=5)
        srrdb_ok = True
        log("INFO", "srrDB API connection: OK")
    except Exception as e:
        log("WARNING", f"srrDB API connection failed: {e}")

    # Test predb.net
    try:
        api_request(
            "https://api.predb.net/?q=test",
            timeout=5,
            headers={'User-Agent': 'NZBGet-PreDB-Check/2.0'}
        )
        predb_ok = True
        log("INFO", "predb.net API connection: OK")
    except Exception as e:
        log("WARNING", f"predb.net API connection failed: {e}")

    return srrdb_ok or predb_ok


def build_local_index_command():
    """Manually rebuild the local index from the current releaselist.txt."""
    if not os.path.exists(LOCAL_LIST_PATH):
        log("ERROR", f"No local releaselist at {LOCAL_LIST_PATH}. "
                     f"Download it from https://www.srrdb.com/open/releaselist first.")
        sys.exit(NZB_REJECT)
    # Force rebuild by deleting the .sqlite
    if os.path.exists(LOCAL_DB_PATH):
        os.remove(LOCAL_DB_PATH)
    _build_local_db()
    if os.path.exists(LOCAL_DB_PATH):
        log("INFO", f"Local index ready at {LOCAL_DB_PATH} "
                    f"({os.path.getsize(LOCAL_DB_PATH)/1024/1024:.0f} MB).")
        sys.exit(NZB_ACCEPT)
    log("ERROR", "Local index build failed; check NZBGet messages for details.")
    sys.exit(NZB_REJECT)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # 1. Check if executed as a custom UI test command
    command = os.environ.get('NZBCP_COMMAND')
    if command is not None:
        if command == 'TestConnection':
            log("INFO", "Testing communication with PreDB validation sources...")
            if test_api_connections():
                log("INFO", "At least one PreDB source is responding. Connection test passed.")
                sys.exit(NZB_ACCEPT)
            else:
                log("ERROR", "Both srrDB and predb.net are unreachable. Connection test failed.")
                sys.exit(NZB_REJECT)
        elif command == 'BuildLocalIndex':
            build_local_index_command()
        else:
            log("ERROR", f"Invalid environment command received: {command}")
            sys.exit(NZB_REJECT)

    # 2. Verify this is an event we care about
    event = os.environ.get('NZBNA_EVENT', '')
    if event != 'NZB_ADDED':
        log("DETAIL", f"Event type '{event}' is not handled. Skipping.")
        sys.exit(NZB_ACCEPT)

    # 3. Extract operational variables passed down by NZBGet (QUEUE uses NZBNA_ prefix)
    nzb_name = os.environ.get('NZBNA_NZBNAME')
    nzb_category = os.environ.get('NZBNA_CATEGORY', '')

    # Read environment variables mapped out from our manifest options
    target_category = os.environ.get('NZBPO_TARGETCATEGORY', '').strip()
    fail_open_raw = os.environ.get('NZBPO_FAILOPEN', 'true').lower()
    fail_open = fail_open_raw in ['yes', 'true', '1']

    if not nzb_name:
        log("DETAIL", "No active NZB name found in task context. Skipping.")
        sys.exit(NZB_ACCEPT)

    if nzb_name.lower().endswith('.nzb'):
        nzb_name = nzb_name[:-4]

    # 4. Assess category assignment filters
    if target_category and nzb_category.lower() != target_category.lower():
        log("DETAIL", f"Category '{nzb_category}' doesn't match target parameter '{target_category}'. Skipping check.")
        sys.exit(NZB_ACCEPT)

    # 5. Check cache before hitting APIs
    cached_result, cached_source = get_cached_result(nzb_name)
    if cached_result is not None:
        if cached_result:
            log("DETAIL", f"Cache HIT: '{nzb_name}' previously verified via {cached_source}. Accepting.")
            sys.exit(NZB_ACCEPT)
        else:
            log("DETAIL", f"Cache HIT: '{nzb_name}' previously REJECTED by {cached_source}. Marking BAD immediately.")
            mark_bad()
            sys.exit(NZB_REJECT)

    log("DETAIL", f"Verifying validation signature for: {nzb_name}")

    # 6. Local releaselist lookup (positive-only — see policy comment at top).
    #    On a HIT, we accept and never touch the network. On a MISS or
    #    unavailable, we fall through to the live APIs which keep their
    #    existing reject authority.
    local_con, local_cur = _open_local_db()
    if local_con is not None:
        local_result = check_local(nzb_name, local_con, local_cur)
        if local_result is True:
            age_h = get_local_index_age_hours()
            age_str = f" (index age {age_h:.1f}h)" if age_h is not None else ""
            set_cached_result(nzb_name, True, source="local")
            log("DETAIL", f"Local releaselist HIT{age_str}. Short-circuiting live APIs.")
            local_con.close()
            sys.exit(NZB_ACCEPT)
        elif local_result is False:
            log("DETAIL", "Local releaselist: no exact match. Falling through to live APIs.")
        else:
            log("DETAIL", "Local releaselist unavailable. Falling through to live APIs.")
        # Keep local_con open for the rest of the run? No — it's read-only
        # and only used for this single check, and we want to release the
        # fd. If multiple local lookups were common we'd cache the conn,
        # but in this script it's a one-shot per invocation.
        local_con.close()
    else:
        log("DETAIL", "Local releaselist not present. Falling through to live APIs.")

    # 7. Query srrDB API
    srrdb_explicit = None   # True = found, False = not found, None = error
    try:
        srrdb_found = check_srrdb(nzb_name)
        srrdb_explicit = srrdb_found
        if srrdb_found:
            set_cached_result(nzb_name, True, source="srrdb")
            log("DETAIL", "Success! Match found in srrDB. Proceeding with download.")
            sys.exit(NZB_ACCEPT)
        else:
            log("DETAIL", "srrDB: exact release not found.")
    except Exception as e:
        log("WARNING", f"srrDB API error: {e}")
        srrdb_explicit = None  # Mark as errored

    # 8. Fallback to predb.net API
    predb_explicit = None    # True = found, False = not found, None = error
    try:
        predb_found = check_predb_net(nzb_name)
        predb_explicit = predb_found
        if predb_found:
            set_cached_result(nzb_name, True, source="predb.net")
            log("DETAIL", "Success! Match found in predb.net. Proceeding with download.")
            sys.exit(NZB_ACCEPT)
        else:
            log("DETAIL", "predb.net: exact release not found.")
    except Exception as e:
        log("WARNING", f"predb.net API error: {e}")
        predb_explicit = None  # Mark as errored

    # 9. Decision logic
    # If at least one API explicitly said "not found", we trust that and reject.
    # fail_open only triggers when BOTH APIs encountered errors (unreachable).
    # Note: the local releaselist is intentionally NOT in this decision —
    # a local miss does not contribute to an explicit rejection.
    if srrdb_explicit is False or predb_explicit is False:
        rejecting_source = []
        if srrdb_explicit is False:
            rejecting_source.append("srrdb")
        if predb_explicit is False:
            rejecting_source.append("predb.net")
        source_str = " and ".join(rejecting_source)

        set_cached_result(nzb_name, False, source=source_str)
        log("DETAIL", f"REJECTED: Release not found in {source_str}.")
        mark_bad()
        sys.exit(NZB_REJECT)

    # Both APIs errored; apply fail_open logic
    if fail_open:
        log("DETAIL", "FailOpen safety trigger is active (both APIs down). Allowing task pipeline to bypass.")
        sys.exit(NZB_ACCEPT)
    else:
        log("DETAIL", "FailOpen parameter is disabled (both APIs down). Dropping download due to validation requirement rules.")
        mark_bad()
        sys.exit(NZB_REJECT)


if __name__ == "__main__":
    main()
