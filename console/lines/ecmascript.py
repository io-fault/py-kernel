"""
ECMA Script language profile.
"""
from .. import libfields

keyword_list = [
	'break',
	'case',
	'catch',
	'continue',
	'debugger',
	'default',
	'delete',
	'do',
	'else',
	'finally',
	'for',
	'function',
	'if',
	'in',
	'instanceof',
	'new',
	'return',
	'switch',
	'this',
	'throw',
	'try',
	'typeof',
	'var',
	'void',
	'while',
	'with',

	# reserved
	'class',
	'const',
	'enum',
	'export',
	'extends',
	'import',
	'super',

	'implements',
	'interface',
	'let',
	'package',
	'private',
	'protected',
	'public',
	'static',
	'yield',
]

core_list = [
	'prototype',
	'window',

	'null',
	'undefined',
	'true',
	'false',

	'NaN',
	'Infinity',
	'isNaN',
	'isFinite',

	'Arguments',
	'Array',
	'Boolean',
	'Date',
	'Error',
	'Function',
	'JSON',
	'Math',
	'Number',
	'Object',
	'RegExp',
	'String',

	'eval',
	'escape',
	'unescape',
	'parseInt',
	'parseFloat',

	'encodeURI',
	'decodeURI',
	'encodeURIComponent',
	'decodeURIComponent',

	'EvalError',
	'RangeError',
	'ReferenceError',
	'SyntaxError',
	'TypeError',
	'URIError',

	'setTimeout',
	'clearTimeout',
	'setInterval',
	'clearInterval',
	'setImmediate',
	'clearImmediate',
]

keywords = {y: y for y in map(libfields.String, keyword_list)}
cores = {y: y for y in map(libfields.String, core_list)}

terminators = {y: y for y in map(libfields.Constant, ";")}
separators = {y: y for y in map(libfields.Constant, ",")}
routers = {y: y for y in map(libfields.Constant, (".","-",">"))} # "->"; needs special handling
operators = {y: y for y in map(libfields.Constant, "@!&^*%+=-|\\/<>?~:")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ("'", '"',))}
