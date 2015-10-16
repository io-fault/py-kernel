"""
Provides common mappings for keyboard based navigation and control.
"""
from ...terminal import library as libterminal

class Mapping(object):
	"""
	A mapping of commands and keys for binding shortcuts.

	A mapping "context" is a reference to a target. For instance, a field, line, or
	container.
	"""
	def __init__(self, default = None):
		self.default = default
		self.mapping = dict()
		self.reverse = dict()

	def assign(self, character, context, action, parameters = ()):
		"""
		"""
		key = (context, action, parameters)
		if key not in self.mapping:
			self.mapping[key] = set()

		value = character
		self.mapping[key].add(value)
		self.reverse[value] = key

	def event(self, key):
		index = (key.type, key.identity, key.modifiers)
		return self.reverse.get(index, self.default)

shift = libterminal.Modifiers.construct(shift=True)
meta = libterminal.Modifiers.construct(meta=True)
controlmod = libterminal.Modifiers.construct(control=True)
shiftmeta = libterminal.Modifiers.construct(meta=True, shift=True)
literal = lambda x: ('literal', x, 0)
caps = lambda x: ('literal', x, shift)
controlk = lambda x: ('control', x, controlmod)
shiftcontrolk = lambda x: ('control', x, shift)
nav = lambda x: ('navigation', x, 0)
shiftnav = lambda x: ('navigation', x, shift)
delta = lambda x: ('delta', x, 0)

# events trapped by the console
trap = Mapping()
trap.assign(('escaped', '~', 0), 'console', ('process', 'exit'))
trap.assign(('escaped', '`', 0), 'console', ('toggle', 'prompt'))
# pane management
trap.assign(('escaped', 'j', 0), 'console', ('pane', 'rotate', 'refraction'), (1,))
trap.assign(('escaped', 'k', 0), 'console', ('pane', 'rotate', 'refraction'), (-1,))

trap.assign(('control', 'tab', meta), 'console', ('console', 'rotate', 'pane', 'forward'))
trap.assign(('control', 'tab', shiftmeta), 'console', ('console', 'rotate', 'pane', 'backward'))
trap.assign(('escaped', 'o', 0), 'console', ('prepare', 'open'))

# refraction control mapping
control = Mapping(('refraction', ('navigation', 'jump', 'character'), ()))
ca = control.assign

# distribution of commands across the vertical range.
ca(literal('y'), 'refraction', ('distribute', 'one'))
ca(caps('y'), 'refraction', ('distribute', 'sequence'))

# control
ca(controlk('c'), 'refraction', ('interrupt',))
ca(('escaped', 'c', 0), 'refraction', ('copy',))

#control.assign(('control', 'escape', 0), 'refraction', ('transition', 'exit'))
ca(('control', 'space', 0), 'refraction', ('control', 'space'))
ca(('control', 'return', 0), 'refraction', ('control', 'return'))

ca(literal('f'), 'refraction', ('navigation', 'horizontal', 'forward'))
ca(literal('d'), 'refraction', ('navigation', 'horizontal', 'backward'))
ca(caps('f'), 'refraction', ('navigation', 'horizontal', 'stop'))
ca(caps('d'), 'refraction', ('navigation', 'horizontal', 'start'))
ca(controlk('f'), 'refraction', ('navigation',))
ca(controlk('d'), 'refraction', ('navigation',))

ca(literal('s'), 'refraction', ('select', 'series',))
ca(caps('s'), 'refraction', ('select', 'single')) # spare
ca(controlk('s'), 'refraction', ('console', 'search'))

ca(literal('e'), 'refraction', ('navigation', 'vertical', 'sections'))
ca(caps('e'), 'refraction', ('navigation', 'vertical', 'paging'))
ca(controlk('e'), 'refraction', ('print', 'unit'))

# temporary
ca(controlk('w'), 'refraction', ('console', 'save'))

ca(literal('j'), 'refraction', ('navigation', 'vertical', 'forward'))
ca(literal('k'), 'refraction', ('navigation', 'vertical', 'backward'))
ca(caps('j'), 'refraction', ('navigation', 'vertical', 'stop'))
ca(caps('k'), 'refraction', ('navigation', 'vertical', 'start'))
ca(('control', 'newline', 0), 'refraction', ('navigation', 'void', 'forward'))
ca(controlk('k'), 'refraction', ('navigation', 'void', 'backward'))

ca(caps('o'), 'refraction', ('open', 'behind',))
ca(literal('o'), 'refraction', ('open', 'ahead'))
ca(controlk('o'), 'refraction', ('open', 'into'))

ca(literal('q'), 'refraction', ('navigation', 'range', 'enqueue'))
ca(caps('q'), 'refraction', ('navigation', 'range', 'dequeue'))
ca(controlk('q'), 'refraction', ('',)) # spare

ca(literal('v'), 'refraction', ('navigation', 'void', 'forward',))
ca(caps('v'), 'refraction', ('navigation', 'void', 'backward',))
ca(controlk('v'), 'refraction', ('',)) # spare

ca(literal('t'), 'refraction', ('delta', 'translocate',))
ca(caps('t'), 'refraction', ('delta', 'transpose',))
ca(controlk('t'), 'refraction', ('delta', 'truncate'))

ca(literal('z'), 'refraction', ('place', 'stop',))
ca(caps('z'), 'refraction', ('place', 'start',))
ca(controlk('z'), 'refraction', ('place', 'expand'))

# [undo] log
ca(literal('u'), 'refraction', ('delta', 'undo',))
ca(caps('u'), 'refraction', ('delta', 'redo',))
ca(controlk('u'), 'refraction', ('redo',))

ca(literal('a'), 'refraction', ('select', 'adjacent', 'local'))
ca(caps('a'), 'refraction', ('select', 'adjacent'))

ca(literal('b'), 'refraction', ('select', 'block'))
ca(caps('b'), 'refraction', ('select', 'outerblock'))

ca(literal('n'), 'refraction', ('delta', 'split',))
ca(caps('n'), 'refraction', ('delta', 'join',))
ca(controlk('n'), 'refraction', ('',))

ca(literal('p'), 'refraction', ('paste', 'after'))
ca(caps('p'), 'refraction', ('paste', 'before',))
ca(controlk('p'), 'refraction', ('paste', 'into',))

ca(literal('l'), 'refraction', ('select', 'horizontal', 'line'))
ca(caps('l'), 'refraction', ('select', 'vertical', 'line'))
ca(controlk('l'), 'refraction', ('console', 'seek', 'line'))

for i in range(10):
	control.assign(literal(str(i)), 'refraction', ('index', 'reference'))

# character level movement
ca(controlk('space'), 'refraction', ('navigation', 'forward', 'character'))
ca(delta('delete'), 'refraction', ('navigation', 'backward', 'character'))

ca(nav('left'), 'refraction', ('window', 'horizontal', 'forward'))
ca(nav('right'), 'refraction', ('window', 'horizontal', 'backward'))
ca(nav('down'), 'refraction', ('window', 'vertical', 'forward'))
ca(nav('up'), 'refraction', ('window', 'vertical', 'backward'))

ca(literal('m'), 'refraction', ('menu', 'primary'))
ca(caps('m'), 'refraction', ('menu', 'secondary'))

ca(literal('i'), 'refraction', ('transition', 'edit'),)
ca(caps('i'), 'refraction', ('delta', 'split'),) # split field

ca(literal('c'), 'refraction', ('delta', 'substitute'),)
ca(caps('c'), 'refraction', ('delta', 'substitute', 'previous'),) # remap this

ca(literal('x'), 'refraction', ('delta', 'delete', 'forward'),)
ca(caps('x'), 'refraction', ('delta', 'delete', 'backward'),)
ca(controlk('x'), 'selection', ('remove', 'selection')) # cut line

ca(literal('r'), 'refraction', ('delta', 'replace', 'character'),)
ca(caps('r'), 'refraction', ('delta', 'replace'),)

ca(('control', 'tab', 0), 'refraction', ('delta', 'indent', 'increment'))
ca(('control', 'tab', shift), 'refraction', ('delta', 'indent', 'decrement'))
ca(controlk('v'), 'refraction', ('delta', 'indent', 'null'))

ca(('control', 'c', 1), 'control', ('navigation', 'console')) # focus control console
del ca

# insert mode
edit = Mapping(default = ('refraction', ('delta', 'insert', 'character'), ())) # insert
ea = edit.assign
ea(('control', 'nul', 0), 'refraction', ('delta', 'insert', 'space')) # literal space

ea(controlk('c'), 'refraction', ('edit', 'abort'))
ea(controlk('d'), 'refraction', ('edit', 'commit')) # eof
ea(controlk('v'), 'refraction', ('edit', 'capture'))

ea(('delta', 'delete', 0), 'refraction', ('delta', 'delete', 'backward'))
ea(('delta', 'backspace', 0), 'refraction', ('delta', 'delete', 'backward'))
ea(controlk('x'), 'refraction', ('delta', 'delete', 'forward'))

# these are mapped to keyboard names in order to allow class-level overrides
# and/or context sensitive action selection
ea(('control', 'space', 0), 'refraction', ('delta', 'edit', 'insert', 'space'))
ea(('control', 'tab', 0), 'refraction', ('edit', 'tab'))
ea(('control', 'tab', shift), 'refraction', ('edit', 'shift', 'tab'))
ea(('control', 'return', 0), 'refraction', ('edit', 'return'))

ea(('navigation', 'left', 0), 'refraction', ('navigation', 'backward', 'character'))
ea(('navigation', 'right', 0), 'refraction', ('navigation', 'forward', 'character'))
ea(('navigation', 'up', 0), 'refraction', ('navigation', 'beginning'))
ea(('navigation', 'down', 0), 'refraction', ('navigation', 'end'))

ea(controlk('u'), 'refraction', ('delta', 'delete', 'tobol'))
ea(controlk('k'), 'refraction', ('delta', 'delete', 'toeol'))

ea(controlk('w'), 'refraction', ('delta', 'delete', 'backward', 'adjacent', 'class'))
ea(controlk('t'), 'refraction', ('delta', 'delete', 'forward', 'adjacent', 'class'))

ea(controlk('a'), 'refraction', ('navigation', 'move', 'bol'))
ea(controlk('e'), 'refraction', ('navigation', 'move', 'eol'))
del ea

# capture keystroke
capture = Mapping(default = ('refraction', ('capture',), ()))

# field creation and type selection
types = Mapping()
field_type_mnemonics = {
	'i': 'integer',
	't': 'text',
	'"': 'quotation',
	"'": 'quotation',
	'd': 'date',
	'T': 'timestamp',
	'n': 'internet', # address
	'r': 'reference', # contextual reference (variables, environment)
}
for k, v in field_type_mnemonics.items():
	types.assign(literal(k), 'refraction', ('type',), (v,))

types.assign(literal('l'), 'container', ('create', 'line'))

del nav, controlk, literal, caps, shift

standard = {
	'control': control,
	'edit': edit,
	'capture': capture,
	'types': types,
}

class Selection(object):
	"""
	A set of mappings used to interact with objects.
	"""
	__slots__ = ('index', 'current')

	@property
	def mapping(self):
		'Get the currently selected mapping by the defined name.'
		return self.current[0]

	def __init__(self, index):
		self.index = index
		self.current = None

	def set(self, name):
		self.current = (name, self.index[name])
		return self.current

	def event(self, key):
		"""
		Look up the event using the currently selected mapping.
		"""
		return (self.current[0], self.current[1].event(key))

	@classmethod
	def standard(Class):
		return Class(standard)
