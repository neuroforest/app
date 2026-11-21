"""`invoke nf.*` - the `.nf` roots an environment reads.

A root is opted in by listing it in `PLUGINS` of the environment, nothing
else; `nf.namespaces` shows what that list comes to on this machine - the
namespace token each root declares (a dim `·` is the
written empty token, a legacy root has none), how many modules it contributes,
its absolute path, and any listed entry that is absent.

`nf.import` copies a legacy plugins root into a `.nf` root
(rules in `neuro.base.nf_import`). It always builds the
copy in a scratch `.nf` first and validates it there; `--dry-run` stops after
printing the mapping and how it differs from the destination - the drift
report of the parallel period - and without it the destination is made equal
to the copy, provided nothing blocked. No git: that is C2.
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
from neuro.utils import internal_utils, terminal_components, terminal_style

from tasks.actions import setup


ROOT_MARK = f"{terminal_style.DIM}·{terminal_style.RESET}"

# The environment the wrapper started this process with, before any `setup.env`
# loaded a config into it: what a child run in another ENV must start from, or
# it would inherit this one's base and roots.
_STARTED_WITH = dict(os.environ)


def namespace_label(idx, root):
    """The token column for `root`: the declared token, a dim `·` for the
    written empty token (the root namespace, `~/.nf`), `-` for a legacy root,
    a warning for a `.nf` root that has not declared one yet."""
    ns = idx.namespace_of(root)
    if ns is not None:
        return ns.token or ROOT_MARK
    return f"{terminal_style.WARN} none" if plugins.is_consolidated(root) else "-"


@invoke.task(pre=[setup.env])
def namespaces(c):
    """List the namespaces in effect: token, module count, absolute root path.
    A `PLUGINS` entry absent on this machine is skipped by every task; it is named here."""
    present = plugins.effective_roots()
    idx = NfxIndex(*present)
    counts = {}
    for entry in idx.entries():
        counts[entry.registry_root] = counts.get(entry.registry_root, 0) + 1
    rows = [(namespace_label(idx, root), str(counts.get(root, 0)), str(Path(root).resolve()))
            for root in present]
    terminal_components.table(rows, header=("Namespace", "Modules", "Path"))
    for p in internal_utils.missing_path_list("PLUGINS"):
        print(f"{terminal_style.WARN} {p} is listed in PLUGINS but absent - skipped, not fatal")


def _import_namespace(builtin, dst, nid=""):
    """The declaration `nf.import` writes into `dst`: its nid and version kept
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
    """Copy a legacy plugins root into a .nf root; --dry-run prints the mapping and the drift only. --nid: namespace nid on first write."""
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
def history(c, src, dst, nid="", verbose=False):
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
    tree_issues = []
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
                tree_issues.append(f"{m.rel}: differs from the import of {src} beyond versions")
        elif got != m.content:
            tree_issues.append(f"{m.rel}: differs from the import of {src}")
    listed = subprocess.run(["git", "-C", str(dst), "ls-tree", "-r", "--name-only", "HEAD"],
                            capture_output=True, text=True).stdout.split()
    tree_issues += [f"{p}: in HEAD, not in the import" for p in sorted(set(listed) - {str(m.rel) for m in head.moves})]

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
    problems = [*report.fatal, *report.unmapped_tags, *tag_issues, *tree_issues]
    for p in problems:
        print(f"  {terminal_style.FAIL} {p}")
    if problems:
        raise SystemExit(1)
    print(f"{terminal_style.SUCCESS} every tag names its module at its version; HEAD equals the import")


def _repo(root):
    try:
        return nf_repo.Repo(Path(root).expanduser() if root else _caller_root())
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")


@invoke.task(pre=[setup.env])
def check(c, root="", rev=""):
    """Pre-commit verdict on a .nf root's index (--rev: on that commit against its parent). Exits 1 on any issue."""
    repo = _repo(root)
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
def tag(c, root=""):
    """Post-commit: annotate HEAD with one tag per changed document whose version is untagged."""
    for name in _repo(root).tag():
        print(f"  ⚑ tagged {name}")


@invoke.task(pre=[setup.env])
def order(c, root=""):
    """The root's uncommitted documents in dependency order (a diagnostic - one commit may hold them all)."""
    rows = _repo(root).order(others=plugins.effective_roots())
    for i, (rel, name, version) in enumerate(rows, 1):
        print(f"{terminal_style.DIM}[{i}]{terminal_style.RESET} {rel}  {name}@{version}")


def _key(target):
    """A module is named by stem, name or nid - and a file path
    (`knowledge/stains.nfx`, absolute or not) names the module of that stem."""
    target = target.strip()
    return Path(target).stem if target.endswith(".nfx") else target


def _caller_root():
    """The .nf root the task was called from. `setup.env` changes into APP_DIR,
    but the shell's `PWD` still names where the caller stood; the root is that
    directory or the nearest parent holding a namespace declaration."""
    here = Path(os.environ.get("PWD") or ".").expanduser()
    for d in (here, *here.parents):
        if (d / nfx.NAMESPACE_FILENAME).is_file():
            return d
    raise SystemExit(f"{terminal_style.FAIL} {here}: not inside a .nf root - pass --root")


def _owner_root(key):
    """The root among PLUGINS that holds the document `key` names."""
    roots = plugins.effective_roots()
    path = NfxIndex(*roots).resolve(key)
    root = path and plugins.registry_root_of(path, roots)
    if root is None:
        raise SystemExit(f"{terminal_style.FAIL} {key}: in none of the PLUGINS roots - pass --root")
    return root


def _test_gate(repo, roots):
    """The gate of a release: `nfx.test` over the documents about to
    be committed, run as a child in ENV=TESTING - its base is wiped, so it must
    never be this process's - reading this release's roots, not TESTING's."""
    roots = [*repo._others(roots, repo.root), repo.root]

    def gate(paths):
        return _nfx_test(roots, paths, lambda path: repo.show(Path(path).relative_to(repo.root)))

    return gate


def _nfx_test(roots, paths=None, show=str):
    """Run `nfx.test` as a child in ENV=TESTING over `roots` (`paths`: only
    these documents) and return its failures as issue lines. The child starts
    from the wrapper's own environment, so the base it wipes is the test one."""
    env = {k: v for k, v in _STARTED_WITH.items() if k not in ("NF_CONFIG", "NF_DATA", "NF_STATE", "NF_CACHE")}
    env["ENV"] = "TESTING"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "records.json"
        target = ["--target", ",".join(str(p) for p in paths)] if paths else []
        what = f"{len(paths)} document(s)" if paths else "every document"
        with terminal_components.step(f"Testing {what} in the test base"):
            r = subprocess.run(
                [os.path.join(setup.get_nenv_dir(), "bin", "invoke"), f"--search-root={os.environ['APP_DIR']}",
                 "nfx.test", *target, "--roots", ":".join(str(p) for p in roots), "--out", str(out)],
                env=env, capture_output=True, text=True)
        if not out.is_file():
            tail = (r.stdout + r.stderr).strip().splitlines()[-8:]
            return ["the tests could not run (--no-test skips them):", *tail]
        issues = []
        for record in json.loads(out.read_text()):
            where = show(record["path"])
            for failure in record["failures"]:
                lines = failure.splitlines() or [""]
                issues.append(f"{where}: {lines[0]}")
                issues += [f"    {line}" for line in lines[1:]]
        return issues


@invoke.task(pre=[setup.env], help={
    "no-test": "Skip `nfx.test` on the release (schema, values, validator tests in the test base)",
})
def release(c, target, root="", major=False, dry_run=False, message="", no_test=False):
    """Release documents (comma-separated) with their in-root dependants: re-pin, bump, one commit, one tag each. An edited validators or test file of a released module goes into the same commit. The release is tested first (`nfx.test`) and refused on a failure."""
    targets = [_key(t) for t in target.split(",") if t.strip()]
    repo = _repo(root or _owner_root(targets[0]))
    others = plugins.effective_roots()
    try:
        steps = repo.plan_release(targets, major, others) if dry_run else None
        if not dry_run:
            sha, steps, tags = repo.release(targets, major, others, message or None,
                                            gate=None if no_test else _test_gate(repo, others))
    except ValueError as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    except nf_repo.ReleaseRefused as e:
        print(f"{terminal_style.FAIL} {terminal_style.BOLD}release refused{terminal_style.RESET} - nothing written:")
        for issue in e.issues:
            print(f"    {issue}")
        raise SystemExit(1)
    rows = [("●" if s.seed else "↳", str(s.rel), f"{s.old} → {s.new}", ", ".join(s.repins),
             "unreleased edits" if s.carries else "") for s in steps]
    terminal_components.table(rows, header=("", "Document", "Version", "Re-pins", "Also carries"))
    if dry_run:
        print(f"\n{len(steps)} document(s) would be released - dry run, nothing written")
        return
    print(f"\n{terminal_style.SUCCESS} {sha[:7]} released {len(steps)} document(s) · {len(tags)} tag(s)")


@invoke.task(pre=[setup.env])
def rename(c, target, new, root="", dry_run=False):
    """Rename a module inside its root: files, name, test path and tags in one `REFACTOR:` commit - a release like any change: next version, dependants re-pinned."""
    target = _key(target)
    repo = _repo(root or _owner_root(target))
    try:
        plan = repo.plan_rename(target, new)
        if not dry_run:
            sha, plan = repo.rename(target, new, plugins.effective_roots())
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    except nf_repo.ReleaseRefused as e:
        print(f"{terminal_style.FAIL} {terminal_style.BOLD}rename refused{terminal_style.RESET} - nothing written:")
        for issue in e.issues:
            print(f"    {issue}")
        raise SystemExit(1)
    rows = [(repo.show(a), repo.show(b)) for a, b in plan.files] + list(plan.tags)
    terminal_components.table(rows, header=("From", "To"))
    if dry_run:
        print(f"\n{plan.event.subject} - dry run, nothing written")
        return
    print(f"\n{terminal_style.SUCCESS} {sha[:7]} {plan.event.subject} · {len(plan.tags)} tag(s) moved")
    print(f"{terminal_style.DIM}pushed already? the remote still has the old tags: "
          f"git push <remote> {' '.join(f':refs/tags/{a}' for a, _ in plan.tags)} "
          f"{' '.join(f'refs/tags/{b}' for _, b in plan.tags)}{terminal_style.RESET}")


@invoke.task(name="move", pre=[setup.env])
def move_(c, target, to, root="", with_dependants=False, as_="", dry_run=False):
    """Move a module into another .nf root: one `MIGRATE:` commit at each end, history left where it was."""
    target = _key(target)
    source = _repo(root or _owner_root(target))
    dest = _repo(to)
    others = plugins.effective_roots()
    try:
        if dry_run:
            plan = nf_repo.plan_move(source, dest, target, with_dependants, as_, others)
        else:
            plan, departed, arrived = nf_repo.move(source, dest, target, with_dependants, as_, others)
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    except nf_repo.ReleaseRefused as e:
        print(f"{terminal_style.FAIL} {terminal_style.BOLD}move refused{terminal_style.RESET} - nothing written:")
        for issue in e.issues:
            print(f"    {issue}")
        raise SystemExit(1)
    rows = [(source.show(a), dest.show(b), item.version, item.released or "never released")
            for item in plan.items for a, b in item.files]
    terminal_components.table(rows, header=("From", "To", "Version", "Released as"))
    if dry_run:
        print(f"\n{plan.departure_message.splitlines()[0]} - dry run, nothing written")
        return
    print(f"\n{terminal_style.SUCCESS} {source.root}: {departed[:7]} {plan.departure_message.splitlines()[0]}")
    print(f"{terminal_style.SUCCESS} {dest.root}: {arrived[:7]} {plan.arrival_message.splitlines()[0]}")


@invoke.task(pre=[setup.env], help={
    "target": "Modules to spin off, comma-separated (stem, name, nid or path)",
    "to": "Where the new root goes: a directory named .nf that does not exist yet",
    "token": "The new root's namespace token",
    "name": "The new root's name (default: the token)",
    "manifest": "A JSON file `{\"outputs\": [{token, to, modules, name?, description?}, …]}` for several new roots",
    "with-dependants": "Take the in-root dependants of the named modules along",
    "dry-run": "Print the partition and stop",
    "swap": "Put the split staged in this directory in place",
    "no-test": "Skip `nfx.test` over the staged roots",
    "no-notify": "With --swap: do not run git's post-rewrite hook in the outputs",
    "rewrite-published": "Allow splitting a root that has a remote (its clones and the remote must then be redone)",
})
def split(c, target="", to="", token="", name="", root="", manifest="", with_dependants=False, dry_run=False,
          swap="", no_test=False, no_notify=False, rewrite_published=False):
    """Split a .nf root's repository: the named modules leave with their whole history for a root of their own, and the original keeps none of it. Builds the parts beside the source and verifies them; --swap puts them in place. Pushes nothing."""
    if swap:
        try:
            state = nf_split.swap(Path(swap).expanduser(), notify=not no_notify)
        except nf_split.SplitRefused as e:
            _refused("swap", e.issues)
        print(f"{terminal_style.SUCCESS} swapped - the source is kept at {state['kept']}")
        for o in state["outputs"]:
            print(f"  {o['word']:<12} {o['to']}  ({o['head'][:7]})")
        print("\nNothing was pushed. To publish (the first rewrites what a remote already holds):")
        for n, o in enumerate(state["outputs"]):
            force = " --force" if n == 0 else ""
            print(f"  git -C {o['to']} push <remote> {state['branch']} --tags{force}")
            print(f"  git -C {o['to']} push <remote> {nf_split.NOTES_REF}{force}")
        print("\nList each new root in PLUGINS where its modules are used.")
        return

    if manifest:
        parts = json.loads(Path(manifest).expanduser().read_text())["outputs"]
    else:
        if not (target and to):
            raise SystemExit(f"{terminal_style.FAIL} name the modules and --to (or pass --manifest)")
        parts = [{"token": token, "to": to, "name": name, "modules": [t for t in target.split(",") if t.strip()]}]
    for part in parts:
        part["modules"] = [_key(m) for m in part.get("modules", ())]
    first = next((m for part in parts for m in part["modules"]), None)
    repo = _repo(root or (_owner_root(first) if first else ""))
    others = plugins.effective_roots()
    try:
        p = nf_split.plan(repo, parts, others, with_dependants, rewrite_published)
    except nf_split.SplitRefused as e:
        _refused("split", e.issues)

    print(f"source   {repo.root}  (token {p.token or '∅'}, {p.commits} commits)\n")
    rows = [(o.word, "continuation" if o.to is None else str(o.to), str(len(o.modules)), str(o.commits), str(o.tags))
            for o in p.outputs]
    terminal_components.table(rows, header=("Root", "Goes to", "Modules", "Commits", "Tags"))
    print(f"\n{p.shared} source commit(s) become a commit in more than one root")
    for o in p.outputs[1:]:
        print(f"\n{o.word}: {', '.join(sorted(p.stems[n][1] for n in o.modules))}")
    for o in p.outputs:
        for needed, pairs in o.needs.items():
            word = needed or "root"
            shown = ", ".join(pairs[:6]) + (f", … ({len(pairs)})" if len(pairs) > 6 else "")
            print(f"\n{o.word} pins namespace {word}: {shown}")
    if p.continuation.needs:
        print(f"\n{terminal_style.WARN} modules that stay depend on modules that leave: {p.continuation.word}'s "
              f"declaration is released as {p.continuation.namespace.version}, and the new root must be present "
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
            _refused("split", refused)
        raise SystemExit(1)
    with terminal_components.step("Verifying: nothing lost, nothing twice, every tag, sound heads"):
        issues = nf_split.verify(p.staging, others)
    if issues is None:
        raise SystemExit(f"{terminal_style.FAIL} the staged split in {p.staging} could not be verified")
    if not issues and not no_test:
        issues = _nfx_test([*repo._others(others, repo.root), *(o["dir"] for o in state["outputs"])])
    if issues:
        print(f"{terminal_style.FAIL} {terminal_style.BOLD}the staged split is not sound{terminal_style.RESET} "
              f"- left in {p.staging} to look at; nothing else was touched:")
        for issue in issues:
            print(f"    {issue}")
        raise SystemExit(1)
    print(f"\n{terminal_style.SUCCESS} staged in {p.staging} - the source is untouched")
    for o in state["outputs"]:
        print(f"  {o['word']:<12} {o['dir']}")
    print(f"\nLook, then:  nf.split --swap {p.staging}")


def _refused(what, issues):
    print(f"{terminal_style.FAIL} {terminal_style.BOLD}{what} refused{terminal_style.RESET} - nothing written:")
    for issue in issues:
        print(f"    {issue}")
    raise SystemExit(1)


@invoke.task(name="log", pre=[setup.env])
def log_(c, target, root="", via=""):
    """A module's whole history, newest first, across its renames and moves - its own changes plain, a commit that only re-pins a dependency dimmed; --via: more roots (comma-separated) to follow, before PLUGINS. `namespace` (or `namespace.nfx`): the declaration's history, in --root or the root you are in."""
    target = _key(target)
    extra = [Path(r).expanduser() for r in via.split(",") if r.strip()]
    try:
        if target == Path(nfx.NAMESPACE_FILENAME).stem:
            entries, note = nf_repo.namespace_log(_repo(root)), None
        else:
            repo = _repo(root or _owner_root(target))
            entries, note = nf_repo.module_log(repo, target, roots=[*extra, *plugins.effective_roots()])
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    # the subject sits before the tags and runs over that column where a commit has none
    def dim(e, cells):
        # cell by cell: the table pads and cuts each cell on its own
        return tuple(f"{terminal_style.DIM}{v}{terminal_style.RESET}" if e.repin and v else v for v in cells)

    rows = [dim(e, (e.date, e.token or ROOT_MARK, e.sha[:7], e.version, e.subject, ", ".join(e.tags)))
            for e in entries]
    terminal_components.table(rows, header=("Date", "Root", "Commit", "Version", "Subject", "Tags"), shrink=4)
    repins = sum(e.repin for e in entries)
    if repins:
        print(f"\n{terminal_style.DIM}{repins} of {len(entries)} commit(s) only re-pin a dependency{terminal_style.RESET}")
    if note:
        print(f"\n{terminal_style.WARN} {note}")


@invoke.task(name="hooks-install", pre=[setup.env])
def hooks_install(c, root="", runner=""):
    """Install a .nf root's hooks: versioned shims in <root>/.githooks/, a stub per hook where git runs it. --runner (required): the wrapper path."""
    if not runner:
        raise SystemExit(f"{terminal_style.FAIL} --runner is required (e.g. /path/to/wrapper) - no default, "
                         f"so a hook never falls back to another line's code")
    repo = _repo(root)
    try:
        wrote = repo.install(runner)
    except FileExistsError as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    for path in wrote:
        print(f"  wrote {path}")
    print(f"{terminal_style.SUCCESS} {repo.root}: hooks run from {repo.hooks_dir()} through `{runner}`"
          f"{'' if wrote else ' (already installed)'}")
