#!/usr/bin/env python3
import os
import sys
import json
import time
import urllib.request
import urllib.parse

# Standard NZBGet Extension Exit Codes
NZB_ACCEPT = 93
NZB_REJECT = 94

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "predb_cache.json")
CACHE_TTL_SECONDS = 86400  # 24 hours

def log(level, message):
    print(f"[{level}] PreDB-Check: {message}")

def load_cache():
    """Load cached srrDB results to avoid duplicate API calls."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        log("WARNING", f"Failed to write cache file: {e}")

def get_cached_result(release_name):
    cache = load_cache()
    entry = cache.get(release_name.lower())
    if entry and (time.time() - entry.get("ts", 0) < CACHE_TTL_SECONDS):
        return entry.get("result")
    return None

def set_cached_result(release_name, result):
    cache = load_cache()
    cache[release_name.lower()] = {"result": result, "ts": time.time()}
    save_cache(cache)

def mark_bad():
    """Print control command to tell NZBGet to mark this release as BAD."""
    print("[NZB] MARK=BAD")
    log("INFO", "Marked download as BAD in NZBGet queue.")

def main():
    # 1. Check if executed as a custom UI test command
    command = os.environ.get('NZBCP_COMMAND')
    if command is not None:
        if command == 'TestConnection':
            log("INFO", "Testing communication with srrDB API...")
            try:
                req = urllib.request.Request(
                    "https://api.srrdb.com/v1/search/Gladiator", 
                    headers={'User-Agent': 'NZBGet-PreDB-Check/2.0'}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        log("INFO", "Connection successful! srrDB API is responding normally.")
                        sys.exit(NZB_ACCEPT)
            except Exception as e:
                log("ERROR", f"Connection failed: {e}")
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

    # 5. Check cache before hitting srrDB API
    cached = get_cached_result(nzb_name)
    if cached is not None:
        if cached:
            log("DETAIL", f"Cache HIT: '{nzb_name}' previously verified scene. Accepting.")
            sys.exit(NZB_ACCEPT)
        else:
            log("DETAIL", f"Cache HIT: '{nzb_name}' previously REJECTED. Marking BAD immediately.")
            mark_bad()
            sys.exit(NZB_REJECT)

    log("DETAIL", f"Verifying validation signature via srrDB for: {nzb_name}")

    # 6. JSON Payload API request execution
    api_url = f"https://api.srrdb.com/v1/search/{urllib.parse.quote(nzb_name)}"
    req = urllib.request.Request(
        api_url, 
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) NZBGet-PreDB-Check/2.0',
            'Accept': 'application/json'
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                raise Exception(f"HTTP Status code tracking failed: {response.status}")
                
            res_data = json.loads(response.read().decode('utf-8'))
            results_count = res_data.get('resultsCount', 0)
            results = res_data.get('results', [])
            
            if results_count > 0 and len(results) > 0:
                exact_match = any(item.get('release', '').lower() == nzb_name.lower() for item in results)
                
                if exact_match:
                    set_cached_result(nzb_name, True)
                    log("DETAIL", "Success! Match locked in srrDB. Proceeding with download.")
                    sys.exit(NZB_ACCEPT)
                else:
                    set_cached_result(nzb_name, False)
                    log("DETAIL", "REJECTED: Loose results surfaced, but exact scene signature verification failed.")
                    mark_bad()
                    sys.exit(NZB_REJECT)
            else:
                set_cached_result(nzb_name, False)
                log("DETAIL", "REJECTED: Release hash could not be matched against verified scene entries.")
                mark_bad()
                sys.exit(NZB_REJECT)

    except Exception as e:
        log("WARNING", f"srrDB API Gateway timeout or validation error: {e}")
        if fail_open:
            log("DETAIL", "FailOpen safety trigger is active. Allowing task pipeline to bypass.")
            sys.exit(NZB_ACCEPT)
        else:
            log("DETAIL", "FailOpen parameter is disabled. Dropping download due to validation requirement rules.")
            mark_bad()
            sys.exit(NZB_REJECT)

if __name__ == "__main__":
    main()
