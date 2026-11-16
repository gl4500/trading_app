"""A3 Task 15a: reviewed launcher for the installed Cosmic Ray 8.3.15 console entry points.

Cosmic Ray has no ``__main__`` (``python -m cosmic_ray`` is unsupported), and the harness never uses ``-c`` or stdin
scripts. So the coordinator runs THIS file with the explicit testenv interpreter:

    <testenv python> research/s1/s1_tests/cr_launch.py cosmic-ray <init|exec|dump|...> ...
    <testenv python> research/s1/s1_tests/cr_launch.py cr-report <session.sqlite> [--show-output] ...

Only the two entry points named in the installed ``entry_points.txt`` are reachable:
``cosmic-ray = cosmic_ray.cli:main`` and ``cr-report = cosmic_ray.tools.report:report``. Anything else is refused with
exit code 2. Part of the mutation harness: excluded from every mutation inventory and hashed separately.
"""
import sys

ENTRY_POINTS = ("cosmic-ray", "cr-report")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ENTRY_POINTS:
        print(f"cr_launch: first argument must be one of {ENTRY_POINTS}, got {argv[:1]}", file=sys.stderr)
        return 2
    name, rest = argv[0], list(argv[1:])
    if name == "cosmic-ray":
        import cosmic_ray.cli
        return int(cosmic_ray.cli.main(rest) or 0)
    import cosmic_ray.tools.report
    try:
        cosmic_ray.tools.report.report.main(args=rest, prog_name="cr-report", standalone_mode=True)
    except SystemExit as exc:                     # click's standalone mode always exits
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
