"""`invoke ncbi.*` - keeping a base's NCBI taxa in step with NCBI Taxonomy.

The engine is :mod:`neuro.tools.science.taxonomy`; this is the task around it:
open the base the wrapper names, run the sync, print one line per change.
An app that wants the changelog kept
wraps the same engine itself; the task prints to stdout and the
journal keeps that.
"""
import sys
from datetime import datetime, timezone

import invoke

from neuro.base import NeuroBase, plugins
from neuro.base.index import OntologyIndex
from neuro.tools.integrations import ncbi as entrez
from neuro.tools.science import taxonomy
from neuro.utils import terminal_style

from tasks.actions import setup


def run(nb, dry_run=False, out=sys.stdout):
    """The sync against an open base, printing each change; returns them.
    Exits 1 on a post-run invariant violation - a node with two parents."""
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    graph = taxonomy.NeoGraph(nb)
    try:
        changes = taxonomy.sync(graph, entrez.fetch_taxa, dry_run=dry_run)
    except taxonomy.SyncInvariantError as error:
        print(f"{terminal_style.FAIL} {error}", file=sys.stderr)
        raise SystemExit(1) from error
    prefix = "[dry-run] " if dry_run else ""
    for change in changes:
        print(prefix + change.line(when), file=out)
    if not changes:
        print(f"{when}  CHECK   -         {len(graph.taxa())} taxa, nothing changed", file=out)
    return changes


@invoke.task(pre=[setup.env])
def sync(c, dry_run=False):
    """Bring every :NcbiTaxon in the base to what NCBI says it is now -
    renames, moves (one IS_CHILD parent, replaced), merges, pruned ancestors -
    one changelog line per change. --dry-run decides and prints, writes nothing."""
    OntologyIndex(*plugins.effective_roots())
    with NeuroBase() as nb:
        run(nb, dry_run=dry_run)
