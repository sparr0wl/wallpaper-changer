"""PyInstaller entry point: ships the Python service, not the Linux desktop UI."""
import sys

if __name__ == '__main__':
    if '--self-test' in sys.argv:
        from dota_background.self_test import main
        raise SystemExit(main())
    from dota_background.bridge import serve
    try:
        raise SystemExit(serve())
    except KeyboardInterrupt:
        raise SystemExit(130)
