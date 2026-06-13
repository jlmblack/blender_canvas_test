bl_info = {
    "name": "Paint Canvas",
    "author": "CyberAgent",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Addon Test",
    "description": "Pen paint on plane (CPU raster + GPU viewport overlay)",
    "category": "Development",
}

import traceback

_LOG_PREFIX = "[Paint Canvas]"


def _log(msg):
    print(f"{_LOG_PREFIX} {msg}")


_import_error = None
try:
    from . import operators, properties, ui
    from . import material, viewport
except Exception as exc:
    _import_error = exc
    _log("IMPORT FAILED (アドオン一覧に出ない／有効化できない原因になります):")
    traceback.print_exc()


def register():
    if _import_error is not None:
        _log(f"register() aborted: import error: {_import_error}")
        raise _import_error

    _log("register() start")
    steps = (
        ("properties", properties.register),
        ("operators", operators.register),
        ("ui", ui.register),
        ("material", material.register_handlers),
        ("viewport", viewport.ensure_handler),
    )
    done = []
    try:
        for name, fn in steps:
            _log(f"  -> {name} ...")
            fn()
            done.append(name)
            _log(f"  -> {name} OK")
    except Exception:
        _log(f"register() FAILED (完了済み: {', '.join(done) or 'なし'})")
        traceback.print_exc()
        raise

    _log("register() complete")


def unregister():
    if _import_error is not None:
        return

    _log("unregister() start")
    for name, fn in (
        ("viewport", viewport.free_handler),
        ("material", material.unregister_handlers),
        ("ui", ui.unregister),
        ("operators", operators.unregister),
        ("properties", properties.unregister),
    ):
        try:
            fn()
            _log(f"  -> {name} OK")
        except Exception:
            _log(f"  -> {name} FAILED")
            traceback.print_exc()
    _log("unregister() complete")
