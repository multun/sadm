# Prologin-SADM is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Prologin-SADM is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Prologin-SADM.  If not, see <http://www.gnu.org/licenses/>.

import json
import tornado.web
import types

import prologin.web


class MethodError(Exception):
    """Exception used to notice the remote callers that the requested method
    does not exist.
    """
    pass


def remote_method(func):
    """Decorator for methods to be callable remotely."""
    func.remote_method = True
    return func

def is_remote_method(obj):
    """Return if a random object is a remote method."""
    return callable(obj) and getattr(obj, 'remote_method', False)


class MethodCollection(type):
    """Metaclass for RPC objects: collect remote methods and store them in a
    class-wide REMOTE_METHOD dictionnary.  Be careful: of course, stored
    methods are not bound to an instance.
    """

    def __init__(cls, name, bases, dct):
        super(MethodCollection, cls).__init__(name, bases, dct)

        # Build the list of remote methods.
        remote_methods = {}
        for name, obj in dct.items():
            if is_remote_method(obj):
                remote_methods[name] = obj
        cls.REMOTE_METHODS = remote_methods


class RemoteCallHandler(tornado.web.RequestHandler):

    @property
    def rpc_object(self):
        """RPC object: contains method that can be called remotely."""
        return self.application

    @tornado.web.asynchronous
    def post(self, method_name):
        # This is an asynchronous handler, since
        request = json.loads(self.request.body.strip().decode('ascii'))

        # First get the method to call.
        try:
            method = self.rpc_object.REMOTE_METHODS[method_name]
        except KeyError:
            self.set_status(404)
            return self._send_exception(MethodError(method_name))

        self.set_status(200)

        args = request['args']
        kwargs = request['kwargs']

        # Actually call it.
        try:
            result = method(self.rpc_object, *args, **kwargs)
        except Exception as exn:
            return self._send_exception(exn)

        # The remote method can be a generator (returns a sequence of values),
        # or just some regular function (returns only one value).
        if isinstance(result, types.GeneratorType):
            # If it is a generator, notice the client.
            self._send_json_line({'type': 'generator'})

            # Then yield successive values.
            while True:
                try:
                    value = next(result)
                except StopIteration:
                    # The generator stopped: notice the client and stop, too.
                    self._send_json_line({'type': 'stop'})
                    return self.finish()
                except Exception as exn:
                    # The generator raised an error: transmit it to the client
                    # and stop.
                    return self._send_exception(exn)
                else:
                    # The generator simply yielded a value: transmit it to the
                    # client, or stop there if this is some non-JSON data.
                    if not self._send_result_data(value):
                        return

        else:
            # Otherwise, just return the single value.
            if self._send_result_data(result):
                self.finish()

    def _send_json_line(self, data):
        self.write(json.dumps(data).encode('ascii'))
        self.write(b'\n')
        self.flush()

    @tornado.web.asynchronous
    def _send_exception(self, exn):
        self._send_json_line({
            'type': 'exception',
            'exn_type': type(exn).__name__,
            'exn_message': str(exn),
        })
        # Exceptions always end the communication.
        self.finish()

    def _send_result_data(self, data):
        success = True
        try:
            self._send_json_line({
                'type': 'result',
                'data': data,
            })
        except (TypeError, ValueError):
            self._send_exception(
                ValueError('The remote method returned something not JSON'),
            )
            success = False
        return success


class BaseRPCApp(prologin.web.TornadoApp, metaclass=MethodCollection):
    """RPC base application: let clients call remotely subclasses methods.

    Just subclass me, add some remote methods using the `remote_method`
    decorator and instanciate me!
    """

    def __init__(self, app_name):
        super(prologin.web.TornadoApp, self).__init__([
            (r'/call/([0-9a-zA-Z_]+)', RemoteCallHandler),
        ], app_name)