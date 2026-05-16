import invoke
from tasks.actions import install, pkg, setup, status, test
from tasks.components import app, desktop, knowledge, neuro, neurobase, nfx, nwjs, ontology, tw5

ns = invoke.Collection()
ns.add_collection(install)
ns.add_collection(pkg)
ns.add_collection(setup)
ns.add_task(status.status)
ns.add_collection(test)
ns.add_collection(app)
ns.add_collection(desktop)
ns.add_collection(knowledge)
ns.add_collection(neuro)
ns.add_collection(neurobase)
ns.add_collection(nfx)
ns.add_collection(nwjs)
ns.add_collection(ontology)
ns.add_collection(tw5)
