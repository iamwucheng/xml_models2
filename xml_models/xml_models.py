__doc__ = """
Based on Django Database backed models, provides a means for mapping models
to xml, and specifying finders that map to a remote REST service.
"""

import datetime

import xpath_finder as xpath
from common_models import *
from dateutil.parser import parse as date_parser
from xpath_finder import MultipleNodesReturnedException


class XmlValidationError(Exception):
    pass


class BaseField:
    """
    All fields must specify an xpath as a keyword arg in their constructor.  Fields may optionally specify a
    default value using the default keyword arg.
    """

    def __init__(self, **kw):
        if 'xpath' not in kw:
            raise Exception('No XPath supplied for xml field')
        self.xpath = kw['xpath']
        self._default = kw.pop('default', None)
        self.__cached_value = None

    def _fetch_by_xpath(self, xml_doc, namespace):
        find = xpath.find_unique(xml_doc, self.xpath, namespace)
        if find is None:
            return self._default
        return find

    def _parse(self, xml, namespace):
        if not self.__cached_value:
            self.__cached_value = self.parse(xml, namespace)

        return self.__cached_value


class CharField(BaseField):
    """
    Returns the single value found by the xpath expression, as a string
    """

    def parse(self, xml, namespace):
        return self._fetch_by_xpath(xml, namespace)


class IntField(BaseField):
    """
    Returns the single value found by the xpath expression, as an int
    """

    def parse(self, xml, namespace):
        value = self._fetch_by_xpath(xml, namespace)
        if value:
            return int(value)
        return self._default


class DateField(BaseField):
    """
    Returns the single value found by the xpath expression, as a datetime.

    By default, expects dates that match the ISO8601 date format.  If a date_format keyword
    arg is supplied, that will be used instead. date_format should conform to strptime formatting options.

    If the service returns UTC offsets then a TZ aware datetime object will be returned.
    """

    def __init__(self, date_format=None, **kw):
        BaseField.__init__(self, **kw)
        self.date_format = date_format

    def parse(self, xml, namespace):
        value = self._fetch_by_xpath(xml, namespace)
        if value:
            if self.date_format:
                return datetime.datetime.strptime(value, self.date_format)
            return date_parser(value)
        return self._default


class FloatField(BaseField):
    """
    Returns the single value found by the xpath expression, as a float
    """

    def parse(self, xml, namespace):
        value = self._fetch_by_xpath(xml, namespace)
        if value:
            return float(value)
        return self._default


class BoolField(BaseField):
    """
    Returns the single value found by the xpath expression, as a boolean
    """

    def parse(self, xml, namespace):
        value = self._fetch_by_xpath(xml, namespace)
        if value is not None:
            if value.lower() == 'true':
                return True
            elif value.lower() == 'false':
                return False
        return self._default


class CollectionField(BaseField):
    """
    Returns a collection found by the xpath expression.

    Requires a field_type to be supplied, which can either be a field type, e.g. IntField, which returns a collection ints,
    or it can be a model type e.g. Person may contain a collection of Address objects.
    """

    def __init__(self, field_type, order_by=None, **kw):
        self.field_type = field_type
        self.order_by = order_by
        BaseField.__init__(self, **kw)

    def parse(self, xml, namespace):
        matches = xpath.find_all(xml, self.xpath, namespace)

        if BaseField not in self.field_type.__bases__:
            results = [self.field_type(xml=match) for match in matches]
        else:
            field = self.field_type(xpath='.')
            results = [field.parse(xpath.domify(match), namespace) for match in matches]
        if self.order_by:
            results.sort(lambda a, b: cmp(getattr(a, self.order_by), getattr(b, self.order_by)))
        return results


class OneToOneField(BaseField):
    def __init__(self, field_type, **kw):
        self.field_type = field_type
        BaseField.__init__(self, **kw)

    def parse(self, xml, namespace):
        match = xpath.find_all(xml, self.xpath, namespace)
        if len(match) > 1:
            raise MultipleNodesReturnedException
        if len(match) == 1:
            return self.field_type(xml=match[0])
        return self._default


class ModelBase(type):
    """
    Meta class for declarative xml_model building
    """

    def __init__(cls, name, bases, attrs):
        xml_fields = [field_name for field_name in attrs.keys() if isinstance(attrs[field_name], BaseField)]
        for field_name in xml_fields:
            setattr(cls, field_name, cls._get_xpath(field_name, attrs[field_name]))
            attrs[field_name]._name = field_name
        if "finders" in attrs:
            setattr(cls, "objects", ModelManager(cls, attrs["finders"]))
        else:
            setattr(cls, "objects", ModelManager(cls, {}))
        if "headers" in attrs:
            setattr(cls.objects, "headers", attrs["headers"])

    def _get_xpath(cls, field_name, field_impl):
        return property(fget=lambda cls: cls._parse_field(field_impl),
                        fset=lambda cls, value: cls._set_value(field_impl, value))


class Model:
    __metaclass__ = ModelBase
    __doc__ = """
    A model can be constructed with either an xml string, or an appropriate document supplied by
    the xpath_twister.domify() method.
    
    An example:
    
    class Person(xml_models.Model):
        namespace="urn:my.default.namespace"
        name = xml_models.CharField(xpath"/Person/@Name", default="John")
        nicknames = xml_models.CollectionField(CharField, xpath="/Person/Nicknames/Name")
        addresses = xml_models.CollectionField(Address, xpath="/Person/Addresses/Address")
        date_of_birth = xml_models.DateField(xpath="/Person/@DateOfBirth", date_format="%d-%m-%Y")
    """

    def __init__(self, xml=None, dom=None):
        self._xml = xml
        self._dom = dom
        self._cache = {}
        self.validate_on_load()


    def validate_on_load(self):
        """
        Override on your model to perform validation when the XML data is first passed in.

        This is to ensure the xml returned conforms to the validation rules. """
        pass

    def _get_tree(self):
        if self._dom is None:
            self._dom = xpath.domify(self._xml)
        return self._dom

    def _set_value(self, field, value):
        self._cache[field] = value

    def _parse_field(self, field):
        if field not in self._cache:
            namespace = None
            if hasattr(self, 'namespace'):
                namespace = self.namespace
            self._cache[field] = field.parse(self._get_tree(), namespace)
        return self._cache[field]
