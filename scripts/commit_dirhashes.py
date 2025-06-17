import argparse
import os
import subprocess

def run_command(command):
    print(f"Executing: {' '.join(command)}")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        print(f"Error: {stderr.strip()}")
        return False, stdout.strip(), stderr.strip()
    print(stdout.strip())
    return True, stdout.strip(), stderr.strip()

def main(dirhashes_file_path, output_dir_name="dirhashes_output"):
    if not os.path.exists(dirhashes_file_path):
        print(f"Error: Dirhashes file not found: {dirhashes_file_path}")
        return

    # Create the output directory if it doesn't exist
    if not os.path.exists(output_dir_name):
        os.makedirs(output_dir_name)
        print(f"Created directory: {output_dir_name}")

    new_files_count = 0
    with open(dirhashes_file_path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                sha256_hash, dirhash_content = parts
                file_path = os.path.join(output_dir_name, sha256_hash)

                # Check if file already exists with the same content
                if os.path.exists(file_path):
                    with open(file_path, 'r') as existing_f:
                        if existing_f.read().strip() == dirhash_content.strip():
                            print(f"Skipping {file_path}, already exists with correct content.")
                            continue

                with open(file_path, 'w') as out_f:
                    out_f.write(dirhash_content + "\n") # Add newline for consistency
                print(f"Created/Updated file: {file_path}")
                new_files_count += 1
            else:
                print(f"Warning: Skipping malformed line: {line.strip()}")

    if new_files_count == 0:
        print("No new or updated dirhash files to commit based on script execution.")
        # Check for any changes in the output directory using git status
        success, stdout, _ = run_command(["git", "status", "--porcelain", output_dir_name])
        if success and stdout.strip():
             print(f"Found existing changes in {output_dir_name}. Proceeding to commit.")
        else:
            print("No changes to commit based on git status either. Exiting.")
            return


    # Git operations
    print("Configuring Git user...")
    run_command(["git", "config", "user.name", "github-actions[bot]"])
    run_command(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])

    print(f"Adding files in {output_dir_name} to Git...")
    run_command(["git", "add", output_dir_name])

    print("Committing changes...")
    commit_message = f"Update dirhashes from Bazel Central Registry ({new_files_count} files processed by script)"
    success, _, stderr_commit = run_command(["git", "commit", "-m", commit_message])

    if not success:
        print("Git commit failed.")
        # Check if it's because there are no changes to commit.
        # `git status --porcelain` would be empty if there are no changes after `git add`.
        # `git diff --staged --quiet` returns 0 if no staged changes.
        # If commit failed, and there were staged changes, it's a real error.
        # If commit failed, and there were NO staged changes (e.g. only `dirhashes_output` existed but was empty and `git add` did nothing)
        # then it's "nothing to commit".

        # Check if `git diff --staged --quiet` returns 0 (no staged changes)
        # This command returns exit code 0 if there are no staged changes, 1 if there are.
        staged_check_process = subprocess.run(["git", "diff", "--staged", "--quiet"])
        if staged_check_process.returncode == 0 : # No changes were staged
             print("No changes were staged for commit (e.g., all files were identical or .gitignore). Nothing to push.")
             return
        else: # Changes were staged, but commit still failed.
             print(f"Commit failed for other reasons: {stderr_commit}. Not pushing.")
             return

    print("Pushing changes to the remote repository...")
    success_branch, current_branch_raw, stderr_branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if not success_branch or not current_branch_raw.strip():
        current_branch = "main"
        print(f"Could not determine current branch (Error: {stderr_branch}). Defaulting to '{current_branch}'.")
    else:
        current_branch = current_branch_raw.strip()
        print(f"Determined current branch as '{current_branch}'.")


    push_success, _, stderr_push = run_command(["git", "push", "origin", current_branch])
    if not push_success:
        print(f"Git push failed: {stderr_push}")
    else:
        print("Commit and push process finished successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Creates files from dirhashes and commits them.")
    parser.add_argument("dirhashes_file", help="Path to the file containing SHA256_of_URL DIRHASH lines.")
    parser.add_argument("--output-dir", default="dirhashes_output", help="Directory to create the hash files in.")
    args = parser.parse_args()
    main(args.dirhashes_file, args.output_dir)
