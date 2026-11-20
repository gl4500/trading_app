# tests package
#
# The throwaway-database bootstrap lives in tests/_isolation.py so that every
# test module can import it directly (X-14): top-level discovery never imports
# this package, so each test_*.py repeats `import tests._isolation` first.
import tests._isolation  # noqa: F401
