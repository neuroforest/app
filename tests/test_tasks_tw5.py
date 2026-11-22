import json


def _wrapper(root, name):
    wrapper = root / name
    wrapper.mkdir(parents=True)
    (wrapper / "build.json").write_text(json.dumps({"submodules": []}))
    return wrapper


def test_uncompiled(tmp_path):
    from tasks.components import tw5

    fresh = _wrapper(tmp_path, "fresh")
    empty = _wrapper(tmp_path, "empty")
    (empty / "compiled").mkdir()
    done = _wrapper(tmp_path, "done")
    (done / "compiled" / "plugin").mkdir(parents=True)

    assert tw5.uncompiled(tmp_path) == [str(empty), str(fresh)]
