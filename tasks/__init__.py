from invoke import Collection
from . import setup, prepare, build, test, desktop

ns = Collection()
ns.add_task(setup.setup)
ns.add_collection(prepare)
ns.add_collection(build)
ns.add_collection(test)
ns.add_collection(desktop)
