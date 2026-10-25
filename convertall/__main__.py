"""python -m convertall: no arguments (or --gui) opens the window, anything else is the CLI."""

import sys


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "--gui":
        from .gui import main as gui_main
        return gui_main(args[1:] if args else [])
    from .cli import main as cli_main
    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
