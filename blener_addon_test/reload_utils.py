import importlib
import sys

import bpy


def register_class(cls):
    """二重 register やリロード後の残骸を吸収して登録する。"""
    try:
        bpy.utils.register_class(cls)
    except ValueError as exc:
        if "already registered" not in str(exc):
            raise
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
        bpy.utils.register_class(cls)


def unregister_class(cls):
    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError:
        pass


def register_classes(classes):
    for cls in classes:
        register_class(cls)


def unregister_classes(classes):
    for cls in reversed(classes):
        unregister_class(cls)


def iter_addon_module_names(package_name: str) -> list[str]:
    prefix = package_name + "."
    return [
        name
        for name in sys.modules
        if name == package_name or name.startswith(prefix)
    ]


def pop_addon_modules(package_name: str) -> list[str]:
    """Remove all modules belonging to the addon package from sys.modules."""
    module_names = sorted(iter_addon_module_names(package_name), key=len, reverse=True)
    removed = []
    for name in module_names:
        if name in sys.modules:
            sys.modules.pop(name)
            removed.append(name)
    return removed


def reload_addon_package(package_name: str):
    """Unregister, pop all addon modules, re-import, and register again."""
    package = sys.modules.get(package_name)
    if package is not None and hasattr(package, "unregister"):
        package.unregister()

    removed = pop_addon_modules(package_name)

    module = importlib.import_module(package_name)
    if hasattr(module, "register"):
        module.register()

    return module, removed
