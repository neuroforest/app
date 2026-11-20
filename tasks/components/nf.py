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
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import invoke

from neuro.base import nf_import, nf_repo, nfx, plugins
from neuro.base.index import NfxIndex
from neuro.utils import internal_utils, terminal_components, terminal_style

from tasks.actions import setup


ROOT_MARK = f"{terminal_style.DIM}·{terminal_style.RESET}"


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
    for m in head.moves:
        got = subprocess.run(["git", "-C", str(dst), "show", f"HEAD:{m.rel}"], capture_output=True).stdout
        if got != m.content:
            tree_issues.append(f"{m.rel}: differs from the import of {src}")
    listed = subprocess.run(["git", "-C", str(dst), "ls-tree", "-r", "--name-only", "HEAD"],
                            capture_output=True, text=True).stdout.split()
    tree_issues += [f"{p}: in HEAD, not in the import" for p in sorted(set(listed) - {str(m.rel) for m in head.moves})]

    print(f"\n{src} → {dst}")
    print(f"namespace {namespace.nid}{' (minted)' if minted else ''}")
    print(f"{report.commits} legacy commits → {report.events} commits · "
          f"{report.legacy_tags} legacy tags → {report.tags - report.synthesized} annotated "
          f"+ {report.synthesized} synthesized for untagged versions")
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
        return nf_repo.Repo(Path(root or ".").expanduser())
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


def _owner_root(key):
    """The root among PLUGINS that holds the document `key` names."""
    roots = plugins.effective_roots()
    path = NfxIndex(*roots).resolve(key)
    root = path and plugins.registry_root_of(path, roots)
    if root is None:
        raise SystemExit(f"{terminal_style.FAIL} {key}: in none of the PLUGINS roots - pass --root")
    return root


@invoke.task(pre=[setup.env])
def release(c, target, root="", major=False, dry_run=False, message=""):
    """Release documents (comma-separated) with their in-root dependants: re-pin, bump, one commit, one tag each."""
    targets = [t.strip() for t in target.split(",") if t.strip()]
    repo = _repo(root or _owner_root(targets[0]))
    others = plugins.effective_roots()
    try:
        steps = repo.plan_release(targets, major, others) if dry_run else None
        if not dry_run:
            sha, steps, tags = repo.release(targets, major, others, message or None)
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
    """Rename a module inside its root: files, name, test path and tags in one `REFACTOR:` commit, no version bump."""
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
