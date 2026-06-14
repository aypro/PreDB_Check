#!/usr/bin/env python3
import os
import sys
import json
import time
import tempfile
import urllib.request
import urllib.parse

# Standard NZBGet Extension Exit Codes
NZB_ACCEPT = 93
NZB_REJECT = 94

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "predb_cache.json")
CACHE_TTL_SECONDS = 86400  # 24 hours

def log(level, message):
    print(f"[{level}] PreDB-Check: {message}")

def prune_cache(cache):
    """Remove entries older than CACHE_TTL_SECONDS to prevent unbounded growth."""
    now = time.time()
    return {k: v for k, v in cache.items() if now - v.get("ts", 0) < CACHE_TTL_SECONDS}

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

    # 6. Query srrDB API
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

    # 7. Fallback to predb.net API
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

    # 8. Decision logic
    # If at least one API explicitly said "not found", we trust that and reject.
    # fail_open only triggers when BOTH APIs encountered errors (unreachable).
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
