"""The installed app's entry point (PyInstaller can't start from a package's `__main__`)."""

from neuralloop_desktop.main import main

raise SystemExit(main())
