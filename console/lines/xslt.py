"""
XSLT language profile.
"""
import itertools
from .. import libfields

indentation_width = 1

_keywords = [
	'include', 'import',
	'attribute',
	'element',
	'call-template',
	'with-param',
	'template',
	'transform',

	'if',
	'choose',
	'when',
	'otherwise',
	'for-each',
	'apply-templates',
	'sort',

	'param',
	'variable',

	'value-of',
	'copy-of',
	'text',
]
keywords = {y: y for y in map(libfields.String, _keywords)}
cores = {}

terminators = {y: y for y in map(libfields.Constant, "<>")}
separators = {}
routers = {':': libfields.Constant(":")}
operators = {y: y for y in map(libfields.Constant, ";@!&^*%+=\\/<>?~")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ("'", '"',))}
