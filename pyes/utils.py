#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = 'Alberto Paro'
__all__ = ['clean_string', 'ResultSet', "ESRange", "ESRangeOp", "string_b64encode", "string_b64decode", "get_values"]
from types import NoneType
from django.db.models.manager import Manager
from django.db.models import Model
import datetime
import base64

def string_b64encode(s):
    """
    This function is useful to convert a string to a valid id to be used in ES.
    You can use it to generate an ID for urls or some texts
    """
    return base64.urlsafe_b64encode(s).strip('=')

def string_b64decode(s):
    return base64.urlsafe_b64decode(s + '=' * (len(s) % 4))

# Characters that are part of Lucene query syntax must be stripped
# from user input: + - && || ! ( ) { } [ ] ^ " ~ * ? : \
# See: http://lucene.apache.org/java/3_0_2/queryparsersyntax.html#Escaping
SPECIAL_CHARS = [33, 34, 38, 40, 41, 42, 45, 58, 63, 91, 92, 93, 94, 123, 124, 125, 126]
UNI_SPECIAL_CHARS = dict((c, None) for c in SPECIAL_CHARS)
STR_SPECIAL_CHARS = ''.join([chr(c) for c in SPECIAL_CHARS])

class ESRange(object):
    def __init__(self, field, from_value=None, to_value=None, include_lower=None,
                 include_upper=None, boost=None, **kwargs):
        """
        type can be "gt", "gte", "lt", "lte"
        
        """
        self.field = field
        self.from_value = from_value
        self.to_value = to_value
        self.type = type
        self.include_lower = include_lower
        self.include_upper = include_upper
        self.boost = boost

    def serialize(self):

        filters = {}
        if self.from_value is not None:
            filters['from'] = self.from_value
        if self.to_value is not None:
            filters['to'] = self.to_value
        if self.include_lower is not None:
            filters['include_lower'] = self.include_lower
        if self.include_upper is not None:
            filters['include_upper'] = self.include_upper
        if self.boost is not None:
            filters['boost'] = self.boost
        return self.field, filters

class ESRangeOp(ESRange):
    def __init__(self, field, op, value, boost=None):
        from_value = to_value = include_lower = include_upper = None
        if op == "gt":
            from_value = value
            include_lower = False
        elif op == "gte":
            from_value = value
            include_lower = True
        if op == "lt":
            to_value = value
            include_upper = False
        elif op == "lte":
            to_value = value
            include_upper = True
        super(ESRangeOp, self).__init__(field, from_value, to_value, \
                include_lower, include_upper, boost)

def clean_string(text):
    """
    Remove Lucene reserved characters from query string
    """
    if isinstance(text, unicode):
        return text.translate(UNI_SPECIAL_CHARS).strip()
    return text.translate(None, STR_SPECIAL_CHARS).strip()

class ResultSet(object):
    def __init__(self, results, fix_keys=True, clean_highlight=True):
        """
        results: an es query results dict
        fix_keys: remove the "_" from every key, useful for django views
        clean_highlight: removed empty highlight
        """
        self.results = results
        self._total = None
        self.valid = False
        self.facets = self.results.get('facets', {})
        if 'hits' in self.results:
            self.valid = True
            self.results = self.results['hits']
        if fix_keys:
            self.fix_keys()
        if clean_highlight:
            self.clean_highlight()

    @property
    def total(self):
        if self._total is None:
            self._total = 0
            if self.valid:
                self._total = self.results.get("total", 0)
        return self._total

    def fix_keys(self):
        """
        Remove the _ from the keys of the results
        """
        if not self.valid:
            return

        for hit in self.results['hits']:
            for key, item in hit.items():
                if key.startswith("_"):
                    hit[key[1:]] = item
                    del hit[key]

    def clean_highlight(self):
        """
        Remove the empty highlight
        """
        if not self.valid:
            return

        for hit in self.results['hits']:
            if 'highlight' in hit:
                hl = hit['highlight']
                for key, item in hl.items():
                    if not item:
                        del hl[key]

    def __getattr__(self, name):
        if name in self.results:
            return self.results[name]

def keys_to_string(data):
    """
    Function to convert all the unicode keys in string keys
    """
    if isinstance(data, dict):
        for key in list(data.keys()):
            if isinstance(key, unicode):
                value = data[key]
                val = keys_to_string(value)
                del data[key]
                data[key.encode("utf8", "ignore")] = val
    return data

#--- taken from http://djangosnippets.org/snippets/2278/

def get_values(instance, go_into={}, exclude=(), extra=(), skip_none=False):
    """
    Transforms a django model instance into an object that can be used for
    serialization. 
    @param instance(django.db.models.Model) - the model in question
    @param go_into(dict) - relations with other models that need expanding
    @param exclude(tuple) - fields that will be ignored
    @param extra(tuple) - additional functions/properties which are not fields
    @param skip_none(bool) - skip None field

    Usage:
    get_values(MyModel.objects.get(pk=187),
               {'user': {'go_into': ('clan',),
                         'exclude': ('crest_blob',),
                         'extra': ('get_crest_path',)}},
               ('image'))

    """

    SIMPLE_TYPES = (int, long, str, list, dict, tuple, bool, float, bool,
                    unicode, NoneType)

    if not isinstance(instance, Model):
        raise TypeError("Argument is not a Model")

    value = {
        'pk': instance.pk,
    }

    # check for simple string instead of tuples
    # and dicts; this is shorthand syntax
    if isinstance(go_into, str):
        go_into = {go_into: {}}

    if isinstance(exclude, str):
        exclude = (exclude,)

    if isinstance(extra, str):
        extra = (extra,)

    # process the extra properties/function/whatever
    for field in extra:
        property = getattr(instance, field)

        if callable(property):
            property = property()

        if skip_none and property is None:
            continue
        elif isinstance(property, SIMPLE_TYPES):
            value[field] = property
        else:
            value[field] = repr(property)

    field_options = instance._meta.get_all_field_names()
    for field in field_options:
        try:
            property = getattr(instance, field)
        except:
            continue
        if skip_none and property is None:
            continue

        if field in exclude or field[0] == '_' or isinstance(property, Manager):
            # if it's in the exclude tuple, ignore it 
            # if it's a "private" field, ignore it 
            # if it's an instance of manager (this means a more complicated
            # relationship), ignore it 
            continue
        elif go_into.has_key(field):
            # if it's in the go_into dict, make a recursive call for that field
            try:
                field_go_into = go_into[field].get('go_into', {})
            except AttributeError:
                field_go_into = {}

            try:
                field_exclude = go_into[field].get('exclude', ())
            except AttributeError:
                field_exclude = ()

            try:
                field_extra = go_into[field].get('extra', ())
            except AttributeError:
                field_extra = ()

            value[field] = get_values(property,
                                      field_go_into,
                                      field_exclude,
                                      field_extra, skip_none=skip_none)
        else:
            if isinstance(property, Model):
                # if it's a model, we need it's PK #
                value[field] = property.pk
            elif isinstance(property, (datetime.date,
                                       datetime.time,
                                       datetime.datetime)):
                value[field] = property
            else:
                # else, we just put the value #
                if callable(property):
                    property = property()

                if isinstance(property, SIMPLE_TYPES):
                    value[field] = property
                else:
                    value[field] = repr(property)

    return value