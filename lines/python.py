"""
Python language profile.
"""
import keyword
import itertools
from .. import libfields

keywords = {y: y for y in map(libfields.String, keyword.kwlist)}
cores = {y: y for y in map(libfields.String, __builtins__.keys())}

terminators = {y: y for y in map(libfields.Constant, ":;#")}
separators = {y: y for y in map(libfields.Constant, ",")}
routers = {y: y for y in map(libfields.Constant, ".")}
operators = {y: y for y in map(libfields.Constant, "@!&^*%+=-|\\/<>?~")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ("'", '"',))}
