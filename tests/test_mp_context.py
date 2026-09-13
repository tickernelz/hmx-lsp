from __future__ import annotations

import multiprocessing
import threading

import pytest

from hmx_core.index import _context, build


def test_index_never_forks_from_a_threaded_process():
    method = _context().get_start_method()
    assert method != "fork", (
        "the index builds on a background thread inside the server; forking from a "
        "threaded process deadlocks and the server never publishes diagnostics"
    )
    assert method in multiprocessing.get_all_start_methods()


def test_build_completes_from_a_background_thread(tmp_path):
    module = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    module.mkdir(parents=True)
    for index in range(4):
        (module / f"m{index}.py").write_text(
            f'class M{index}(models.Model):\n'
            f'    class Meta:\n'
            f'        name = "demomodel{index}"\n'
        )

    outcome: dict = {}

    def worker():
        try:
            outcome["models"] = len(build(str(tmp_path)).models)
        except BaseException as error:
            outcome["error"] = f"{type(error).__name__}: {error}"

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=120)

    assert not thread.is_alive(), "build hung when called from a background thread"
    assert "error" not in outcome, outcome.get("error")
    assert outcome["models"] >= 4


def _corpus(tmp_path, count=40):
    module = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    module.mkdir(parents=True)
    for index in range(count):
        (module / f"m{index}.py").write_text(
            f'class M{index}(models.Model):\n'
            f'    class Meta:\n'
            f'        name = "demomodel{index}"\n'
        )
    return tmp_path


def test_build_falls_back_to_one_process_when_the_pool_cannot_start(tmp_path, monkeypatch):
    import hmx_core.index as index_module

    root = _corpus(tmp_path)
    expected = len(build(str(root)).models)
    assert expected >= 40

    class Unusable:
        def __getattr__(self, name):
            raise OSError("pool unavailable")

    monkeypatch.setattr(index_module, "_context", lambda: Unusable())
    got = build(str(root))

    assert len(got.models) == expected


def test_fallback_still_resolves_fields(tmp_path, monkeypatch):
    import hmx_core.index as index_module
    from hmx_core.resolve import Resolver

    module = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    module.mkdir(parents=True)
    (module / "order.py").write_text(
        'class Order(models.Model):\n'
        '    class Meta:\n'
        '        name = "saleorder"\n'
        '    amount = models.FloatField()\n'
    )

    class Unusable:
        def __getattr__(self, name):
            raise OSError("pool unavailable")

    monkeypatch.setattr(index_module, "_context", lambda: Unusable())
    resolver = Resolver(build(str(tmp_path)))

    assert resolver.known("saleorder")
    assert "amount" in resolver.fields("saleorder")
