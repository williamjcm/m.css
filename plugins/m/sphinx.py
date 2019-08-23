#
#   This file is part of m.css.
#
#   Copyright © 2017, 2018, 2019 Vladimír Vondruš <mosra@centrum.cz>
#
#   Permission is hereby granted, free of charge, to any person obtaining a
#   copy of this software and associated documentation files (the "Software"),
#   to deal in the Software without restriction, including without limitation
#   the rights to use, copy, modify, merge, publish, distribute, sublicense,
#   and/or sell copies of the Software, and to permit persons to whom the
#   Software is furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included
#   in all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#   THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#   FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#   DEALINGS IN THE SOFTWARE.
#

import logging
import os
import re
from typing import Dict
from urllib.parse import urljoin
import zlib

from docutils import nodes, utils
from docutils.parsers import rst
from docutils.parsers.rst import directives
from docutils.parsers.rst.roles import set_classes
from docutils.parsers.rst.states import Inliner

from pelican import signals

module_doc_output = None
class_doc_output = None
enum_doc_output = None
function_doc_output = None
property_doc_output = None
data_doc_output = None

class PyModule(rst.Directive):
    final_argument_whitespace = True
    has_content = True
    required_arguments = 1
    option_spec = {'summary': directives.unchanged}

    def run(self):
        module_doc_output[self.arguments[0]] = {
            'summary': self.options.get('summary', ''),
            'content': '\n'.join(self.content)
        }
        return []

class PyClass(rst.Directive):
    final_argument_whitespace = True
    has_content = True
    required_arguments = 1
    option_spec = {'summary': directives.unchanged}

    def run(self):
        class_doc_output[self.arguments[0]] = {
            'summary': self.options.get('summary', ''),
            'content': '\n'.join(self.content)
        }
        return []

class PyEnum(rst.Directive):
    final_argument_whitespace = True
    has_content = True
    required_arguments = 1
    option_spec = {'summary': directives.unchanged}

    def run(self):
        enum_doc_output[self.arguments[0]] = {
            'summary': self.options.get('summary', ''),
            'content': '\n'.join(self.content)
        }
        return []

# List option (allowing multiple arguments). See _docutils_assemble_option_dict
# in python.py for details.
def directives_unchanged_list(argument):
    return [directives.unchanged(argument)]

class PyFunction(rst.Directive):
    final_argument_whitespace = True
    has_content = True
    required_arguments = 1
    option_spec = {'summary': directives.unchanged,
                   'param': directives_unchanged_list,
                   'return': directives.unchanged}

    def run(self):
        # Check that params are parsed properly, turn them into a dict. This
        # will blow up if the param name is not specified.
        params = {}
        for name, content in self.options.get('param', []):
            if name in params: raise KeyError(f"duplicate param {name}")
            params[name] = content

        function_doc_output[self.arguments[0]] = {
            'summary': self.options.get('summary', ''),
            'params': params,
            'return': self.options.get('return'),
            'content': '\n'.join(self.content)
        }
        return []

class PyProperty(rst.Directive):
    final_argument_whitespace = True
    has_content = True
    required_arguments = 1
    option_spec = {'summary': directives.unchanged}

    def run(self):
        property_doc_output[self.arguments[0]] = {
            'summary': self.options.get('summary', ''),
            'content': '\n'.join(self.content)
        }
        return []

class PyData(rst.Directive):
    final_argument_whitespace = True
    has_content = True
    required_arguments = 1
    option_spec = {'summary': directives.unchanged}

    def run(self):
        data_doc_output[self.arguments[0]] = {
            'summary': self.options.get('summary', ''),
            'content': '\n'.join(self.content)
        }
        return []

# Modified from abbr / gh / gl / ... to add support for queries and hashes
link_regexp = re.compile(r'(?P<title>.*) <(?P<link>[^?#]+)(?P<hash>[?#].+)?>')

def parse_link(text):
    link = utils.unescape(text)
    m = link_regexp.match(link)
    if m:
        title, link, hash = m.group('title', 'link', 'hash')
        if not hash: hash = '' # it's None otherwise
    else:
        title, hash = '', ''

    return title, link, hash

intersphinx_inventory = {}
intersphinx_name_prefixes = []

# Basically a copy of sphinx.util.inventory.InventoryFile.load_v2. There's no
# documentation for this, it seems.
def parse_intersphinx_inventory(file, base_url, inventory, css_classes):
    # Parse the header, uncompressed
    inventory_version = file.readline().rstrip()
    if inventory_version != b'# Sphinx inventory version 2':
        raise ValueError(f"Unsupported inventory version header: {inventory_version}") # pragma: no cover
    # those two are not used at the moment, just for completeness
    project = file.readline().rstrip()[11:]
    version = file.readline().rstrip()[11:]
    line = file.readline()
    if b'zlib' not in line:
        raise ValueError(f"invalid inventory header (not compressed): {line}") # pragma: no cover

    # Decompress the rest. Again mostly a copy of the sphinx code.
    for line in zlib.decompress(file.read()).decode('utf-8').splitlines():
        m = re.match(r'(?x)(.+?)\s+(\S*:\S*)\s+(-?\d+)\s+(\S+)\s+(.*)',
                         line.rstrip())
        if not m: # pragma: no cover
            print(f"wait what is this line?! {line}")
            continue
        # What the F is prio for
        name, type, prio, location, title = m.groups()

        # What is this?!
        if location.endswith('$'): location = location[:-1] + name

        # The original code `continue`s in this case. I'm asserting. Fix your
        # docs.
        assert not(type == 'py:module' and type in inventory and name in inventory[type]), "Well dang, we hit that bug in 1.1 that I didn't want to work around" # pragma: no cover

        # Prepend base URL and add to the inventory
        inventory.setdefault(type, {})[name] = (urljoin(base_url, location), title, css_classes)

def parse_intersphinx_inventories(input, inventories):
    global intersphinx_inventory, intersphinx_name_prefixes
    intersphinx_inventory = {}
    intersphinx_name_prefixes = ['']

    for f in inventories:
        inventory, base_url = f[:2]
        prefixes = f[2] if len(f) > 2 else []
        css_classes = f[3] if len(f) > 3 else []

        intersphinx_name_prefixes += prefixes
        with open(os.path.join(input, inventory), 'rb') as file:
            parse_intersphinx_inventory(file, base_url, intersphinx_inventory, css_classes)

# Matches e.g. py:function in py:function:open
_type_prefix_re = re.compile(r'([a-z0-9]{,3}:[a-z0-9]{3,}):')
_function_types = ['py:function', 'py:classmethod', 'py:staticmethod', 'py:method', 'c:function']

def ref(name, rawtext, text, lineno, inliner: Inliner, options={}, content=[]):
    title, target, hash = parse_link(text)

    # Otherwise adding classes to the options behaves globally (uh?)
    _options = dict(options)
    set_classes(_options)
    # Avoid assert on adding to undefined member later
    if 'classes' not in _options: _options['classes'] = []

    # Iterate through all prefixes, try to find the name
    global intersphinx_inventory, intersphinx_name_prefixes
    for prefix in intersphinx_name_prefixes:
        found = None

        # If the target is prefixed with a type, try looking up that type
        # directly. The implicit link title is then without the type.
        m = _type_prefix_re.match(target)
        if m:
            type = m.group(1)
            prefixed = prefix + target[len(type) + 1:]
            # ALlow trailing () on functions here as well
            if prefixed.endswith('()') and type in _function_types:
                prefixed = prefixed[:-2]
            if type in intersphinx_inventory and prefixed in intersphinx_inventory[type]:
                target = target[len(type) + 1:]
                found = type, intersphinx_inventory[m.group(1)][prefixed]

        prefixed = prefix + target

        # If the target looks like a function, look only in functions and strip
        # the trailing () as the inventory doesn't have that
        if not found and prefixed.endswith('()'):
            prefixed = prefixed[:-2]
            for type in _function_types:
                if type in intersphinx_inventory and prefixed in intersphinx_inventory[type]:
                    found = type, intersphinx_inventory[type][prefixed]
                    break

        # Iterate through whitelisted types otherwise. Skipping
        # 'std:pdbcommand', 'std:cmdoption', 'std:term', 'std:label',
        # 'std:opcode', 'std:envvar', 'std:token', 'std:doc', 'std:2to3fixer'
        # and unknown domains such as c++ for now as I'm unsure about potential
        # name clashes.
        if not found:
            for type in ['py:exception', 'py:attribute', 'py:method', 'py:data', 'py:module', 'py:function', 'py:class', 'py:classmethod', 'py:staticmethod', 'c:var', 'c:type', 'c:function', 'c:member', 'c:macro']:
                if type in intersphinx_inventory and prefixed in intersphinx_inventory[type]:
                    found = type, intersphinx_inventory[type][prefixed]

        if found:
            url, link_title, css_classes = found[1]
            if title:
                use_title = title
            elif link_title != '-':
                use_title = link_title
            else:
                use_title = target
                # Add () to function refs
                if found[0] in _function_types and not target.endswith('()'):
                    use_title += '()'

            _options['classes'] += css_classes
            node = nodes.reference(rawtext, use_title, refuri=url + hash, **_options)
            return [node], []

    if title:
        logging.warning("Sphinx symbol `{}` not found, rendering just link title".format(target))
        node = nodes.inline(rawtext, title, **_options)
    else:
        logging.warning("Sphinx symbol `{}` not found, rendering as monospace".format(target))
        node = nodes.literal(rawtext, target, **_options)
    return [node], []

def register_mcss(mcss_settings, module_doc_contents, class_doc_contents, enum_doc_contents, function_doc_contents, property_doc_contents, data_doc_contents, **kwargs):
    global module_doc_output, class_doc_output, enum_doc_output, function_doc_output, property_doc_output, data_doc_output
    module_doc_output = module_doc_contents
    class_doc_output = class_doc_contents
    enum_doc_output = enum_doc_contents
    function_doc_output = function_doc_contents
    property_doc_output = property_doc_contents
    data_doc_output = data_doc_contents

    parse_intersphinx_inventories(input=mcss_settings['INPUT'],
         inventories=mcss_settings.get('M_SPHINX_INVENTORIES', []))

    rst.directives.register_directive('py:module', PyModule)
    rst.directives.register_directive('py:class', PyClass)
    rst.directives.register_directive('py:enum', PyEnum)
    rst.directives.register_directive('py:function', PyFunction)
    rst.directives.register_directive('py:property', PyProperty)
    rst.directives.register_directive('py:data', PyData)

    rst.roles.register_local_role('ref', ref)

def _pelican_configure(pelicanobj):
    # For backwards compatibility, the input directory is pelican's CWD
    parse_intersphinx_inventories(input=os.getcwd(),
         inventories=pelicanobj.settings.get('M_SPHINX_INVENTORIES', []))

def register(): # for Pelican
    rst.roles.register_local_role('ref', ref)

    signals.initialized.connect(_pelican_configure)