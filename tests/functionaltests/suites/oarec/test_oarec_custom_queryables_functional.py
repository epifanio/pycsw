# =================================================================
#
# Authors: Massimo Di Stefano <epiesasha@me.com>
#
# Copyright (c) 2026 Massimo Di Stefano
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# =================================================================

"""Custom queryables declared in the repository mappings.

A deployment adds columns to the records table (here: ``length_m``, a
number, and ``drivable``, a flag) and declares them in its custom
mappings as ``MD_CORE_MODEL['queryables']``. They must then be
queryable in OGC API - Records (under their column name) and in CSW
(under the declared name), and advertised by both.
"""

from copy import deepcopy
import io
import json
import shutil
import sqlite3
import textwrap
from xml.etree import ElementTree as etree

import pytest

from pycsw.ogc.api.records import API
from pycsw.server import Csw

pytestmark = pytest.mark.functional

CITE_DB = 'tests/functionaltests/suites/cite/data/cite.db'

# identifier -> (length_m, drivable)
VALUES = {
    'urn:uuid:19887a8a-f6b0-4a63-ae56-7fba0e17801f': (250.0, 1),
    'urn:uuid:1ef30a8b-876d-4828-9246-c37ab4510bbd': (1200.0, 1),
    'urn:uuid:66ae76b7-54ba-489b-a582-0f0633d96493': (4800.0, 0),
    'urn:uuid:6a3de50b-fa66-4b58-a0e6-ca146fdd18d4': (999.0, 0),
}

MAPPINGS = '''
from copy import deepcopy
from pycsw.core.config import StaticContext

MD_CORE_MODEL = deepcopy(StaticContext().md_core_model)
MD_CORE_MODEL['queryables'] = {
    'ext:length_m': 'length_m',
    'ext:drivable': 'drivable',
    'ext:missing': 'no_such_column',   # skipped: the column does not exist
    'dc:title': 'length_m',            # skipped: clashes with a core queryable
}
'''


@pytest.fixture()
def custom_config(config, tmp_path):
    db = tmp_path / 'cite-custom.db'
    shutil.copy(CITE_DB, db)
    con = sqlite3.connect(db)
    con.execute('ALTER TABLE records ADD COLUMN length_m REAL')
    con.execute('ALTER TABLE records ADD COLUMN drivable INTEGER')
    for identifier, (length, drivable) in VALUES.items():
        con.execute('UPDATE records SET length_m = ?, drivable = ? '
                    'WHERE identifier = ?', (length, drivable, identifier))
    con.commit()
    con.close()

    mappings = tmp_path / 'custom_queryables_mappings.py'
    mappings.write_text(textwrap.dedent(MAPPINGS))

    cfg = deepcopy(config)
    cfg['repository']['database'] = f'sqlite:///{db}'
    cfg['repository']['mappings'] = str(mappings)
    yield cfg


def test_oarec_queryables_include_custom_columns(custom_config):
    api = API(custom_config)
    headers, status, content = api.queryables({}, {})
    properties = json.loads(content)['properties']

    assert properties['length_m']['type'] == 'number'
    assert properties['drivable']['type'] == 'integer'
    assert 'no_such_column' not in properties


def test_oarec_items_filter_on_custom_queryables(custom_config):
    api = API(custom_config)

    def matched(cql):
        headers, status, content = api.items({}, None, {'filter': cql})
        assert status == 200, content
        return {f['id'] for f in json.loads(content)['features']}

    assert matched('length_m > 1000') == {
        'urn:uuid:1ef30a8b-876d-4828-9246-c37ab4510bbd',
        'urn:uuid:66ae76b7-54ba-489b-a582-0f0633d96493'}
    assert matched('length_m > 1000 AND drivable = 1') == {
        'urn:uuid:1ef30a8b-876d-4828-9246-c37ab4510bbd'}
    assert matched('length_m BETWEEN 200 AND 1000') == {
        'urn:uuid:19887a8a-f6b0-4a63-ae56-7fba0e17801f',
        'urn:uuid:6a3de50b-fa66-4b58-a0e6-ca146fdd18d4'}


def test_oarec_without_custom_queryables_is_unchanged(config):
    api = API(config)
    properties = json.loads(api.queryables({}, {})[2])['properties']
    assert len(properties) == 20
    assert 'length_m' not in properties


def _csw(custom_config, body):
    environ = {
        'REQUEST_METHOD': 'POST', 'PATH_INFO': '/csw', 'QUERY_STRING': '',
        'CONTENT_TYPE': 'application/xml',
        'CONTENT_LENGTH': str(len(body)),
        'wsgi.input': io.BytesIO(body.encode()),
        'SERVER_NAME': 'localhost', 'SERVER_PORT': '80',
        'HTTP_HOST': 'localhost', 'wsgi.url_scheme': 'http',
        'SCRIPT_NAME': '', 'REMOTE_ADDR': '127.0.0.1',
        'local.app_root': '.',
    }
    csw = Csw(custom_config, environ)
    status, content = csw.dispatch_wsgi()
    return etree.fromstring(content)


NS = {
    'csw': 'http://www.opengis.net/cat/csw/2.0.2',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'ows': 'http://www.opengis.net/ows',
}


def _getrecords(filter_xml):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<csw:GetRecords xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
    xmlns:ogc="http://www.opengis.net/ogc" service="CSW" version="2.0.2"
    resultType="results" maxRecords="20"
    outputSchema="http://www.opengis.net/cat/csw/2.0.2">
  <csw:Query typeNames="csw:Record">
    <csw:ElementSetName>brief</csw:ElementSetName>
    <csw:Constraint version="1.1.0">
      <ogc:Filter>{filter_xml}</ogc:Filter>
    </csw:Constraint>
  </csw:Query>
</csw:GetRecords>'''


def test_csw_getrecords_filter_on_custom_queryables(custom_config):
    doc = _csw(custom_config, _getrecords('''
        <ogc:And>
          <ogc:PropertyIsGreaterThan>
            <ogc:PropertyName>ext:length_m</ogc:PropertyName>
            <ogc:Literal>1000</ogc:Literal>
          </ogc:PropertyIsGreaterThan>
          <ogc:PropertyIsEqualTo>
            <ogc:PropertyName>ext:drivable</ogc:PropertyName>
            <ogc:Literal>1</ogc:Literal>
          </ogc:PropertyIsEqualTo>
        </ogc:And>'''))
    ids = {e.text for e in doc.iter('{%s}identifier' % NS['dc'])}
    assert ids == {'urn:uuid:1ef30a8b-876d-4828-9246-c37ab4510bbd'}


def test_csw_rejects_undeclared_custom_names(custom_config):
    doc = _csw(custom_config, _getrecords('''
        <ogc:PropertyIsGreaterThan>
          <ogc:PropertyName>ext:missing</ogc:PropertyName>
          <ogc:Literal>1</ogc:Literal>
        </ogc:PropertyIsGreaterThan>'''))
    assert doc.tag == '{%s}ExceptionReport' % NS['ows']


def test_csw_capabilities_advertise_custom_queryables(custom_config):
    body = '''<?xml version="1.0" encoding="UTF-8"?>
<csw:GetCapabilities xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
    xmlns:ows="http://www.opengis.net/ows" service="CSW">
  <ows:AcceptVersions><ows:Version>2.0.2</ows:Version></ows:AcceptVersions>
</csw:GetCapabilities>'''
    doc = _csw(custom_config, body)
    constraint = doc.find(
        './/ows:Operation[@name="GetRecords"]/ows:Constraint'
        '[@name="CustomQueryables"]', NS)
    assert constraint is not None
    values = {v.text for v in constraint.iter('{%s}Value' % NS['ows'])}
    assert values == {'ext:length_m', 'ext:drivable'}
