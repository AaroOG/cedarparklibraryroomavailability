#!/usr/bin/env python3
import subprocess, sys, os, re
from pathlib import Path

REPO = Path(__file__).parent.resolve()
REMOTE_NAME = "origin"
DEFAULT_BRANCH = "main"

def run(cmd, check=True):
    result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(result.stderr.strip())
        sys.exit(1)
    return result

def stream(cmd):
    """Run a command and stream its output live to the terminal."""
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=sys.stdout, stderr=sys.stderr)
    proc.wait()
    if proc.returncode != 0:
        sys.exit(1)

def main():
    if not (REPO / ".git").exists():
        print("Initialising git repository...")
        run(["git", "init"])
        run(["git", "checkout", "-b", DEFAULT_BRANCH])

    remotes = run(["git", "remote"], check=False).stdout.strip()
    if not remotes:
        print("\nNo git remote configured.")
        use_gh = input("Use GitHub CLI (gh) to authenticate? [Y/n]: ").strip().lower()
        if use_gh not in ("n", "no"):
            r = run(["gh", "auth", "status"], check=False)
            if r.returncode != 0:
                print("Logging in with GitHub CLI...")
                os.system("gh auth login")
            r = run(["gh", "repo", "create", "--source=.", "--push", "--public"], check=False)
            if r.returncode == 0:
                print("Repository created and pushed.")
                return
            r = run(["gh", "repo", "view", "--json", "sshUrl"], check=False)
            if r.returncode == 0:
                import json
                info = json.loads(r.stdout)
                ssh_url = info["sshUrl"]
                run(["git", "remote", "add", REMOTE_NAME, ssh_url])
                print(f"Remote set to {ssh_url}")
            else:
                print("Could not find a GitHub repository.")
                url = input("Remote URL: ").strip()
                if not url:
                    print("Aborting.")
                    sys.exit(1)
                run(["git", "remote", "add", REMOTE_NAME, url])
        else:
            url = input("Remote URL (git@github.com:user/repo.git for SSH): ").strip()
            if not url:
                print("Aborting.")
                sys.exit(1)
            run(["git", "remote", "add", REMOTE_NAME, url])

    remote_url = run(["git", "remote", "get-url", REMOTE_NAME], check=False).stdout.strip()
    print(f"\nRemote: {remote_url}")

    if remote_url.startswith("https://") and "@" not in remote_url:
        print("\nWarning: HTTPS without credentials will fail. Switching to SSH...")
        ssh_url = re.sub(r"https://github\.com/", "git@github.com:", remote_url)
        if not ssh_url.endswith(".git"):
            ssh_url += ".git"
        run(["git", "remote", "set-url", REMOTE_NAME, ssh_url])
        print(f"Remote updated to {ssh_url}")

    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not msg:
        msg = input("\nCommit message: ").strip()
    if not msg:
        msg = "Update room availability dashboard"

    run(["git", "add", "-A"])
    r = run(["git", "commit", "-m", msg], check=False)
    if r.returncode != 0:
        if "nothing to commit" in (r.stderr + r.stdout):
            print("Nothing to commit — working tree clean.")
        else:
            print(r.stderr)
        sys.exit(1)

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    print(f"Pushing to {REMOTE_NAME}/{branch}...")
    stream(["git", "push", "-u", REMOTE_NAME, branch])

if __name__ == "__main__":
    main()
