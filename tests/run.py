"""Run every test: python3 tests/run.py"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(HERE, pattern="test_*.py"))
sys.exit(0 if result.wasSuccessful() else 1)
