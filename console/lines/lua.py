"""
Lua language profile.
"""
from .. import libfields

keyword_list = [
	"and",
	"break",
	"do",
	"else",
	"elseif",
	"end",
	"for",
	"function",
	"goto",
	"if",
	"in",
	"local",
	"not",
	"or",
	"repeat",
	"return",
	"then",
	"until",
	"while",

	"true",
	"false",
	"nil",
]

core_list = [
]

exoword_list = [
]

keywords = {y: y for y in map(libfields.String, keyword_list)}
cores = {y: y for y in map(libfields.String, core_list)}
exowords = {y: y for y in map(libfields.String, exoword_list)}

terminators = {y: y for y in map(libfields.Constant, ";")}
separators = {y: y for y in map(libfields.Constant, ",")}
routers = {y: y for y in map(libfields.Constant, (".","-",">"))} # "->"; needs special handling
operators = {y: y for y in map(libfields.Constant, "@!&^*%+=-|\\/<>?~:")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ("'", '"',))}
