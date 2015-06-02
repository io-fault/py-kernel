"""
Provides common mappings for keyboard based navigation and control.
"""
from ..terminal import library as libterminal

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
literal = lambda x: ('literal', x, 0)
caps = lambda x: ('literal', x, shift)
controlk = lambda x: ('control', x, 1)
shiftcontrolk = lambda x: ('control', x, shift)
nav = lambda x: ('navigation', x, 0)
shiftnav = lambda x: ('navigation', x, shift)
delta = lambda x: ('delta', x, 0)

# events trapped by the console
trap = Mapping()
trap.assign(('escaped', '~', 0), 'console', ('process', 'exit'))
trap.assign(('escaped', '`', 0), 'console', ('focus', 'prompt'))
# pane management
trap.assign(('escaped', 'q', 0), 'console', ('navigation', 'forward'))
trap.assign(('escaped', 'w', 0), 'console', ('navigation', 'backward'))
trap.assign(('escaped', 'tab', 0), 'console', ('select', 'rotate'))
trap.assign(('escaped', 'tab', shift), 'console', ('navigation', 'backward'))

# projection control mapping
control = Mapping(('projection', ('navigation', 'jump', 'character'), ()))

# control
control.assign(controlk('c'), 'projection', ('interrupt',))
control.assign(controlk('v'), 'projection', ('print', 'unit',))

control.assign(('control', 'escape', 0), 'projection', ('transition', 'exit'))
control.assign(('control', 'space', 0), 'projection', ('control', 'space'))

control.assign(literal('f'), 'projection', ('navigation', 'horizontal', 'forward'))
control.assign(literal('d'), 'projection', ('navigation', 'horizontal', 'backward'))
control.assign(caps('f'), 'projection', ('navigation', 'horizontal', 'stop'))
control.assign(caps('d'), 'projection', ('navigation', 'horizontal', 'start'))
control.assign(literal('s'), 'projection', ('span', 'horizontal', 'forward'))
control.assign(caps('s'), 'projection', ('span', 'horizontal', 'backward'))

control.assign(literal('j'), 'projection', ('navigation', 'vertical', 'forward'))
control.assign(literal('k'), 'projection', ('navigation', 'vertical', 'backward'))
control.assign(caps('j'), 'projection', ('navigation', 'vertical', 'stop'))
control.assign(caps('k'), 'projection', ('navigation', 'vertical', 'start'))
control.assign(('control', 'newline', 0), 'projection', ('window', 'vertical', 'forward'))
control.assign(controlk('k'), 'projection', ('window', 'vertical', 'backward'))

control.assign(literal('v'), 'projection', ('navigation', 'void', 'forward',))
control.assign(caps('v'), 'projection', ('navigation', 'void', 'backward',))

control.assign(literal('t'), 'projection', ('delta', 'truncate', 'backward'))
control.assign(caps('t'), 'projection', ('delta', 'truncate', 'forward'))
control.assign(controlk('t'), 'projection', ('delta', 'truncate'))

if 0:
	control.assign(literal('v'), 'projection', ('vertical', 'set', 'start'))
	control.assign(caps('v'), 'projection', ('vertical', 'set', 'stop'))
	control.assign(literal('h'), 'projection', ('horizontal', 'set', 'start'))
	control.assign(caps('h'), 'projection', ('horizontal', 'set', 'stop'))

control.assign(controlk('d'), 'projection', ('delete',))
control.assign(controlk('t'), 'projection', ('transpose',))
control.assign(controlk('f'), 'projection', ('find', 'string'))
control.assign(controlk('a'), 'projection', ('select', 'document'))
# history
control.assign(controlk('u'), 'projection', ('delta', 'undo',))
control.assign(controlk('r'), 'projection', ('delta', 'redo',))

control.assign(literal('a'), 'projection', ('select', 'adjacent'))
control.assign(controlk('a'), 'projection', ('select', 'all'))

control.assign(literal('n'), 'projection', ('next',))
control.assign(caps('n'), 'projection', ('previous',))

control.assign(caps('l'), 'projection', ('select', ''))
control.assign(literal('l'), 'projection', ('select', 'line'))

control.assign(literal('b'), 'projection', ('select', 'block'))
control.assign(caps('b'), 'projection', ('select', 'outerblock'))

#control.assign(literal('v'), 'projection', ('line', 'split',))
#control.assign(literal('V'), 'projection', ('line', 'join',))

control.assign(caps('o'), 'projection', ('open', 'behind',))
control.assign(literal('o'), 'projection', ('open', 'ahead'))

control.assign(literal('p'), 'projection', ('paste', 'after'))
control.assign(controlk('p'), 'projection', ('paste', 'into',))
control.assign(caps('p'), 'projection', ('paste', 'before',))

for i in range(10):
	control.assign(literal(str(i)), 'projection', ('index', 'reference'))

# character level movement
control.assign(controlk('space'), 'projection', ('navigation', 'forward', 'character'))
control.assign(delta('delete'), 'projection', ('navigation', 'backward', 'character'))
control.assign(nav('left'), 'projection', ('navigation', 'backward', 'character'))
control.assign(nav('right'), 'projection', ('navigation', 'forward', 'character'))

control.assign(literal('e'), 'projection', ('transition', 'enter'), ('end',))
control.assign(caps('e'), 'projection', ('transition', 'enter'), ('beginning',))

control.assign(literal('m'), 'projection', ('navigation', 'move')) # move to field index
control.assign(caps('m'), 'projection', ('navigation', 'move')) # move to line number

control.assign(literal('i'), 'projection', ('transition', 'edit'),)
control.assign(caps('i'), 'projection', ('delta', 'split'),) # split field

control.assign(literal('c'), 'projection', ('delta', 'substitute'),)
control.assign(caps('c'), 'projection', ('delta', 'substitute', 'series'),)

control.assign(literal('x'), 'field', ('cut', 'forward'),)
control.assign(caps('x'), 'field', ('cut', 'backward'),)
control.assign(controlk('x'), 'selection', ('cut', 'line')) # cut line

control.assign(literal('r'), 'projection', ('delta', 'replace', 'character'),)
control.assign(caps('r'), 'projection', ('delta', 'replace'),)

control.assign(literal('s'), 'projection', ('select', 'acquire', 'start'),)
control.assign(caps('s'), 'projection', ('select', 'acquire', 'stop'),)

control.assign(('control', 'tab', 0), 'projection', ('indent', 'increment'))
control.assign(('control', 'tab', shift), 'projection', ('indent', 'decrement'))

control.assign(nav('up'), 'container', ('navigation', 'forward'))
control.assign(nav('down'), 'container', ('navigation', 'backward'))

control.assign(('control', 'c', 1), 'control', ('navigation', 'console')) # focus control console

# insert mode
edit = Mapping(default = ('projection', ('insert', 'character'), ())) # insert
edit.assign(('control', 'nul', 0), 'projection', ('delta', 'insert', 'space')) # literal space

edit.assign(controlk('c'), 'projection', ('edit', 'abort'))
edit.assign(controlk('d'), 'projection', ('edit', 'commit')) # eof

edit.assign(('control', 'escape', 1), 'projection', ('transition', 'control'))

edit.assign(('delta', 'delete', 0), 'projection', ('delta', 'delete', 'backward'))
edit.assign(('delta', 'backspace', 0), 'projection', ('delta', 'delete', 'backward'))
edit.assign(controlk('x'), 'projection', ('delta', 'delete', 'forward'))

# these are mapped to keyboard names in order to allow class-level overrides
# and/or context sensitive action selection
edit.assign(('control', 'space', 0), 'projection', ('edit', 'space'))
edit.assign(('control', 'tab', 0), 'projection', ('edit', 'tab'))
edit.assign(('control', 'tab', shift), 'projection', ('edit', 'shift', 'tab'))
edit.assign(('control', 'return', 0), 'projection', ('edit', 'return'))

edit.assign(('navigation', 'left', 0), 'projection', ('navigation', 'backward', 'character'))
edit.assign(('navigation', 'right', 0), 'projection', ('navigation', 'forward', 'character'))
edit.assign(('navigation', 'up', 0), 'projection', ('navigation', 'beginning'))
edit.assign(('navigation', 'down', 0), 'projection', ('navigation', 'end'))

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
