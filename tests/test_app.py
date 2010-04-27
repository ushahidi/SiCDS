#!/usr/bin/env python
# Copyright (C) 2010 Ushahidi Inc. <jon@ushahidi.com>,
# Joshua Bronson <jabronson@gmail.com>, and contributors
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the
# Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor,
# Boston, MA  02110-1301
# USA

from functools import partial
from itertools import count
from json import dumps, loads
from pprint import pformat
from re import compile
from sys import stdout
from webtest import TestApp

from sicds.app import SiCDSApp
from sicds.config import SiCDSConfig

TESTKEY = 'sicds_test_key'
TESTSUPERKEY = 'sicds_test_superkey'
TESTPORT = 8635

def test_config(store):
    return dict(port=TESTPORT, keys=[TESTKEY], superkey=TESTSUPERKEY,
        store=store, loggers=['null:'])

# test configs for all supported backends.
# comment out any that aren't installed on your system.
# warning: test data stores will be cleared every time tests are run
# make sure these configs don't point to anything important!
test_configs = (
    test_config('tmp:'),
    test_config('couchdb://localhost:5984/sicds_test'),
    #test_config('mongodb://localhost:27017/sicds_test'),
    )

def next_str(prefix, counter):
    return '{0}{1}'.format(prefix, counter.next())

def make_req(key=TESTKEY, contentItems=[{}]):
    return dict(key=key, contentItems=[make_item(**i) for i in contentItems])

def make_item(id=None, difcollections=[{}], next_item=partial(next_str, 'item', count())):
    return dict(id=id or next_item(), difcollections=[make_coll(**c) for c in difcollections])

def make_coll(name=None, difs=[{}], next_coll=partial(next_str, 'collection', count())):
    return dict(name=name or next_coll(), difs=[make_dif(**d) for d in difs])

def make_dif(type=None, value=None,
        next_type=partial(next_str, 'type', count()),
        next_val=partial(next_str, 'value', count()),
        ):
    return dict(type=type or next_type(), value=value or next_val())

class TestCase(object):
    '''
    Encapsulates a SiCDSRequest, an expected response status code, and part of
    an expected response body.

    Random data will be generated where ``reqdata`` lacks it.
    '''
    def __init__(self, desc, reqdata, req_path=SiCDSApp.R_IDENTIFY,
            res_status_expect=200, res_body_expect=''):
        self.desc = desc
        self.req_path = req_path
        self.req_body = dumps(reqdata)
        self.res_status_expect = res_status_expect
        if isinstance(res_body_expect, dict):
            res_body_expect = dumps(res_body_expect)
        self.res_body_expect = res_body_expect

    @property
    def expect_errors(self):
        return self.res_status_expect >= 400

def result_str(uniq):
    return SiCDSApp.RES_UNIQ if uniq else SiCDSApp.RES_DUP

def make_resp(req, uniq=True):
    results = [dict(id=coll['id'], result=result_str(uniq))
        for coll in req['contentItems']]
    return {'key': req['key'], 'results': results}

test_cases = []

# test that duplication identification works as expected
# first time we see an item it should be unique,
# subsequent times it should be duplicate
req1 = make_req()
res1_uniq = make_resp(req1, uniq=True)
res1_dup = make_resp(req1, uniq=False)
tc_uniq = TestCase('item1 unique', req1, res_body_expect=res1_uniq)
tc_dup = TestCase('item1 now duplicate', req1, res_body_expect=res1_dup)
test_cases.extend((tc_uniq, tc_dup))

# test multi-collection identification
# if we see an item with multiple collections, each of which we haven't seen
# before, it should be unique. if we see an item with multiple collections
# at least one of which we've seen before, it should be duplicate
c1 = make_coll()
c2 = make_coll()
c3 = make_coll()
i1 = make_item(difcollections=[c1, c2])
i2 = make_item(difcollections=[c2, c3])
i3 = make_item(difcollections=[c3])
req2 = make_req(contentItems=[i1])
req3 = make_req(contentItems=[i2])
req4 = make_req(contentItems=[i3])
res2_uniq = make_resp(req2, uniq=True)
res3_dup = make_resp(req3, uniq=False)
res4_dup = make_resp(req4, uniq=False)
tc_uniq2 = TestCase('[c1, c2] collections unique', req2, res_body_expect=res2_uniq)
tc_dup2 = TestCase('[c2, c3] collections duplicate', req3, res_body_expect=res3_dup)
tc_dup3 = TestCase('[c3] collection duplicate', req4, res_body_expect=res4_dup)
test_cases.extend((tc_uniq2, tc_dup2, tc_dup3))

# test that order of difs does not matter
d1 = make_dif()
d2 = make_dif()
c12 = make_coll(difs=[d1, d2])
c21 = make_coll(difs=[d2, d1])
i12 = make_item(difcollections=[c12])
i21 = make_item(difcollections=[c21])
req12 = make_req(contentItems=[i12])
req21 = make_req(contentItems=[i21])
res12_uniq = make_resp(req12, uniq=True)
res21_dup = make_resp(req21, uniq=False)
tc_uniq12 = TestCase('[dif1, dif2] unique',
    req12, res_body_expect=res12_uniq)
tc_dup21 = TestCase('[dif2, dif1] duplicate (order does not matter)',
    req21, res_body_expect=res21_dup)
test_cases.extend((tc_uniq12, tc_dup21))

# test registering a new key
NEWKEY = 'sicds_test_key2'
req_keyreg = {'superkey': TESTSUPERKEY, 'newkey': NEWKEY}
tc_keyreg = TestCase('register new key', req_keyreg,
    req_path=SiCDSApp.R_REGISTER_KEY,
    res_body_expect=SiCDSApp.KEYREGOK)
test_cases.append(tc_keyreg)

# existing content should look new to the client using the new key
req1_newkey = dict(req1, key=NEWKEY)
res1_newkey = dict(res1_uniq, key=NEWKEY)
tc_newkey_uniq = TestCase('item1 unique to new client',
    req1_newkey, res_body_expect=res1_newkey)
test_cases.append(tc_newkey_uniq)

# check that various bad requests give error responses
req_badkey = dict(req1, key='bad_key')
tc_badkey = TestCase('reject bad key', req_badkey,
    res_status_expect=SiCDSApp.X_UNAUTHORIZED_KEY().status_int,
    res_body_expect=SiCDSApp.E_UNAUTHORIZED_KEY,
    )
test_cases.append(tc_badkey)

tc_missing_fields = TestCase('reject missing fields', {},
    res_status_expect=SiCDSApp.X_BAD_REQ().status_int, 
    res_body_expect=SiCDSApp.E_BAD_REQ,
    )
test_cases.append(tc_missing_fields)

req_extra_fields = dict(make_req(), extra='extra')
tc_extra_fields = TestCase('reject extra fields', req_extra_fields,
    res_status_expect=SiCDSApp.X_BAD_REQ().status_int, 
    res_body_expect=SiCDSApp.E_BAD_REQ,
    )
test_cases.append(tc_extra_fields)

req_too_large = {'too_large': ' '*SiCDSApp.REQMAXBYTES}
tc_too_large = TestCase('reject too large', req_too_large,
    res_status_expect=SiCDSApp.X_REQ_TOO_LARGE().status_int, 
    res_body_expect=SiCDSApp.E_REQ_TOO_LARGE,
    )
test_cases.append(tc_too_large)


npassed = nfailed = 0
failures_per_config = []
for config in test_configs:
    config = SiCDSConfig(config)
    config.store.clear()
    store_type = config.store.__class__.__name__
    stdout.write('{0}:\t'.format(store_type))
    failures = []
    app = SiCDSApp(config.keys, config.superkey, config.store, config.loggers)
    app = TestApp(app)
    for tc in test_cases:
        resp = app.post(tc.req_path, tc.req_body, status=tc.res_status_expect,
            expect_errors=tc.expect_errors, headers={
            'content-type': 'application/json'})
        if tc.res_body_expect not in resp:
            tc.res_status_got = resp.status_int
            tc.res_body_got = resp.body
            nfailed += 1
            failures.append(tc)
            stdout.write('F')
        else:
            npassed += 1
            stdout.write('.')
        stdout.flush()
    stdout.write('\n')
    if failures:
        failures_per_config.append((store_type, failures))

print('\n{0} test(s) passed, {1} test(s) failed.'.format(npassed, nfailed))

whitespace = compile('\s+')
def indented(text, indent=' '*6, width=60, collapse_whitespace=True):
    if collapse_whitespace:
        text = ' '.join(whitespace.split(text))
    return '\n'.join((indent + text[i:i+width] for i in range(0, len(text), width)))

if nfailed:
    print('\nFailure summary:')
    for fs in failures_per_config:
        print('\n  For {0}:'.format(fs[0]))
        for tc in fs[1]:
            print('\n    test:')
            print('      {0}'.format(tc.desc))
            print('    request:')
            print(indented(tc.req_body, collapse_whitespace=False))
            print('    expected response:')
            print(indented(tc.res_body_expect))
            print('    got response:')
            print(indented(tc.res_body_got))
