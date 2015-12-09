"""
Package module for custom line parsers and profiles for &.console
"""
import importlib
from .. import libfields

def parse(Class, line,
		Indentation = libfields.Indentation.acquire,
		len = len,
		space = libfields.space,
		String = libfields.String
	):
	"""
	Parse a line of text into Fields.
	"""
	kws = Class.keywords
	cores = Class.cores
	translation_table = Class.translation
	constants = Class.constants

	# Calculate indentation
	xline = line.lstrip('\t')
	l = len(xline)
	indent = len(line) - l
	yield Indentation(indent)

	primaries = xline.rstrip('\n').split(' ')
	spaces = len(primaries) - 1

	# converts to spaces which are then split
	offset = 0
	for x in primaries:
		if x in kws:
			# constant keyword
			yield kws[x]
			offset += len(x)
		elif x in cores:
			yield cores[x]
			offset += len(x)
		else:
			# split delimiters
			*t, edge = x.translate(translation_table).split(' ')
			for y in t:
				if y:
					if y in kws:
						# constant keyword
						yield kws[y]
					elif x in cores:
						yield cores[y]
					else:
						yield String(y)

				# handle following delimiter
				offset += len(y)
				yield constants[xline[offset]]
				offset += 1

			# last field; no delimiter
			if edge:
				yield String(edge)
			offset += len(edge)
		offset += 1 # space

		if offset < l:
			yield space

class Line(libfields.Text):
	'Base class for profiled text lines.'
	__slots__ = libfields.Text.__slots__

	def reformat(self, list = list, str = str):
		"""
		Rebuild the Line contents.
		"""
		ind, *self.sequences = parse(self.__class__, str(self))

# Cache of profile -> Line subclass
cache = {}

extensions = {
	'.py': 'python',
	'.sh': 'shell',

	'.c': 'c',
	'.h': 'c',
	'.m': 'objectivec',
	'.java': 'java',

	'.hh': 'cxx',
	'.hpp': 'cxx',
	'.hxx': 'cxx',
	'.cxx': 'cxx',
	'.c++': 'cxx',
	'.cpp': 'cxx',
	'.cc': 'cxx',

	'.js': 'ecmascript',
	'.json': 'ecmascript',
	'.css': 'css',

	'.xsl': 'xslt',
	'.xslt': 'xslt',
	'.xml': 'xml',
	'.html': 'html',

	'.txt': 'text',
	None: 'text',
}

# Module attributes used to seed the translation table for parsing the line.
translation_set = (
	'terminators',
	'separators',
	'routers',
	'operators',
	'groupings',
	'quotations',
)

def table(language):
	"""
	Construct a table for string translate.
	"""
	for x in translation_set:
		yield from getattr(language, x).keys()

def aggregate(language):
	"""
	Aggregate the profile module translation set.
	"""
	for x in translation_set:
		yield from getattr(language, x).items()

def profile_module(name):
	"""
	Get the profile module for parsing lines for the given language.
	"""
	return importlib.import_module('.'+name, package=__name__)

def profile_from_filename(filename):
	"""
	Get the profile name from the given file name.
	"""
	ext = filename[filename.rfind('.'):]
	return extensions.get(ext, 'text')

def profile(name):
	"""
	Get the profile module's &Line subclass and module.
	"""
	if name in cache:
		return cache[name]

	mod = profile_module(name)

	pd = {x:' ' for x in table(mod)}
	pd['\n'] = None # implied with display

	trans = str.maketrans(pd)
	dexowords = getattr(mod, 'exowords', {})
	cf = {}
	cf.update([(x, 'keyword') for x in mod.keywords.values()])
	cf.update([(x, 'core') for x in mod.cores.values()])
	cf.update([(x, 'exoword') for x in dexowords.values()])

	class Subline(Line):
		__slots__ = Line.__slots__

		keywords = mod.keywords
		cores = mod.cores
		exowords = dexowords
		classifications = cf
		translation = trans
		constants = dict(aggregate(mod))
		routers = mod.routers
		quotations = mod.quotations
		parse = classmethod(parse)
		indentation = getattr(mod, 'indentation_width', 4)

	r = cache[name] = (Subline, mod)
	return r
