#!/usr/bin/env python3
import subprocess, sys, os, re
from pathlib import Path

REPO = Path(__file__).parent.resolve()
REMOTE_NAME = "origin"
DEFAULT_BRANCH = "main"

def run(cmd, check=True, silent=False):
    result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if check and result.returncode != 0:
        if not silent:
            print(f"Error running {' '.join(cmd)}:\n{result.stderr.strip()}")
        sys.exit(1)
    return result

def main():
    if not (REPO / ".git").exists():
        print("Initialising git repository...")
        run(["git", "init"])
        run(["git", "checkout", "-b", DEFAULT_BRANCH])

    remotes = run(["git", "remote"], check=False, silent=True).stdout.strip()
    if not remotes:
        print("\nNo git remote configured.")
        use_gh = input("Use GitHub CLI (gh) to authenticate? [Y/n]: ").strip().lower()
        if use_gh not in ("n", "no"):
            r = run(["gh", "auth", "status"], check=False, silent=True)
            if r.returncode != 0:
                print("You need to log in with GitHub CLI first:")
                os.system("gh auth login")
            result = run(["gh", "repo", "create", "--source=.", "--push", "--public"], check=False, silent=True)
            if result.returncode == 0:
                print("Repository created and pushed on first attempt.")
                return
            result = run(["gh", "repo", "view", "--json", "sshUrl"], check=False, silent=True)
            if result.returncode == 0:
                import json
                info = json.loads(result.stdout)
                ssh_url = info["sshUrl"]
                run(["git", "remote", "add", REMOTE_NAME, ssh_url])
                print(f"Remote set to {ssh_url}")
            else:
                print("\nCould not find a GitHub repository. Options:")
                print("  1. Create one at https://github.com/new and enter the URL below")
                print("  2. Use SSH: git@github.com:user/repo.git")
                print("  3. Use HTTPS with a personal access token: https://USER:TOKEN@github.com/user/repo.git")
                url = input("\nRemote URL: ").strip()
                if not url:
                    print("Aborting.")
                    sys.exit(1)
                run(["git", "remote", "add", REMOTE_NAME, url])
        else:
            url = input("Remote URL (use git@github.com:user/repo.git for SSH): ").strip()
            if not url:
                print("Aborting.")
                sys.exit(1)
            run(["git", "remote", "add", REMOTE_NAME, url])

    remote_url = run(["git", "remote", "get-url", REMOTE_NAME], check=False, silent=True).stdout.strip()
    if remote_url.startswith("https://") and "@" not in remote_url:
        print("\nWarning: HTTPS remote without credentials will fail.")
        print("GitHub no longer accepts password authentication over HTTPS.")
        print("\nOptions:")
        print("  1. Use SSH instead:   git remote set-url origin git@github.com:user/repo.git")
        print("  2. Use a personal access token:")
        print("     git remote set-url origin https://USERNAME:TOKEN@github.com/user/repo.git")
        print("     (Create a token at https://github.com/settings/tokens)")
        print("  3. Use GitHub CLI:     gh auth login && gh repo view")
        switch = input("\nSwitch to SSH now? [Y/n]: ").strip().lower()
        if switch not in ("n", "no"):
            ssh_url = re.sub(r"https://github\.com/", "git@github.com:", remote_url)
            ssh_url = re.sub(r"\.git$", "", ssh_url) + ".git"
            run(["git", "remote", "set-url", REMOTE_NAME, ssh_url])
            print(f"Remote updated to {ssh_url}")

    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not msg:
        msg = input("Commit message: ").strip()
    if not msg:
        msg = "Update room availability dashboard"

    run(["git", "add", "-A"])
    r = run(["git", "commit", "-m", msg], check=False, silent=True)
    if r.returncode != 0:
        if "nothing to commit" in r.stderr:
            print("Nothing to commit — working tree clean.")
        else:
            print(r.stderr)
        sys.exit(1)

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], silent=True).stdout.strip()
    r = run(["git", "push", "-u", REMOTE_NAME, branch], check=False, silent=True)
    if r.returncode != 0:
        print(f"Push failed:\n{r.stderr.strip()}")
        sys.exit(1)
    print(f"\nPushed to {REMOTE_NAME}/{branch}")

if __name__ == "__main__":
    main()