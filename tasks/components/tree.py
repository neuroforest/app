"""`tree.*` - one `.nf` tree: a directory, its git repository, its namespace.

A tree task is addressed by `--tree`: a path, or the tree's namespace token
(`root` for the empty one); without it, the tree the shell stands in. The
forest is `nf.*`, one module is `nfx.*`.

`tree.import` copies a legacy plugins root into a tree
(rules in `neuro.base.nf_import`). It always builds the copy in a scratch `.nf`
first and validates it there; `--dry-run` stops after printing the mapping and
how it differs from the destination - the drift report of the parallel period
- and without it the destination is made equal to the copy, provided nothing
blocked. No git: `tree.rebuild` replays the history.
"""
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import invoke

from neuro.base import nf_import, nf_repo, nf_split, nfx, plugins
from neuro.base.index import NfxIndex
from neuro.utils import terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import nf_common


def _import_namespace(builtin, dst, nid=""):
    """The declaration `tree.import` writes into `dst`: its nid and version kept
    when `dst` already has one (re-runs stay idempotent), else `nid` if given,
    else a fresh one. A `nid` contradicting the written one is refused."""
    parent = nfx.read(builtin / nfx.NAMESPACE_FILENAME)
    existing = dst / nfx.NAMESPACE_FILENAME
    if existing.is_file():
        old = nfx.read(existing)
        if nid and nid != old.nid:
            raise SystemExit(f"{terminal_style.FAIL} {existing} already declares nid {old.nid}, not {nid}")
        return nf_import.namespace_doc(old.nid, parent.nid, parent.version, old.version), False
    return nf_import.namespace_doc(nid or str(uuid.uuid4()), parent.nid, parent.version), not nid


@invoke.task(name="import", pre=[setup.env])
def import_(c, src, dst="~/.nf", nid="", dry_run=False):
    """Copy a legacy plugins root into a .nf tree; --dry-run prints the mapping and the drift only. --nid: namespace nid on first write."""
    src = Path(src).expanduser().resolve()
    dst = Path(dst).expanduser().resolve()
    builtin = Path(os.environ["APP_DIR"]).resolve() / plugins.NF_DIRNAME
    if not plugins.is_consolidated(dst):
        raise SystemExit(f"{terminal_style.FAIL} {dst}: the destination must be named {plugins.NF_DIRNAME}")
    namespace, minted = _import_namespace(builtin, dst, nid)
    mapping = nf_import.plan_import(src, namespace)
    issues = list(mapping.issues)

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / plugins.NF_DIRNAME
        staged.mkdir()
        nf_import.stage(mapping, staged)
        if not issues:
            issues += nf_import.verify(staged, src, builtin)
            idx = NfxIndex(builtin, staged)
            for m in mapping.modules:
                for failure in nf_repo.document_failures(idx, staged / m.rel):
                    issues.append(f"{m.rel}: {failure}")
    delta = nf_import.diff(mapping, dst)
    status = {rel: kind for kind, rels in delta.items() for rel in rels}

    rows = []
    for m in mapping.moves:
        shown = "(generated)" if m.src is None else str(m.src.relative_to(src))
        rows.append((status[m.rel], shown, str(m.rel), m.tag, m.note))
    rows += [("stale", "-", str(rel), "", "removed") for rel in delta["stale"]]
    print(f"{src} → {dst}")
    print(f"namespace {namespace.nid}{' (minted)' if minted else ''} · token ∅ · name {namespace.name} · "
          f"pins {namespace.dependencies[0][0]}@{namespace.dependencies[0][1]}\n")
    terminal_components.table(rows, header=("Status", "Source", "Destination", "Tag", "Note"))
    if mapping.skipped:
        print(f"\nnot copied: {', '.join(str(p.relative_to(src)) for p in mapping.skipped)}")
    counts = {k: len(v) for k, v in delta.items()}
    print(f"\n{len(mapping.modules)} modules · " + " · ".join(f"{n} {k}" for k, n in counts.items()))
    if issues:
        print(f"\n{terminal_style.FAIL} {len(issues)} problem(s) - nothing written:")
        for issue in issues:
            print(f"  {issue}")
        raise SystemExit(1)
    print(f"{terminal_style.SUCCESS} the copy validates: same modules, nids and versions, hashes and pins hold")
    if dry_run:
        return
    dst.mkdir(parents=True, exist_ok=True)
    nf_import.sync(mapping, dst)
    print(f"{terminal_style.SUCCESS} {dst} written")


@invoke.task(pre=[setup.env])
def rebuild(c, src, dst, nid="", verbose=False):
    """Build a new repo at --dst whose history is --src's, regrouped into release commits with annotated tags."""
    from neuro.base import nf_history

    src = Path(src).expanduser().resolve()
    dst = Path(dst).expanduser().resolve()
    builtin = Path(os.environ["APP_DIR"]).resolve() / plugins.NF_DIRNAME
    namespace, minted = _import_namespace(builtin, dst, nid)

    def progress(n, total):
        if n % 50 == 0 or n == total:
            print(f"  {n}/{total} events", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        report = nf_history.build(src, dst, namespace, Path(tmp), progress=progress)
        head = nf_import.plan_import(src, namespace)
    tag_issues = nf_history.check_tags(dst)
    head_issues = []

    def unversioned(content):
        """A module without its version and its pins' versions - what a replayed release may change."""
        doc = json.loads(content)
        doc.pop("version", None)
        doc["dependencies"] = sorted(str(d).partition("@")[0] for d in doc.get("dependencies") or [])
        return doc

    for m in head.moves:
        got = subprocess.run(["git", "-C", str(dst), "show", f"HEAD:{m.rel}"], capture_output=True).stdout
        if m.nid:
            # the replay releases changes the legacy repo left unreleased: versions and pins may be ahead
            if not got or unversioned(got) != unversioned(m.content):
                head_issues.append(f"{m.rel}: differs from the import of {src} beyond versions")
        elif got != m.content:
            head_issues.append(f"{m.rel}: differs from the import of {src}")
    listed = subprocess.run(["git", "-C", str(dst), "ls-tree", "-r", "--name-only", "HEAD"],
                            capture_output=True, text=True).stdout.split()
    head_issues += [f"{p}: in HEAD, not in the import" for p in sorted(set(listed) - {str(m.rel) for m in head.moves})]

    print(f"\n{src} → {dst}")
    print(f"namespace {namespace.nid}{' (minted)' if minted else ''}")
    print(f"{report.commits} legacy commits → {report.events} commits · "
          f"{report.legacy_tags} legacy tags → {report.tags - report.synthesized} annotated "
          f"+ {report.synthesized} synthesized for untagged versions")
    print(f"{report.bumped} release(s) written for changes the legacy repo made without one")
    print(f"{report.empty} empty event(s) dropped · {report.renamed} message(s) with module names rewritten to stems")
    print(f"{len(report.warnings)} historical warning(s){'' if verbose else ' (--verbose lists them)'}")
    if verbose:
        for w in report.warnings:
            print(f"  {w}")
    problems = [*report.fatal, *report.unmapped_tags, *tag_issues, *head_issues]
    for p in problems:
        print(f"  {terminal_style.FAIL} {p}")
    if problems:
        raise SystemExit(1)
    print(f"{terminal_style.SUCCESS} every tag names its module at its version; HEAD equals the import")


@invoke.task(pre=[setup.env])
def check(c, tree="", rev=""):
    """Pre-commit verdict on a tree's index (--rev: on that commit against its parent). Exits 1 on any issue."""
    repo = nf_common.repo(tree)
    verdict = repo.check(rev or None, others=plugins.effective_roots())
    what = f"{rev}" if rev else "the index"
    if verdict.issues:
        print(f"{terminal_style.FAIL} {terminal_style.BOLD}{what} refused{terminal_style.RESET} "
              f"({len(verdict.issues)} issue(s)):")
        for issue in verdict.issues:
            print(f"    {issue}")
        raise SystemExit(1)
    if verdict.checked or verdict.released:
        tail = f" · releases {', '.join(verdict.released)}" if verdict.released else ""
        print(f"{terminal_style.SUCCESS} {terminal_style.BOLD}validated{terminal_style.RESET} "
              f"{len(verdict.checked)} document(s){tail}")


@invoke.task(pre=[setup.env])
def tag(c, tree=""):
    """Post-commit: annotate HEAD with one tag per changed document whose version is untagged."""
    for name in nf_common.repo(tree).tag():
        print(f"  ⚑ tagged {name}")


@invoke.task(pre=[setup.env])
def order(c, tree=""):
    """The tree's uncommitted documents in dependency order (a diagnostic - one commit may hold them all)."""
    rows = nf_common.repo(tree).order(others=plugins.effective_roots())
    for i, (rel, name, version) in enumerate(rows, 1):
        print(f"{terminal_style.DIM}[{i}]{terminal_style.RESET} {rel}  {name}@{version}")


@invoke.task(pre=[setup.env])
def hooks(c, tree="", runner=""):
    """Install or refresh a tree's hooks: versioned shims in <tree>/.githooks/, a stub per hook where git runs it. --runner: the wrapper path (required the first time)."""
    repo = nf_common.repo(tree)
    runner = runner or repo.git("config", "--get", "nf.runner", check=False).strip()
    if not runner:
        raise SystemExit(f"{terminal_style.FAIL} --runner is required (e.g. /path/to/wrapper) - no default, "
                         f"so a hook never falls back to another line's code")
    try:
        wrote = repo.install(runner)
    except FileExistsError as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    for path in wrote:
        print(f"  wrote {path}")
    print(f"{terminal_style.SUCCESS} {repo.root}: hooks run from {repo.hooks_dir()} through `{runner}`"
          f"{'' if wrote else ' (already installed)'}")
    if any(Path(p).parent.name == nf_repo.SHIM_DIR for p in wrote):
        print(f"{terminal_style.DIM}the shims are versioned with the tree: commit {nf_repo.SHIM_DIR}/{terminal_style.RESET}")


@invoke.task(pre=[setup.env], help={
    "target": "Modules to spin off, comma-separated (stem, name, nid or path)",
    "to": "Where the new tree goes: a directory named .nf that does not exist yet",
    "token": "The new tree's namespace token",
    "name": "The new tree's name (default: the token)",
    "tree": "The tree to split (default: the one holding the first module)",
    "manifest": "A JSON file `{\"outputs\": [{token, to, modules, name?, description?}, …]}` for several new trees",
    "with-dependants": "Take the in-tree dependants of the named modules along",
    "dry-run": "Print the partition and stop",
    "swap": "Put the split staged in this directory in place",
    "no-test": "Skip `nfx.test` over the staged trees",
    "no-notify": "With --swap: do not run git's post-rewrite hook in the outputs",
    "rewrite-published": "Allow splitting a tree that has a remote (its clones and the remote must then be redone)",
})
def split(c, target="", to="", token="", name="", tree="", manifest="", with_dependants=False, dry_run=False,
          swap="", no_test=False, no_notify=False, rewrite_published=False):
    """Split a tree's repository: the named modules leave with their whole history for a tree of their own, and the original keeps none of it. Builds the parts beside the source and verifies them; --swap puts them in place. Pushes nothing."""
    if swap:
        try:
            state = nf_split.swap(Path(swap).expanduser(), notify=not no_notify)
        except nf_split.SplitRefused as e:
            nf_common.refused("swap", e.issues)
        print(f"{terminal_style.SUCCESS} swapped - the source is kept at {state['kept']}")
        for o in state["outputs"]:
            print(f"  {o['word']:<12} {o['to']}  ({o['head'][:7]})")
        print("\nNothing was pushed. To publish (the first rewrites what a remote already holds):")
        for n, o in enumerate(state["outputs"]):
            force = " --force" if n == 0 else ""
            print(f"  git -C {o['to']} push <remote> {state['branch']} --tags{force}")
            print(f"  git -C {o['to']} push <remote> {nf_split.NOTES_REF}{force}")
        print("\nList each new tree in PLUGINS where its modules are used.")
        return

    if manifest:
        parts = json.loads(Path(manifest).expanduser().read_text())["outputs"]
    else:
        if not (target and to):
            raise SystemExit(f"{terminal_style.FAIL} name the modules and --to (or pass --manifest)")
        parts = [{"token": token, "to": to, "name": name, "modules": [t for t in target.split(",") if t.strip()]}]
    for part in parts:
        part["modules"] = [nf_common.key(m) for m in part.get("modules", ())]
    first = next((m for part in parts for m in part["modules"]), None)
    repo = nf_common.repo(tree or (str(nf_common.owner_tree(first)) if first else ""))
    others = plugins.effective_roots()
    try:
        p = nf_split.plan(repo, parts, others, with_dependants, rewrite_published)
    except nf_split.SplitRefused as e:
        nf_common.refused("split", e.issues)

    print(f"source   {repo.root}  (token {p.token or '∅'}, {p.commits} commits)\n")
    rows = [(o.word, "continuation" if o.to is None else str(o.to), str(len(o.modules)), str(o.commits), str(o.tags))
            for o in p.outputs]
    terminal_components.table(rows, header=("Tree", "Goes to", "Modules", "Commits", "Tags"))
    print(f"\n{p.shared} source commit(s) become a commit in more than one tree")
    for o in p.outputs[1:]:
        print(f"\n{o.word}: {', '.join(sorted(p.stems[n][1] for n in o.modules))}")
    for o in p.outputs:
        for needed, pairs in o.needs.items():
            word = needed or "root"
            shown = ", ".join(pairs[:6]) + (f", … ({len(pairs)})" if len(pairs) > 6 else "")
            print(f"\n{o.word} pins namespace {word}: {shown}")
    if p.continuation.needs:
        print(f"\n{terminal_style.WARN} modules that stay depend on modules that leave: {p.continuation.word}'s "
              f"declaration is released as {p.continuation.namespace.version}, and the new tree must be present "
              f"wherever {p.continuation.word} is used")
    if dry_run:
        print("\ndry run - nothing written")
        return

    # `step` reports an exception and swallows it: what failed is read from what was left unset
    state = issues = refused = None
    with terminal_components.step(f"Building {len(p.outputs)} repositories in {p.staging}"):
        try:
            state = nf_split.build(p)
        except nf_split.SplitRefused as e:
            refused = e.issues
            raise
    if state is None:
        if refused:
            nf_common.refused("split", refused)
        raise SystemExit(1)
    with terminal_components.step("Verifying: nothing lost, nothing twice, every tag, sound heads"):
        issues = nf_split.verify(p.staging, others)
    if issues is None:
        raise SystemExit(f"{terminal_style.FAIL} the staged split in {p.staging} could not be verified")
    if not issues and not no_test:
        issues = nf_common.nfx_test([*repo._others(others, repo.root), *(o["dir"] for o in state["outputs"])])
    if issues:
        print(f"{terminal_style.FAIL} {terminal_style.BOLD}the staged split is not sound{terminal_style.RESET} "
              f"- left in {p.staging} to look at; nothing else was touched:")
        for issue in issues:
            print(f"    {issue}")
        raise SystemExit(1)
    print(f"\n{terminal_style.SUCCESS} staged in {p.staging} - the source is untouched")
    for o in state["outputs"]:
        print(f"  {o['word']:<12} {o['dir']}")
    print(f"\nLook, then:  tree.split --swap {p.staging}")
