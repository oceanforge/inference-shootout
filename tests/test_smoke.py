def test_runtime_dependencies_are_pinned_to_the_agreed_set():
    """The spec fixes the runtime dependency list. Adding to it is a design
    decision, not an implementation detail, so the test guards it."""
    with open("requirements.txt") as f:
        names = {
            line.split("==")[0].strip().lower()
            for line in f
            if line.strip() and not line.startswith("#")
        }
    assert names == {"flask", "openai", "python-dotenv", "gunicorn"}


def test_no_module_outgrows_the_readable_budget():
    """The repo is a template people are meant to read end to end. The spec
    caps each module at 200 lines and the application at 500 total."""
    import pathlib

    modules = sorted(pathlib.Path(".").glob("*.py"))
    sizes = {m.name: len(m.read_text().splitlines()) for m in modules}
    oversized = {name: n for name, n in sizes.items() if n > 200}
    assert not oversized, f"modules over 200 lines: {oversized}"
    assert sum(sizes.values()) < 500, f"total application Python: {sum(sizes.values())}"
