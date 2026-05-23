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
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=sys.stdout, stderr=sys.stderr)
    proc.wait()
    if proc.returncode != 0:
        sys.exit(1)

def test_push(remote, branch):
    r = run(["git", "push", "--dry-run", "-u", remote, branch], check=False)
    return r.returncode == 0

def main():
    if not (REPO / ".git").exists():
        print("Initialising git repository...")
        run(["git", "init"])
        run(["git", "checkout", "-b", DEFAULT_BRANCH])

    remotes = run(["git", "remote"], check=False).stdout.strip()
    if not remotes:
        print("\nNo git remote configured.")
        print("Options:")
        print("  1) Use GitHub CLI (gh) — handles auth for you")
        print("  2) Enter a remote URL manually")
        choice = input("Choice [1/2]: ").strip()
        if choice != "2":
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
                run(["git", "remote", "add", REMOTE_NAME, info["sshUrl"]])
            else:
                print("Could not find a repo on GitHub. Create one first at https://github.com/new")
                url = input("Remote URL: ").strip()
                if not url:
                    print("Aborting.")
                    sys.exit(1)
                run(["git", "remote", "add", REMOTE_NAME, url])
        else:
            print("\nRemote URL formats:")
            print("  SSH:   git@github.com:your-username/repo-name.git")
            print("  HTTPS: https://github.com/your-username/repo-name.git")
            url = input("Remote URL: ").strip()
            if not url:
                print("Aborting.")
                sys.exit(1)
            run(["git", "remote", "add", REMOTE_NAME, url])

    remote_url = run(["git", "remote", "get-url", REMOTE_NAME], check=False).stdout.strip()
    print(f"\nRemote: {remote_url}")

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

    if not test_push(REMOTE_NAME, branch):
        print("\nPush failed — authentication issue.")
        print("Options:")
        print("  1) Use GitHub CLI:       gh auth login")
        print("  2) Use a personal access token (create one at https://github.com/settings/tokens)")
        print("  3) Set up SSH:           ssh-keygen && pbcopy < ~/.ssh/id_ed25519.pub")
        print("                            then add the key at https://github.com/settings/keys")
        choice = input("Choice [1/2/3]: ").strip()

        if choice == "1":
            os.system("gh auth login")
        elif choice == "2":
            token = input("Paste your GitHub personal access token: ").strip()
            if "@" not in remote_url:
                match = re.match(r"https://(?:[^@]+@)?(.+)", remote_url)
                if match:
                    authed_url = f"https://{token}@{match.group(1)}"
                    run(["git", "remote", "set-url", REMOTE_NAME, authed_url])
                    print("Remote URL updated with token.")
        elif choice == "3":
            key_path = os.path.expanduser("~/.ssh/id_ed25519.pub")
            if not os.path.exists(key_path):
                key_path = os.path.expanduser("~/.ssh/id_rsa.pub")
            if os.path.exists(key_path):
                with open(key_path) as f:
                    print(f"\nYour public key:\n{f.read().strip()}")
                print("Add it at https://github.com/settings/keys")
            else:
                print("Run: ssh-keygen -t ed25519 -C \"your@email.com\"")
                print("Then: pbcopy < ~/.ssh/id_ed25519.pub")
                print("And add the key at https://github.com/settings/keys")
            input("\nPress Enter after adding your key to GitHub...")

        if remote_url.startswith("https://"):
            ssh_url = re.sub(r"https://github\.com/", "git@github.com:", remote_url.split("@")[-1])
            if not ssh_url.endswith(".git"):
                ssh_url += ".git"
            run(["git", "remote", "set-url", REMOTE_NAME, ssh_url])
            print(f"Switched to SSH: {ssh_url}")

        print("Retrying push...")

    print(f"Pushing to {REMOTE_NAME}/{branch}...")
    stream(["git", "push", "-u", REMOTE_NAME, branch])

if __name__ == "__main__":
    main()