"""
C language profile.
"""
from .. import libfields
from . import c

keyword_list = [
	'alignas',
	'alignof',
	'and',
	'and_eq',
	'asm',
	'auto',
	'bitand',
	'bitor',
	'bool',
	'break',
	'case',
	'catch',
	'char',
	'char16_t',
	'char32_t',
	'class',
	'compl',
	'concept',
	'const',
	'constexpr',
	'const_cast',
	'continue',
	'decltype',
	'default',
	'delete',
	'do',
	'double',
	'dynamic_cast',
	'else',
	'enum',
	'explicit',
	'export',
	'extern',
	'false',
	'float',
	'for',
	'friend',
	'goto',
	'if',
	'inline',
	'int',
	'long',
	'mutable',
	'namespace',
	'new',
	'noexcept',
	'not',
	'not_eq',
	'nullptr',
	'operator',
	'or',
	'or_eq',
	'private',
	'protected',
	'public',
	'register',
	'reinterpret_cast',
	'requires',
	'return',
	'short',
	'signed',
	'sizeof',
	'static',
	'static_assert',
	'static_cast',
	'struct',
	'switch',
	'template',
	'this',
	'thread_local',
	'throw',
	'true',
	'try',
	'typedef',
	'typeid',
	'typename',
	'union',
	'unsigned',
	'using',
	'virtual',
	'void',
	'volatile',
	'wchar_t',
	'while',
	'xor',
	'xor_eq',
]

core_list = [
	'unique_ptr',
	'shared_ptr',
	'weak_ptr',
	'auto_ptr',

	'align',
	'addressof',
]

core_list.extend(c.core_list)

keywords = {y: y for y in map(libfields.String, keyword_list)}
cores = {y: y for y in map(libfields.String, core_list)}
exowords = c.exowords

terminators = {y: y for y in map(libfields.Constant, ";")}
separators = {y: y for y in map(libfields.Constant, ",")}
routers = {y: y for y in map(libfields.Constant, (".","-",">"))} # "->"; needs special handling
operators = {y: y for y in map(libfields.Constant, "@!&^*%+=-|\\/<>?~:")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ("'", '"',))}
