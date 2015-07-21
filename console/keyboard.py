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
trap.assign(('escaped', 'j', 0), 'console', ('pane', 'rotate', 'projection'), (1,))
trap.assign(('escaped', 'k', 0), 'console', ('pane', 'rotate', 'projection'), (-1,))

trap.assign(('control', 'tab', meta), 'console', ('console', 'rotate', 'pane'))
trap.assign(('control', 'tab', shiftmeta), 'console', ('navigation', 'backward'))
trap.assign(('escaped', 'o', 0), 'console', ('prepare', 'open'))

# projection control mapping
control = Mapping(('projection', ('navigation', 'jump', 'character'), ()))
ca = control.assign

# map
ca(literal('y'), 'projection', ('distribute', 'one'))
ca(caps('y'), 'projection', ('distribute', 'sequence'))

# control
ca(controlk('c'), 'projection', ('interrupt',))
ca(('escaped', 'c', 0), 'projection', ('copy',))

#control.assign(('control', 'escape', 0), 'projection', ('transition', 'exit'))
ca(('control', 'space', 0), 'projection', ('control', 'space'))
ca(('control', 'return', 0), 'projection', ('control', 'return'))

ca(literal('f'), 'projection', ('navigation', 'horizontal', 'forward'))
ca(literal('d'), 'projection', ('navigation', 'horizontal', 'backward'))
ca(caps('f'), 'projection', ('navigation', 'horizontal', 'stop'))
ca(caps('d'), 'projection', ('navigation', 'horizontal', 'start'))
ca(controlk('f'), 'projection', ())
ca(controlk('d'), 'projection', ())

ca(literal('s'), 'projection', ('select', 'series',))
ca(caps('s'), 'projection', ('select', 'series', 'backward')) # spare

ca(literal('e'), 'projection', ('navigation', 'vertical', 'sections'))
ca(caps('e'), 'projection', ('navigation', 'vertical', 'paging'))
ca(controlk('e'), 'projection', ('print', 'unit'))

# temporary
ca(controlk('w'), 'projection', ('console', 'save'))

ca(literal('j'), 'projection', ('navigation', 'vertical', 'forward'))
ca(literal('k'), 'projection', ('navigation', 'vertical', 'backward'))
ca(caps('j'), 'projection', ('navigation', 'vertical', 'stop'))
ca(caps('k'), 'projection', ('navigation', 'vertical', 'start'))
ca(('control', 'newline', 0), 'projection', ('navigation', 'void', 'forward'))
ca(controlk('k'), 'projection', ('navigation', 'void', 'backward'))

ca(caps('o'), 'projection', ('open', 'behind',))
ca(literal('o'), 'projection', ('open', 'ahead'))
ca(controlk('o'), 'projection', ('open', 'into'))

ca(literal('q'), 'projection', ('navigation', 'range', 'enqueue'))
ca(caps('q'), 'projection', ('navigation', 'range', 'dequeue'))
ca(controlk('q'), 'projection', ('',)) # spare

ca(literal('v'), 'projection', ('navigation', 'void', 'forward',))
ca(caps('v'), 'projection', ('navigation', 'void', 'backward',))
ca(controlk('v'), 'projection', ('',)) # spare

ca(literal('t'), 'projection', ('delta', 'translocate',))
ca(caps('t'), 'projection', ('delta', 'transpose',))
ca(controlk('t'), 'projection', ('delta', 'truncate'))

ca(literal('z'), 'projection', ('place', 'stop',))
ca(caps('z'), 'projection', ('place', 'start',))
ca(controlk('z'), 'projection', ('place', 'expand'))

# [undo] log
ca(literal('u'), 'projection', ('delta', 'undo',))
ca(caps('u'), 'projection', ('delta', 'redo',))
ca(controlk('u'), 'projection', ('redo',))

ca(literal('a'), 'projection', ('select', 'adjacent', 'local'))
ca(caps('a'), 'projection', ('select', 'adjacent'))

ca(literal('b'), 'projection', ('select', 'block'))
ca(caps('b'), 'projection', ('select', 'outerblock'))

ca(literal('n'), 'projection', ('delta', 'split',))
ca(caps('n'), 'projection', ('delta', 'join',))
ca(controlk('n'), 'projection', ('',))

ca(literal('p'), 'projection', ('paste', 'after'))
ca(caps('p'), 'projection', ('paste', 'before',))
ca(controlk('p'), 'projection', ('paste', 'into',))

ca(literal('l'), 'projection', ('select', 'horizontal', 'line'))
ca(caps('l'), 'projection', ('select', 'vertical', 'line'))
ca(controlk('l'), 'projection', ('console', 'seek', 'line'))

for i in range(10):
	control.assign(literal(str(i)), 'projection', ('index', 'reference'))

# character level movement
ca(controlk('space'), 'projection', ('navigation', 'forward', 'character'))
ca(delta('delete'), 'projection', ('navigation', 'backward', 'character'))

ca(nav('left'), 'projection', ('window', 'horizontal', 'forward'))
ca(nav('right'), 'projection', ('window', 'horizontal', 'backward'))
ca(nav('down'), 'projection', ('window', 'vertical', 'forward'))
ca(nav('up'), 'projection', ('window', 'vertical', 'backward'))

ca(literal('m'), 'projection', ('menu', 'primary')) # move to field index
ca(caps('m'), 'projection', ('menu', 'secondary')) # move to line number

ca(literal('i'), 'projection', ('transition', 'edit'),)
ca(caps('i'), 'projection', ('delta', 'split'),) # split field

ca(literal('c'), 'projection', ('delta', 'substitute'),)
ca(caps('c'), 'projection', ('delta', 'substitute', 'previous'),) # remap this

ca(literal('x'), 'projection', ('delta', 'delete', 'forward'),)
ca(caps('x'), 'projection', ('delta', 'delete', 'backward'),)
ca(controlk('x'), 'selection', ('remove', 'selection')) # cut line

ca(literal('r'), 'projection', ('delta', 'replace', 'character'),)
ca(caps('r'), 'projection', ('delta', 'replace'),)

ca(('control', 'tab', 0), 'projection', ('delta', 'indent', 'increment'))
ca(('control', 'tab', shift), 'projection', ('delta', 'indent', 'decrement'))
ca(controlk('v'), 'projection', ('delta', 'indent', 'null'))

ca(('control', 'c', 1), 'control', ('navigation', 'console')) # focus control console
del ca

# insert mode
edit = Mapping(default = ('projection', ('delta', 'insert', 'character'), ())) # insert
ea = edit.assign
ea(('control', 'nul', 0), 'projection', ('delta', 'insert', 'space')) # literal space

ea(controlk('c'), 'projection', ('edit', 'abort'))
ea(controlk('d'), 'projection', ('edit', 'commit')) # eof
ea(controlk('v'), 'projection', ('edit', 'capture'))

ea(('delta', 'delete', 0), 'projection', ('delta', 'delete', 'backward'))
ea(('delta', 'backspace', 0), 'projection', ('delta', 'delete', 'backward'))
ea(controlk('x'), 'projection', ('delta', 'delete', 'forward'))

# these are mapped to keyboard names in order to allow class-level overrides
# and/or context sensitive action selection
ea(('control', 'space', 0), 'projection', ('delta', 'edit', 'insert', 'space'))
ea(('control', 'tab', 0), 'projection', ('edit', 'tab'))
ea(('control', 'tab', shift), 'projection', ('edit', 'shift', 'tab'))
ea(('control', 'return', 0), 'projection', ('edit', 'return'))

ea(('navigation', 'left', 0), 'projection', ('navigation', 'backward', 'character'))
ea(('navigation', 'right', 0), 'projection', ('navigation', 'forward', 'character'))
ea(('navigation', 'up', 0), 'projection', ('navigation', 'beginning'))
ea(('navigation', 'down', 0), 'projection', ('navigation', 'end'))

ea(controlk('u'), 'projection', ('delta', 'delete', 'tobol'))
ea(controlk('k'), 'projection', ('delta', 'delete', 'toeol'))

ea(controlk('w'), 'projection', ('delta', 'delete', 'backward', 'adjacent', 'class'))
ea(controlk('t'), 'projection', ('delta', 'delete', 'forward', 'adjacent', 'class'))

ea(controlk('a'), 'projection', ('navigation', 'move', 'bol'))
ea(controlk('e'), 'projection', ('navigation', 'move', 'eol'))
del ea

# capture keystroke
capture = Mapping(default = ('projection', ('capture',), ()))

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
	types.assign(literal(k), 'projection', ('type',), (v,))

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
