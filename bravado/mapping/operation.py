import logging

from bravado import swagger_type
from bravado.response import post_receive, HTTPFuture
from bravado.exception import SwaggerError
from bravado.mapping.param import Param, marshal_param

log = logging.getLogger(__name__)


class Operation(object):
    """Perform a request by taking the kwargs passed to the call and
    constructing an HTTP request.

    :type swagger_spec: :class:`Spec`
    :param path_name: path of the operation. e.g. /pet/{petId}
    :param http_method: get/put/post/delete/etc
    :param op_spec: operation specification in dict form
    """
    def __init__(self, swagger_spec, path_name, http_method, op_spec):
        self.swagger_spec = swagger_spec
        self.path_name = path_name
        self.http_method = http_method
        self.op_spec = op_spec

        # generated by @property when necessary since this is optional.
        # Diverges from op_* naming scheme since it is called 'operation_id'
        # in the Swagger 2.0 Spec.
        self._operation_id = None

        # (key, value) = (param name, Param)
        self.params = {}

    @classmethod
    def from_spec(cls, swagger_spec, path_name, http_method, op_spec):
        """
        Creates a :class:`Operation` and builds up its list of :class:`Param`s

        :param swagger_spec: :class:`Spec`
        :param path_name: path of the operation. e.g. /pet/{petId}
        :param http_method: get/put/post/delete/etc
        :param op_spec: operation specification in dict form
        :rtype: :class:`Operation`
        """
        op = cls(swagger_spec, path_name, http_method, op_spec)
        op.build_params()
        return op

    def build_params(self):
        """
        Builds up the list of this operations parameters taking into account
        parameters that may be available for this operation's path component.
        """
        self.params = {}
        op_param_specs = self.op_spec.get('parameters', [])
        path_specs = self.swagger_spec.spec_dict['paths'][self.path_name]
        path_param_specs = path_specs.get('parameters', [])
        param_specs = op_param_specs + path_param_specs

        for param_spec in param_specs:
            param = Param(self.swagger_spec, param_spec)
            self.params[param.name] = param

    @property
    def operation_id(self):
        """A friendly name for the operation. The id MUST be unique among all
        operations described in the API. Tools and libraries MAY use the
        operation id to uniquely identify an operation.

        This this field is not required, it will be generated when needed.

        :rtype: str
        """
        if self._operation_id is None:
            self._operation_id = self.op_spec.get('operationId')
            if self._operation_id is None:
                # build based on the http method and request path
                self._operation_id = (self.http_method + '_' + self.path_name)\
                    .replace('/', '_')\
                    .replace('{', '_')\
                    .replace('}', '_')\
                    .replace('__', '_')\
                    .strip('_')
        return self._operation_id

    def __repr__(self):
        return u"%s(%s)" % (self.__class__.__name__, self.operation_id)

    def construct_request(self, **kwargs):
        """
        :param kwargs: parameter name/value pairs to pass to the invocation of
            the operation
        :return: request in dict form
        """
        request_options = kwargs.pop('_request_options', {})
        request = {
            'method': self.http_method,
            'url': self.swagger_spec.api_url + self.path_name,
            'params': {},
            'headers': request_options.get('headers', {}),
        }
        self.construct_params(request, kwargs)
        return request

    def construct_params(self, request, op_kwargs):
        """
        Given the parameters passed to the operation invocation, validates and
        marshals the parmameters into the request dict.

        :type request: dict
        :param op_kwargs: the kwargs passed to the operation invocation
        :raises: TypeError on extra parameters or when a required parameter
            is not supplied.
        """
        current_params = self.params.copy()
        for param_name, param_value in op_kwargs.iteritems():
            param = current_params.pop(param_name, None)
            if param is None:
                raise TypeError("{0} does not have parameter {1}".format(
                    self.operation_id, param_name))
            marshal_param(param, param_value, request)

        # Check required params and non-required params with a 'default' value
        for remaining_param in current_params.itervalues():
            if remaining_param.required:
                raise TypeError('{0} is a required parameter'.format(remaining_param.name))
            if not remaining_param.required and remaining_param.has_default():
                marshal_param(remaining_param, None, request)

    def __call__(self, **kwargs):
        # TODO: rewrite/simplify
        log.debug(u"%s(%s)" % (self.operation_id, kwargs))
        request = self.construct_request(**kwargs)

        def response_future(response, **kwargs):
            # Assume status is OK, an exception would have been raised already
            if not response.text:
                return None

            status_code = str(response.status_code)
            # Handle which repsonse to activate given status_code
            default_response_spec = self.op_spec['responses'].get('default', None)
            response_spec = self.op_spec['responses'].get(status_code, default_response_spec)
            if response_spec is None:
                # reponse code doesn't match and no default provided
                if status_code == '200':
                    # it was obviously successful
                    log.warn("Op {0} was successful by didn't match any responses".format(self.operation_id))
                else:
                    raise SwaggerError("Response doesn't match any expected responses: {0}".format(response))

            response_dict = response.json()

            if response_spec and 'schema' in response_spec:
                swagger_type_ = swagger_type.get_swagger_type(response_spec['schema'])
            else:
                swagger_type_ = None

            log.debug('response_dict = %s' % response_dict)
            log.debug('response_spec = %s' % response_spec)
            log.debug('swagger_type  = %s' % swagger_type_)

            return post_receive(
                response_dict,
                swagger_type_,
                self.swagger_spec.definitions,
                **kwargs)

        return HTTPFuture(self.swagger_spec.http_client, request, response_future)
