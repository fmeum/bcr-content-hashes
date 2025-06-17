import json
import os
import re
import argparse

def find_source_json_urls(bcr_path):
    modules_dir = os.path.join(bcr_path, 'modules')
    github_archive_pattern = re.compile(
        r"^https://github\.com/[^/]+/[^/]+/archive/refs/tags/[^/]+\.(zip|tar\.gz)$"
    )
    extracted_urls = []

    if not os.path.isdir(modules_dir):
        print(f"Error: Directory not found: {modules_dir}")
        return []

    for root, _, files in os.walk(modules_dir):
        for file in files:
            if file == 'source.json':
                source_json_path = os.path.join(root, file)
                try:
                    with open(source_json_path, 'r') as f:
                        data = json.load(f)
                    url = data.get('url')
                    if url and github_archive_pattern.match(url):
                        extracted_urls.append(url)
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode JSON from {source_json_path}")
                except Exception as e:
                    print(f"Warning: Error processing {source_json_path}: {e}")
    return extracted_urls

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Finds GitHub archive URLs in source.json files from Bazel Central Registry.")
    parser.add_argument("bcr_path", help="Path to the checked-out bazel-central-registry repository")
    args = parser.parse_args()

    urls = find_source_json_urls(args.bcr_path)
    for url in urls:
        print(url)
