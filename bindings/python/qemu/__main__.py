import sys
from . import run


def main():
    try:
        result = run(sys.argv[1:])
    except (OSError, RuntimeError, ValueError) as error:
        print(f"qemu: {error}", file=sys.stderr)
        result = 1
    raise SystemExit(result)


if __name__ == "__main__":
    main()
