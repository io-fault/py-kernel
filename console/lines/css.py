"""
Cascading Style Sheets language profile.
"""
from .. import libfields

keyword_list = [
	'@import',
	'@media',
	'@charset',
	'@page',
]

core_list = [
	'body',
	'html',
]

keywords = {y: y for y in map(libfields.String, keyword_list)}
cores = {y: y for y in map(libfields.String, core_list)}

terminators = {y: y for y in map(libfields.Constant, ";")}
separators = {y: y for y in map(libfields.Constant, ":,")}
routers = {y: y for y in map(libfields.Constant, (".","-"))}
operators = {y: y for y in map(libfields.Constant, "!&^*%+=-|\\/<>?~")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ("'", '"',))}
