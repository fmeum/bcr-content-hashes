import argparse
import hashlib
import json
import os
import re
import time
import requests

# Basic retry mechanism
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 10 # More aggressive delay for faster testing; might need adjustment
REQUEST_TIMEOUT_SECONDS = 30

def transform_github_url_to_proxy_path(github_url):
    # Example: https://github.com/OWNER/REPO/archive/refs/tags/VERSION.zip
    # Becomes: github.com/OWNER/REPO/@v/VERSION.zip
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/archive/refs/tags/([^/]+)\.(zip|tar\.gz)", github_url)
    if not match:
        return None, None, None
    owner, repo, tag_with_ext = match.groups()[:3]

    # Remove .zip or .tar.gz from tag for .info file, but keep for .zip path
    tag_name = tag_with_ext
    if tag_with_ext.endswith(".zip"):
        tag_name = tag_with_ext[:-4]
    elif tag_with_ext.endswith(".tar.gz"):
        tag_name = tag_with_ext[:-7]

    module_path = f"github.com/{owner}/{repo}"
    archive_path_on_proxy = f"{module_path}/@v/{tag_with_ext}" # Includes .zip or .tar.gz
    info_file_version = tag_name # Version for .info file (without extension)

    return module_path, archive_path_on_proxy, info_file_version

def get_dirhash_from_proxy(github_url):
    module_path, archive_proxy_path, info_file_version = transform_github_url_to_proxy_path(github_url)
    if not archive_proxy_path:
        print(f"Error: Could not transform GitHub URL: {github_url}")
        return None

    proxy_archive_url = f"https://proxy.golang.org/{archive_proxy_path}"
    proxy_info_url = f"https://proxy.golang.org/{module_path}/@v/{info_file_version}.info"

    print(f"Processing URL: {github_url}")
    print(f"  -> Proxy archive URL: {proxy_archive_url}")
    print(f"  -> Proxy .info URL: {proxy_info_url}")

    # Step 1: Request archive to trigger caching and wait for it
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(proxy_archive_url, timeout=REQUEST_TIMEOUT_SECONDS)
            print(f"  Attempt {attempt + 1}/{MAX_RETRIES} to fetch archive {proxy_archive_url}: Status {response.status_code}")
            if response.status_code == 200:
                print(f"  Archive {proxy_archive_url} is cached.")
                break
            elif response.status_code == 404 or response.status_code == 410: # Gone means it won't appear
                 print(f"  Archive {proxy_archive_url} not found or gone (Status {response.status_code}). Skipping.")
                 return None
        except requests.exceptions.RequestException as e:
            print(f"  Attempt {attempt + 1}/{MAX_RETRIES} failed for {proxy_archive_url}: {e}")

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY_SECONDS)
        else:
            print(f"  Failed to cache archive {proxy_archive_url} after {MAX_RETRIES} attempts. Skipping.")
            return None

    # Step 2: Fetch .info file and extract DirHash
    # It's possible the .info file becomes available slightly after the archive. Add a small delay/retry.
    time.sleep(5) # Small delay before fetching .info
    for attempt in range(MAX_RETRIES):
        try:
            info_response = requests.get(proxy_info_url, timeout=REQUEST_TIMEOUT_SECONDS)
            print(f"  Attempt {attempt + 1}/{MAX_RETRIES} to fetch .info {proxy_info_url}: Status {info_response.status_code}")
            if info_response.status_code == 200:
                info_data = info_response.json()
                # The issue implies "dirhash" is available.
                # Go's .info files have 'Version', 'Time', and sometimes 'GoModPath'.
                # The actual "directory hash" used by Go is often called Sum or GoModSum for go.mod,
                # or ZipHash for the .zip.
                # For Bazel modules, this might be different. The term "dirhash" is specific.
                # Let's assume for now proxy.golang.org provides a 'DirHash' field in the .info response
                # or that this is a placeholder for a value we expect to find.
                # If not, Plan Step 7 (Refine dirhash fetching) will address this.
                dirhash = info_data.get("DirHash") # This is a hopeful assumption
                if not dirhash:
                    # Fallback or alternative: The .info file for a module version typically contains 'Version' and 'Time'.
                    # The hash of the module's .zip file itself is available at <proxy_url>/<module_path>/@v/<version>.ziphash
                    ziphash_url = f"https://proxy.golang.org/{module_path}/@v/{info_file_version}.ziphash"
                    print(f"  DirHash not found in .info. Attempting to fetch .ziphash from {ziphash_url}")
                    ziphash_response = requests.get(ziphash_url, timeout=REQUEST_TIMEOUT_SECONDS)
                    if ziphash_response.status_code == 200:
                        # The content of .ziphash is like "h1:<base64_encoded_sha256_hash_of_zip>"
                        dirhash = ziphash_response.text.strip()
                        print(f"  Successfully fetched .ziphash: {dirhash}")
                    else:
                        print(f"  Failed to fetch .ziphash (Status {ziphash_response.status_code}). No dirhash found for {github_url}")
                        return None

                if dirhash:
                    return dirhash
                else: # Should be caught by the ziphash failure above, but as a safeguard.
                    print(f"  No DirHash or ziphash found in .info response for {proxy_info_url}. Content: {info_data}")
                    return None

            elif info_response.status_code == 404 or info_response.status_code == 410:
                print(f"  .info file {proxy_info_url} not found or gone (Status {info_response.status_code}). Skipping.")
                return None

        except requests.exceptions.RequestException as e:
            print(f"  Attempt {attempt + 1}/{MAX_RETRIES} failed for {proxy_info_url}: {e}")
        except json.JSONDecodeError:
            print(f"  Could not decode JSON from {proxy_info_url}. Content: {info_response.text[:200]}...") # Print first 200 chars
            return None

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY_SECONDS)
        else:
            print(f"  Failed to fetch .info file {proxy_info_url} after {MAX_RETRIES} attempts. Skipping.")
            return None

    return None # Should not be reached if logic is correct

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetches dirhashes from proxy.golang.org for a list of GitHub archive URLs.")
    parser.add_argument("url_file", help="Path to a file containing one GitHub archive URL per line.")
    parser.add_argument("output_file", help="Path to save the results (SHA256_of_URL DIRHASH).")
    args = parser.parse_args()

    if not os.path.exists(args.url_file):
        print(f"Error: URL file not found: {args.url_file}")
        exit(1)

    with open(args.url_file, 'r') as f_urls, open(args.output_file, 'w') as f_out:
        for line in f_urls:
            github_url = line.strip()
            if not github_url:
                continue

            dirhash = get_dirhash_from_proxy(github_url)
            if dirhash:
                url_sha256 = hashlib.sha256(github_url.encode('utf-8')).hexdigest()
                f_out.write(f"{url_sha256} {dirhash}\n")
                print(f"Successfully processed {github_url}: SHA256({url_sha256}) -> DirHash/ZipHash({dirhash})")
            else:
                print(f"Failed to process {github_url}")
    print(f"Processing complete. Results saved to {args.output_file}")
