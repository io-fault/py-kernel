"""
Plain text
"""
from .. import libfields

keywords = cores = {}

terminators = {y: y for y in map(libfields.Constant, ":;.")}
separators = {y: y for y in map(libfields.Constant, ",")}
routers = {}
operators = {y: y for y in map(libfields.Constant, "@!&^*%+=-|\\/<>?~#")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ('"',))}
