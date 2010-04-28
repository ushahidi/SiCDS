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

from json import loads, dumps
from sicds.schema import Schema, InvalidField, many, t_str, t_uni
from urlparse import urlsplit
from webob import Response, exc
from webob.dec import wsgify

class KeyRegRequest(Schema):
    required = {'superkey': t_str, 'newkey': t_str}

def v_keyregresult(registered):
    if registered:
        return 'registered'
    return 'already registered'

class KeyRegResponse(Schema):
    required = {'key': t_str, 'registered': v_keyregresult}

class Dif(Schema):
    required = {'type': t_uni, 'value': t_uni}

class DifCollection(Schema):
    required = {'name': t_uni, 'difs': many(Dif, atleast=1)}

class ContentItem(Schema):
    required = {'id': t_uni, 'difcollections': many(DifCollection, atleast=1)}

class IDRequest(Schema):
    '''
    >>> req = {"key":"some_key","contentItems":[
    ...         {"id":"d87fds7f6s87f6sd78fsdf","difcollections":[
    ...           {"name":"collection1","difs":[
    ...             {"type":"some-type1","value":"some-value-1"},
    ...             {"type":"some-type1","value":"some-value-2"}
    ...             ]
    ...           },
    ...           {"name":"collection2","difs":[
    ...             {"type":"some-type1","value":"some-value-1"},
    ...             {"type":"some-type1","value":"some-value-2"}
    ...             ]
    ...           }]
    ...         }]
    ...       }
    >>> req = IDRequest(req)
    >>> req
    <IDRequest ...>
    >>> req.key
    'some_key'
    >>> IDRequest({'fields': 'missing'})
    Traceback (most recent call last):
      ...
    RequiredField: ...

    '''
    required = {'key': t_str, 'contentItems': many(ContentItem, atleast=1)}

def v_idresult(uniq):
    if uniq:
        return 'unique'
    return 'duplicate'

class IDResult(Schema):
    required = {'id': t_uni, 'result': v_idresult}

class IDResponse(Schema):
    required = {'key': t_str, 'results': many(IDResult, atleast=1)}


class SiCDSApp(object):
    #: max size of request body. bigger will be refused.
    REQMAXBYTES = 1024

    def __init__(self, keys, superkey, store, loggers):
        '''
        :param keys: clients must supply a key in this iterable to use the API
        :param superkey: new keys can be registered using this key
        :param store:
        :param loggers: a list of :class:`BaseLogger` implementations
        '''
        self.keys = set(keys)
        self.superkey = superkey
        self.store = store
        self.loggers = loggers
        self.store.ensure_keys(self.keys)

    def _log(self, success, *args, **kw):
        for logger in self.loggers:
            if success:
                logger.success(*args, **kw)
            else:
                logger.error(*args, **kw)

    def _register(self, json):
        data = KeyRegRequest(json)
        if data.superkey != self.superkey:
            raise exc.HTTPForbidden
        registered = self.store.register_key(data.newkey)
        self.keys.add(data.newkey)
        resp = KeyRegResponse(key=data.newkey, registered=registered)
        return Response(body=dumps(resp.unwrap))

    def _identify(self, json):
        data = IDRequest(json)
        if data.key not in self.keys:
            raise exc.HTTPForbidden
        uniq, dup = self._process(data.key, data.contentItems)
        results = [IDResult({'id': i, 'result': True}) for i in uniq] + \
                  [IDResult({'id': i, 'result': False}) for i in dup]
        resp = IDResponse(key=data.key, results=results).unwrap
        return Response(content_type='application/json', body=dumps(resp))

    def _process(self, key, items):
        uniqitems = []
        dupitems = []
        for item in items:
            uniq = True
            for collection in item.difcollections:
                difs = collection.difs
                if self.store.has(key, difs):
                    uniq = False
                else:
                    self.store.add(key, difs)
            if uniq:
                uniqitems.append(item.id)
            else:
                dupitems.append(item.id)
        return uniqitems, dupitems

    #: routes
    R_IDENTIFY = '/'
    R_REGISTER_KEY = '/register'
    _routes = {
        R_IDENTIFY: _identify,
        R_REGISTER_KEY: _register,
        }

    @wsgify
    def __call__(self, req):
        try:
            if req.path_info not in self._routes:
                raise exc.HTTPNotFound
            if req.method != 'POST':
                raise exc.HTTPMethodNotAllowed
            if req.content_length > self.REQMAXBYTES:
                raise exc.HTTPRequestEntityTooLarge
            json = loads(req.body)
            handler = self._routes[req.path_info]
            resp = handler(self, json)
            self._log(True, req, resp)
            return resp
        except exc.HTTPException as e:
            self._log(False, req, repr(e))
            raise
        except Exception as e:
            self._log(False, req, repr(e))
            raise exc.HTTPBadRequest(str(e))

def main():
    from config import SiCDSConfig, DEFAULTCONFIG
    from sys import argv

    def die(msg):
        print(msg)
        exit(1)

    if argv[1:]:
        configpath = argv[1]
        from yaml import load, YAMLError
        try:
            with open(configpath) as configfile:
                config = load(configfile)
        except YAMLError:
            die('Could not parse yaml')
        except IOError:
            die('Could not open file {0}'.format(configpath))
    else:
        import doctest
        doctest.testmod(optionflags=doctest.ELLIPSIS)

        config = DEFAULTCONFIG
        print('Warning: Using default configuration. Data will not be persisted.')

    config = SiCDSConfig(config)
    app = SiCDSApp(config.keys, config.superkey, config.store, config.loggers)
    from wsgiref.simple_server import make_server
    httpd = make_server(config.host, config.port, app)
    print('Serving on port {0}'.format(config.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
