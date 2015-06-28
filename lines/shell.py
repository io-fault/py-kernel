"""
Bourne Shell language profile.
"""
from .. import libfields

keyword_list = [
	'if', 'fi',
	'elif', 'else',
	'case', 'esac',
	'while', 'until',
	'for', 'in',
	'do', 'done',
	'break',
	'continue',
	'return',
	'function',
	'then',
]

core_list = [
	'export',
	'shift',
	'test',
	'expr',

	'printf',
	'echo',
	'read',

	'cd',
	'ls',
	'dirname',
	'pwd',

	'ln',
	'cp',

	'rm',
	'mkdir',
	'rmdir',
	'rmtree',

	'exec',
	'exit',

	'chmod',
	'chgrp',
	'chown',

	'touch',
	'cat',
	'which',
]

keywords = {y: y for y in map(libfields.String, keyword_list)}
cores = {y: y for y in map(libfields.String, core_list)}

terminators = {y: y for y in map(libfields.Constant, ";")}
separators = {y: y for y in map(libfields.Constant, ",")}
routers = {y: y for y in map(libfields.Constant, (".",))} # for common formatting
operators = {y: y for y in map(libfields.Constant, "!&^*%+=-|\\/<>")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ("'", '"',))}
