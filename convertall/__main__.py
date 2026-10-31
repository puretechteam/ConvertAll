"""python -m convertall: no arguments (or --gui) opens the window, anything else is the CLI."""

import sys


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "--gui":
        from .instance import (
            main as gui_main,  # hands files to an open window before loading it
        )
        return gui_main(args[1:] if args else [])
    from .cli import main as cli_main
    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
