"""Regression tests for Flask routes that accept path-containing IDs."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


ROOT = Path(__file__).parents[2]
CONFIG = ROOT / "tests" / "functionaltests" / "suites" / "cite" / "default.yml"


def test_stac_routes_accept_path_containing_collection_and_item_ids():
    script = """
from pycsw import wsgi_flask

adapter = wsgi_flask.APP.url_map.bind('localhost')
collection = 'doi:10.1594/PANGAEA.912516'
item = 'doi:10.1594/PANGAEA.912516/record-1'

assert adapter.match('/stac/collections/' + collection)[0] == 'pycsw.collection'
assert adapter.match('/stac/collections/' + collection + '/items')[0] == 'pycsw.items'
assert (
    adapter.match('/stac/collections/' + collection + '/items/' + item)[0]
    == 'pycsw.item'
)
"""
    environment = os.environ.copy()
    environment["PYCSW_CONFIG"] = str(CONFIG)
    environment["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
