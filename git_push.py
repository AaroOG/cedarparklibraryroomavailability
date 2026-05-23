#!/usr/bin/env python3
import subprocess, sys, os
from pathlib import Path

REPO = Path(__file__).parent.resolve()
REMOTE_NAME = "origin"
DEFAULT_BRANCH = "main"

def run(cmd, check=True):
    result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error running {' '.join(cmd)}:\n{result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()

def main():
    if not (REPO / ".git").exists():
        print("Initialising git repository...")
        run(["git", "init"])
        run(["git", "checkout", "-b", DEFAULT_BRANCH])

    remotes = run(["git", "remote"], check=False)
    if not remotes:
        url = input("No remote found. Enter your GitHub repository URL (e.g. https://github.com/user/repo.git): ").strip()
        if not url:
            print("No remote URL provided. Aborting.")
            sys.exit(1)
        run(["git", "remote", "add", REMOTE_NAME, url])

    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not msg:
        msg = input("Commit message: ").strip()
    if not msg:
        msg = "Update room availability dashboard"

    run(["git", "add", "-A"])
    run(["git", "commit", "-m", msg])

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    run(["git", "push", "-u", REMOTE_NAME, branch])
    print(f"\nPushed to {REMOTE_NAME}/{branch}")

if __name__ == "__main__":
    main()
