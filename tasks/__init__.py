import invoke
from .actions import setup, test
from .components import desktop, neuro, neurobase, nwjs, tw5

ns = invoke.Collection()
ns.add_collection(setup)
ns.add_collection(test)
ns.add_collection(desktop)
ns.add_collection(neuro)
ns.add_collection(neurobase)
ns.add_collection(nwjs)
ns.add_collection(tw5)
