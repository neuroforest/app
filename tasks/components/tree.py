"""`tree.*` - one `.nf` tree: a directory, its git repository, its namespace.

A tree task is addressed by `--tree`: a path, or the tree's namespace token
(`root` for the empty one); without it, the tree the shell stands in. The
forest is `nf.*`, one module is `nfx.*`.

The trees of this machine are recorded in one file, `~/.config/neuroforest/trees.toml`
(`neuro.base.nf_trees`): `tree.init`, `tree.register`, `tree.move` and
`tree.split` write it, `tree.forget` drops a line, `nf.trees` shows it.

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

from neuro.base import nf_import, nf_repo, nf_split, nf_trees, nfx, plugins
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
    verdict = repo.check(rev or None, others=plugins.effective_trees())
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
    rows = nf_common.repo(tree).order(others=plugins.effective_trees())
    for i, (rel, name, version) in enumerate(rows, 1):
        print(f"{terminal_style.DIM}[{i}]{terminal_style.RESET} {rel}  {name}@{version}")


def _unjudged():
    """Say so where the machine has no global nf check: nothing then calls `tree.check` on a commit."""
    if nf_repo.global_check() is None:
        print(f"{terminal_style.WARN} no global nf check on this machine (an executable pre-commit.d/nf under the "
              f"global core.hooksPath) - commits to this tree are not judged")


def _register(root, replace=False):
    """Record the tree at `root` in the machine's registry and say so; a refusal is reported, not fatal."""
    try:
        t = nf_trees.register(root, replace)
    except nf_trees.RegistryError as e:
        print(f"{terminal_style.WARN} {root} not registered: {e}")
        return None
    print(f"{terminal_style.SUCCESS} registered {t.word:<10} {t.path}  ({t.nid[:8]})")
    return t


@invoke.task(pre=[setup.env], help={
    "to": "Where the tree goes: a directory named .nf that does not exist yet (or is empty)",
    "token": "Its namespace token (`root` for the empty one)",
    "name": "Its name (default: the token)",
    "description": "One line on what the tree holds",
    "pins": "Namespaces it may depend on besides the app's own, comma-separated tokens of trees on this machine",
    "no-commit": "Stop before the first commit",
})
def init(c, to, token, name="", description="", pins="", no_commit=False):
    """Make an empty tree: the directory, a repository, namespace.nfx with a fresh nid, a line in the registry. Inside a project's work tree the tree joins that repository."""
    root = Path(to).expanduser()
    words = [nf_common.tree_path(p.strip()) for p in pins.split(",") if p.strip()]
    try:
        pinned = [nf_trees.declared(r) for r in (Path(os.environ["APP_DIR"]).resolve() / plugins.NF_DIRNAME, *words)]
        doc = nf_trees.init(root, token, name, description, [(ns.nid, ns.version) for ns in pinned])
    except nf_trees.RegistryError as e:
        nf_common.refused("init", e.issues)
    repo = nf_common.repo(str(root))
    word = doc.namespace or "root"
    repo.track_notes()
    print(f"{terminal_style.SUCCESS} {repo.root}: namespace {word} ({doc.nid})")
    _unjudged()
    if repo.top != repo.root:
        print(f"{terminal_style.DIM}it is part of the repository {repo.top}{terminal_style.RESET}")
    if not no_commit:
        paths = [repo.show(nfx.NAMESPACE_FILENAME)]
        repo.git("add", "--", *paths)
        try:
            repo.git("commit", "-q", "-m", f"ADD: namespace {word}", "--", *paths)
        except RuntimeError as e:
            raise SystemExit(f"{terminal_style.FAIL} the first commit was refused; the tree is left as written:\n{e}")
        print(f"{terminal_style.SUCCESS} committed {repo.rev('HEAD')[:7]}")
    _register(repo.root)
    print(f"\nAdd @{word} to PLUGINS of each environment that uses it.")


@invoke.task(pre=[setup.env], help={
    "tree": "The tree to record: a path (default: the tree the shell stands in)",
    "replace": "Point the registry here although another checkout of this namespace is registered",
})
def register(c, tree="", replace=False):
    """Record a tree that arrived by clone (or by hand) in the machine's registry, and make its remotes fetch the origin notes."""
    repo = nf_common.repo(tree)
    try:
        t = nf_trees.register(repo.root, replace)
    except nf_trees.RegistryError as e:
        nf_common.refused("register", e.issues)
    print(f"{terminal_style.SUCCESS} registered {t.word}  {t.path}  ({t.nid})")
    for remote in repo.track_notes():
        print(f"  {remote} now fetches {nf_repo.NOTES_REF} - `git -C {repo.top} fetch {remote}` brings them")
    _unjudged()
    if repo.root not in plugins.effective_trees():
        print(f"{terminal_style.DIM}not in this environment's scope: add @{t.word} to PLUGINS to load it{terminal_style.RESET}")


@invoke.task(pre=[setup.env], help={"tree": "The line to drop: a path, a namespace token or a nid"})
def forget(c, tree):
    """Drop a tree's line from the machine's registry. Touches no directory; `tree.register` puts it back."""
    try:
        gone = nf_trees.forget(tree)
    except nf_trees.RegistryError as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    if gone is None:
        raise SystemExit(f"{terminal_style.FAIL} {tree}: no such tree in {nf_trees.registry_path()}")
    print(f"{terminal_style.SUCCESS} forgot {gone.word}  {gone.path}  ({gone.nid})")


@invoke.task(pre=[setup.env], help={
    "to": "The new location: a directory named .nf that does not exist yet",
    "tree": "The tree to move: a path or a namespace token (default: the tree the shell stands in)",
})
def move(c, to, tree=""):
    """Relocate a tree and rewrite its line in the registry. No commit: nothing inside the repository holds its own path."""
    old = nf_common.repo(tree).root
    try:
        t = nf_trees.move(old, to)
    except nf_trees.RegistryError as e:
        nf_common.refused("move", e.issues)
    print(f"{terminal_style.SUCCESS} moved {t.word}  {old} → {t.path}")
    stale = [entry for entry, path in plugins.scope()
             if not entry.startswith("@") and path is not None and path.resolve() == old]
    for entry in stale:
        print(f"{terminal_style.WARN} PLUGINS of this environment still names the old path ({entry}) - "
              f"write @{t.word} instead")
    print(f"{terminal_style.DIM}other environments and programs that name {old} by path need the same edit; "
          f"`@{t.word}` entries follow by themselves{terminal_style.RESET}")


@invoke.task(pre=[setup.env], help={
    "target": "Modules to spin off, comma-separated (stem, name, nid or path)",
    "to": "Where the new tree goes: a directory named .nf that does not exist yet",
    "token": "The new tree's namespace token",
    "name": "The new tree's name (default: the token)",
    "tree": "The tree to split (default: the one holding the first module)",
    "manifest": "A JSON file `{\"outputs\": [{token, to, modules, name?, description?, nid?, strip_prefix?, rename?, "
                "gone?}, …], \"rename\"?, \"events\"?}` for several new trees; `strip_prefix` / `rename: {module: stem}` "
                "rename modules throughout the new tree's history, `gone` lists the nids of deleted modules whose "
                "history goes along; the top-level `rename: {stem: stem}` does it in the tree that stays, and "
                "`events: false` leaves the split's event commits out",
    "with-dependants": "Take the in-tree dependants of the named modules along",
    "dry-run": "Print the partition and stop",
    "swap": "Put the split staged in this directory in place",
    "no-test": "Skip `nfx.test` over the staged trees",
    "no-notify": "With --swap: do not run git's post-rewrite hook in the outputs",
    "no-register": "With --swap: leave the machine's tree registry alone (scratch work)",
    "rewrite-published": "Allow splitting a tree that has a remote (its clones and the remote must then be redone)",
})
def split(c, target="", to="", token="", name="", tree="", manifest="", with_dependants=False, dry_run=False,
          swap="", no_test=False, no_notify=False, no_register=False, rewrite_published=False):
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
        if no_register:
            print("\nNot registered (--no-register): `tree.register --tree <path>` records a tree.")
            return
        print()
        for o in state["outputs"]:
            _register(o["to"])
        new = " · ".join(f"@{o['word']}" for o in state["outputs"][1:])
        print(f"\nAdd {new} to PLUGINS of each environment that uses those modules.")
        return

    kept_rename, events = None, True
    if manifest:
        doc = json.loads(Path(manifest).expanduser().read_text())
        parts, kept_rename, events = doc["outputs"], doc.get("rename"), doc.get("events", True)
    else:
        if not (target and to):
            raise SystemExit(f"{terminal_style.FAIL} name the modules and --to (or pass --manifest)")
        parts = [{"token": token, "to": to, "name": name, "modules": [t for t in target.split(",") if t.strip()]}]
    for part in parts:
        part["modules"] = [nf_common.key(m, tree) for m in part.get("modules", ())]
    first = next((m for part in parts for m in part["modules"]), None)
    repo = nf_common.repo(tree or (str(nf_common.owner_tree(first)) if first else ""))
    others = plugins.effective_trees()
    try:
        p = nf_split.plan(repo, parts, others, with_dependants, rewrite_published, rename=kept_rename, events=events)
    except nf_split.SplitRefused as e:
        nf_common.refused("split", e.issues)

    print(f"source   {repo.root}  (token {p.token or '∅'}, {p.commits} commits)\n")
    rows = [(o.word, "continuation" if o.to is None else str(o.to), str(len(o.modules)), str(o.commits), str(o.tags))
            for o in p.outputs]
    terminal_components.table(rows, header=("Tree", "Goes to", "Modules", "Commits", "Tags"))
    print(f"\n{p.shared} source commit(s) become a commit in more than one tree")
    for o in p.outputs:
        if o.to is not None:
            print(f"\n{o.word}: {', '.join(sorted(p.stems[n][1] for n in o.modules))}")
        elif p.renamed.get(o.token):
            print(f"\n{o.word}:")
        dead = sorted(nid for nid, t in p.gone.items() if t == o.token)
        if dead:
            print(f"{terminal_style.DIM}  takes the history of {len(dead)} deleted module(s): "
                  f"{', '.join(dead)}{terminal_style.RESET}")
        renamed = sorted(p.renamed.get(o.token, {}).items())
        if renamed:
            print(f"{terminal_style.DIM}  renamed throughout its history ({len(renamed)}): "
                  f"{', '.join(f'{old} → {new}' for old, new in renamed)}{terminal_style.RESET}")
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
