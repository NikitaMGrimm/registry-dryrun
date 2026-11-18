"""For each open horizon-mods PR: #1148's check, as it will run after the cutover. Reads only; runs no submitted code.

Usage: check_prs.py <targets.json> <cutover sha> <out.json>
Run from a horizon-mods clone (origin = horizon-rust/horizon-mods) that has the cutover commit, with
cargo-horizon-mod on PATH and FILES_KEPT pointing at verified files of the live entries.
"""
import json
import os
import pathlib
import subprocess
import sys

targets, cutover, out_path = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
root = pathlib.Path.cwd()
tmp = pathlib.Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "prcheck"
tmp.mkdir(parents=True, exist_ok=True)


def sh(args, cwd=None, env=None):
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def first_error(text):
    lines = [l for l in text.splitlines() if l.strip()]
    for l in lines:
        if "error" in l.lower():
            return l.strip()
    return lines[-1].strip() if lines else ""


base_dir = tmp / "base"
if not base_dir.exists():
    sh(["git", "worktree", "add", "-q", "--detach", str(base_dir), cutover])
results = []
for t in targets:
    n = t["number"]
    r = {k: t[k] for k in ("number", "login", "review_author", "base", "title", "mods")}
    r["stages"] = []
    results.append(r)

    def stage(name, code, text):
        r["stages"].append({"stage": name, "ok": code == 0, "output": text[-4000:]})
        if code != 0 and "failed" not in r:
            r["failed"] = name
            r["error"] = first_error(text)
        return code == 0

    if t["base"] != "main":
        stage("base", 1, f"error: base branch is {t['base']}, not main; the check only runs on pull requests into main")
        continue
    code, text = sh(["git", "fetch", "-q", "origin", f"pull/{n}/head:pr{n}"])
    if not stage("fetch PR", code, text):
        continue
    head = tmp / f"pr{n}"
    sh(["git", "worktree", "remove", "--force", str(head)])
    sh(["git", "worktree", "add", "-q", "--detach", str(head), cutover])
    env = {**os.environ, "GIT_AUTHOR_NAME": "dryrun", "GIT_AUTHOR_EMAIL": "dryrun@example.invalid",
           "GIT_COMMITTER_NAME": "dryrun", "GIT_COMMITTER_EMAIL": "dryrun@example.invalid"}
    code, text = sh(["git", "merge", "--no-edit", "-q", f"pr{n}"], cwd=head, env=env)
    if code != 0:
        _, conflicts = sh(["git", "diff", "--name-only", "--diff-filter=U"], cwd=head)
        sh(["git", "merge", "--abort"], cwd=head)
        stage("merge into the cutover", 1, f"error: conflicts with the cutover in: {conflicts.replace(chr(10), ' ')}\n{text}")
        continue
    stage("merge into the cutover", 0, text)
    _, merged = sh(["git", "rev-parse", "HEAD"], cwd=head)
    kinds = []
    for m in t["mods"]:
        _, blob = sh(["git", "show", f"HEAD:{m}"], cwd=head)
        kind = next((l.split("=", 1)[1].strip().strip('"') for l in blob.splitlines() if l.startswith("kind")), "?")
        kinds.append(kind)
    r["kind"] = ",".join(kinds)
    code, text = sh(["git", "ls-tree", "-r", "HEAD"], cwd=head)
    bad = [l for l in text.splitlines() if l.split()[0] not in ("100644", "100755")]
    if not stage("only regular files", 1 if bad else 0, "error: not a regular file: " + "; ".join(bad) if bad else ""):
        continue
    owners = tmp / f"owners{n}.txt"
    review_base = tmp / f"review-base{n}"
    sh(["rm", "-rf", str(review_base)])
    code, text = sh([sys.executable, str(base_dir / "scripts/catalogue.py"), "review-base", str(base_dir), cutover,
                     str(head), merged, str(review_base), "--author-id", str(t["author_id"]),
                     "--unconfirmed-owners", str(owners)])
    if not stage("catalogue review-base", code, text):
        continue
    code, text = sh(["cargo", "horizon-mod", "registry", "review", str(review_base), str(head),
                     "--author", t["review_author"]])
    stage("registry review", code, text)
    code, text = sh(["bash", str(base_dir / "scripts/fetch.sh"), str(head)], cwd=root)
    if stage("download its files (sha256 checked)", code, text):
        code, text = sh(["cargo", "horizon-mod", "registry", "check", str(base_dir), str(head), "--files", "files"], cwd=root)
        stage("check each new file", code, text)
        code, text = sh(["cargo", "horizon-mod", "registry", "build", str(head), "--files", "files", "--out",
                         str(tmp / f"index{n}.json")], cwd=root)
        stage("index build", code, text)
    text = owners.read_text().strip() if owners.exists() else ""
    stage("owner of a reactivated archived id", 1 if text else 0, "error: owner not confirmed: " + text if text else "")
    r["ok"] = "failed" not in r
    print(n, "ok" if r["ok"] else f"FAIL {r['failed']}: {r['error'][:160]}", flush=True)
json.dump(results, open(out_path, "w"), indent=1)
