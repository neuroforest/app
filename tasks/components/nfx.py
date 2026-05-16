import os
from pathlib import Path

import invoke

from neuro.base import nfx
from neuro.base.index import NfxIndex
from neuro.utils import internal_utils, terminal_components

from tasks.actions import setup


@invoke.task(pre=[setup.env])
def index(c):
    """Show every discovered .nfx (ontology, knowledge, metaontology) in one table."""
    roots = internal_utils.get_path_list("PLUGINS")
    idx = NfxIndex(*roots)

    app_dir = Path(os.environ["APP_DIR"])
    type_label = {"metaontology": "meta", "ontology": "onto", "knowledge": "know"}
    type_order = {"metaontology": 0, "ontology": 1, "knowledge": 2}
    entries = []
    for path in idx.all_targets():
        doc = nfx.read(path)
        try:
            rel = os.path.relpath(path, app_dir)
        except ValueError:
            rel = str(path)
        entries.append((doc.type, doc.name or path.stem, doc.version, doc.nid, rel))
    entries.sort(key=lambda r: (type_order.get(r[0], 99), r[1]))
    rows = [
        (type_label.get(t, t or "?"), n, v, (nid or "")[:8], p)
        for t, n, v, nid, p in entries
    ]
    terminal_components.table(rows, header=("Type", "Name", "Version", "NID", "Path"))
