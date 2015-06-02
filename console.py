import collections
import sys
import os
import queue
import functools
import locale
import codecs
import keyword
import operator
import itertools

from ..terminal import library as libterminal
from ..status import library as libstatus
from . import libfields
from . import library as iolib
from . import core
from . import keyboard

from ..terminal import symbols

range_color_palette = {
	'start-inclusive': 0x00CC00,
	'stop-inclusive': 0xFF5F00, # orange (between yellow and red)

	'offset-active': 0x0F0F00, # yellow, actual position
	'offset-inactive': 0,

	'start-exclusive': 0x0000FF,
	'stop-exclusive': 0xFF0000,
}

contexts = (
	'system', # the operating system 
	'program', # the program the editor is running in
	'control', # the session control; the prompt
	'session', # the state of the set of projects being managed
	'project', # the project referring to the container (may be None)
	'container', # root/document
	'sequence', # the lines of the document
	'line', # an individual line
	'field', # a field in a line
	'set', # a set of fields
)

actions = dict(
	navigation = (
		'forward',
		'backward',
		'first',
		'move',
		'last',
	),

	delta = (
		'create',
		'delete',
		'insert',
		'change',
	),

	selection = (
		'select',
		'all', # select all wrt context
		'tag',
		'match',
		'void', # deletion tagging
	),

	# commands that exclusively perform context transitions
	transition = (
		'enter',
		'exit',
		'escape',
	),

	transaction = (
		'commit',
		'rollback',
		'replay', # replay a rolled back transaction
	),
)

prompt_separator = libfields.FieldSeparator(symbols.whitespace['space'])

class Commands(object):
	"""
	A set of built-in commands used by the console.
	Projections will often have their own command set.
	"""
	def __init__(self):
		pass

class System(Commands):
	"""
	Commands used to interrogate the system.
	"""

	def ls(self,
		path,
		long = False,
		all = False,
		human = False,
	):
		pass

	def rm(self, *paths,
		recursive = False,
		force = False):
		pass

	def rmdir(self,
		*paths):
		pass

	def rmtree(self,
		*paths):
		pass

	def cd(self, path):
		pass

class Projection(iolib.core.Resource):
	"""
	A projection of a source onto a connected area of the display.

	Projection resources are used by Console transformers to manage the parts
	of the display.
	"""
	create_keyboard_mapping = keyboard.Selection.standard
	default_keyboard_mapping = 'edit'

	@property
	def keyset(self):
		return self.keyboard.current

	def __init__(self):
		self.dimensions = None # calibrated dimensions
		self.view = None
		self.area = None
		self.prompt = None
		self.pane = None # pane index of projection; None if not a pane or hidden
		self.movement = False
		self.line = 0 # absolute line offset of the vertical vector

		# keeps track of horizontal positions that are modified for cursor and range display
		self.horizontal_positions = {}
		self.horizontal_range = None
		self.horizontal_layer = None

		# Physical location of the projection.
		self.vector = libterminal.Vector()
		# View location of the projection.
		self.window = libterminal.Vector()

		# Recorded snapshot of vector and window.
		# Used by Console to clear outdated cursor positions.
		self.snapshot = None

		self.keyboard = self.create_keyboard_mapping() # per-projection to maintain state
		self.keyboard.set(self.default_keyboard_mapping)

	@staticmethod
	@functools.lru_cache(16)
	def event_method(target, event):
		return 'event_' + '_'.join(event)

	def route(self, event):
		"""
		Route the event to the target given the current processing state.
		"""
		mapping, event = self.keyboard.event(event)
		if event is None:
			# report no such binding
			return None

		return (mapping, event)

	def key(self, console, event):
		routing = self.route(event)
		if routing is None:
			return ()

		mapping, (target_id, event_selection, params) = routing

		method_name = self.event_method(target_id, event_selection)
		method = getattr(self, method_name)

		return method(event, *params)

	def adjust(self, point, dimensions):
		"""
		Adjust the positioning and size of the view. &point is a pair of positive integers
		describing the top-right corner on the screen and dimensions is a pair of positive
		integers describing the width.

		Adjustments are conditionally passed to a view.
		"""
		if self.view is not None:
			self.view.adjust(point, dimensions)
			self.calibrate(dimensions)
			self.dimensions = dimensions

	def calibrate(self, dimensions):
		"""
		Overloaded by subclasses to deal with the effect of an adjustment.

		Called when the projection is adjusted.
		"""
		self.window.horizontal.configure(self.window.horizontal.datum, dimensions[0], 0)
		self.window.vertical.configure(self.window.vertical.datum, dimensions[1], 0)

	def conceal(self):
		"""
		Called when the projection is hidden from the display.
		"""
		pass

	def reveal(self):
		"""
		Called when the projection is revealed. May not be focused.
		"""
		pass

	def focus(self):
		"""
		Set position indicators and activate cursor.
		"""
		self.controller.set_position_indicators(self)

	def blur(self):
		"""
		Clear position indicators and lock cursor.
		"""
		self.controller.clear_position_indicators(self)

	def connect(self, view):
		"""
		Connect the area to the projection for displaying the units.

		Connect &None in order to conceal.
		"""
		self.view = view
		self.area = view.area

		if view is None:
			return self.conceal()
		else:
			return self.reveal()

	def clear(self):
		"""
		Clear the projection state.
		Used to handle exceptional cases and programming errors.
		"""
		pass

	def update(self, start, stop, *lines):
		"""
		Render all the display lines in the given ranges.
		"""
		pass

	def render(self, start, stop):
		pass

	def refresh(self):
		"""
		Render all lines in the projection.
		"""
		pass

class Range(tuple):
	"""
	Arbitrary numeric range holding the contention (start <= stop).

	Ranges are inclusive at start and exclusive at stop.
	"""
	__slots__ = ()

	@property
	def start(self):
		return self[0]

	@property
	def stop(self):
		return self[1]

	def __contains__(self, x):
		'Whether or not the range contains the given number.'
		return self[0] <= x < self[1]

	def contiguous(self, r):
		pair = [self, r]
		pair.sort()
		return pair[0][1] >= pair[1][0] and pair[0][1] < pair[1][1]

	def join(self, r):
		return self.new(min(self[0], r[0]), max(self[1], r[1]))

	@classmethod
	def new(Class, start, stop):
		return Class((min(start,stop), max(start,stop)))

class Fields(Projection):
	"""
	A &fields based projection that maintains focus and field selection state.
	"""
	color_palette = {
		# modes
		'edit': 0xFF0000,
		'control': 0xFF0000, 
	}
	character_palette = {
		'character-deleted': symbols.combining['high']['x'],
		'cursor': ('[', ']'),
	}
	delete_across_units = False
	margin = 16 # number of lines that remains below or above the cursor
	out_of_bounds = libfields.Sequence(())

	@property
	def page_size(self):
		return self.area.height

	def invert(self, line):
		"""
		Identify the unit from the given line number.
		"""
		return line

	def selection(self):
		"""
		Calculate the selection from the vector position.
		"""
		lineno = self.vector.vertical.get()
		line = self.units[lineno]
		path, field, state = line.find(self.vector.horizontal.get())
		return (line, path, field)

	def block(self, index, ilevel = None, minimum = 0, maximum = None):
		"""
		Indentation block ranges.
		"""

		if maximum is None:
			maximum = len(self.units)

		if ilevel is None:
			self.level = libfields.indentation(self.units[index[1]])
		else:
			self.level = ilevel

		start, stop = libfields.block(
			self.units, index, minimum, maximum,
			libfields.indentation_block, self.level
		)

		stop += 1 # positions are exclusive on the end
		self.vector.vertical.configure(start, stop - start, index[1] - start)
		self.movement = True

	def outerblock(self, index):
		"""
		Outer indentation block ranges.
		"""
		if self.level:
			return self.block(index, self.level - 1)
		else:
			pass

	def adjacent(self, index, level = None, minimum = None, maximum = None):
		"""
		Adjacent block ranges.
		"""

		v = self.vector.vertical

		if v.relation():
			# position is outside vertical range
			# ignore implicit range constraints
			minimum = minimum or 0
			if maximum is None:
				maximum = len(self.units)
		else:
			# inside vertical range
			vs = v.snapshot()
			if maximum is None:
				maximum = vs[2]
			if minimum is None:
				minimum = vs[0]

		start, stop = libfields.block(
			self.units, index, minimum, maximum,
			libfields.contiguous_block
		)

		stop += 1 # positions are exclusive on the end
		v.configure(start, stop - start, index[1] - start)
		self.movement = True

	def horizontal_select(self, path, field, offset = 0):
		unit = self.unit

		h = self.vector.horizontal
		uo = unit.offset(path, field)

		# Adjust the vertical position without modifying the range.
		h.configure(uo or 0, field.length(), offset or 0)
		self.movement = True

	def select(self, line, unit, path, field):
		"""
		Select the field in the unit with the vector.

		The vertical ranges (start and stop) will not be adjusted, but
		the vertical position and horizontal ranges will be.
		"""
		h = self.vector.horizontal
		uo = unit.offset(field)

		self.field = field
		self.unit = unit

		# Adjust the vertical position without modifying the range.
		self.clear_horizontal_indicators()
		self.line = line
		v = self.vector.vertical
		v.move(v.get() - line)

		h.configure(uo, field.length(), 0)
		self.update_horizontal_indicators()
		self.movement = True

	def update_horizontal_state(self):
		h = self.vector.horizontal
		sh = h.snapshot()
		if False and sh == (0, 0, 0):
			# don't adjust horizontal if it's zero'd
			self.field = None
			return

		# attempt to identify what the corresponding field
		# would be given positional consistency across the vertical.
		fp = h.get()
		fu = self.unit.find(fp)

		if fu is not None:
			path, field, state = fu
			start, length, fi = state
			if isinstance(field, libfields.Formatting):
				offset = start + length
				for upath, ufield in fi:
					if not isinstance(ufield, libfields.Formatting):
						field = ufield
						path = upath
						length = field.length()
						start = offset
						break
					offset += field.length()

			h.configure(start, length, fp - start)
			self.path = path
			self.field = field
			self.update_horizontal_indicators()

	def update_vertical_state(self):
		"""
		Update the cache of the position based on the vector.
		"""
		v = self.vector.vertical
		w = self.window.vertical
		v.snapshot()
		nl = v.get()
		if nl < 0:
			nl = 0

		if self.line != nl:
			# new selection
			self.clear_horizontal_indicators()

			new = self.units[nl:nl+1]
			if new:
				self.unit = new[0]
			else:
				self.unit = self.out_of_bounds

			self.line = nl

			# make sure it's within the margin or it's on an edge
			origin, top, bottom = w.snapshot()
			mtop = top + self.margin
			mbottom = bottom - self.margin

			# adjust the window if movement traversed into the margin
			if nl < mtop and top > 0:
				w.move(-(mtop - nl))
				self.scrolled()
			elif nl > mbottom and bottom < len(self.units):
				w.move(nl - mbottom)
				self.scrolled()
			else:
				self.update_horizontal_state()

	def scrolled(self):
		"""
		Bind the window to the appropriate edges.
		"""
		h = self.window.horizontal
		v = self.window.vertical

		# origin != top means a scroll occurred
		hscrolled = h.offset
		vscrolled = v.offset

		# normalize the window by setting the datum to stop
		overflow = v.maximum - len(self.units)
		if overflow > 0:
			v.move(-overflow)

		underflow = v.get()
		if underflow < 0:
			v.move(-underflow)

		v.reposition()
		self.controller.emit(self.refresh())
		self.refresh_horizontal_indicators()

	def __init__(self):
		super().__init__()
		self.units = libfields.Segments() # the sequence of buffered Fields.

		# cached access to line and specific field
		self.field = None # field in line (and unit)
		self.unit = None # controlling unit; object containing line
		self.path = None # the sequence of fields containing the target field
		self.movement = True
		self.scrolling = True
		self.level = 0 # indentation level

	@property
	def horizontal(self):
		'The current working horizontal position.'
		return self.vector.horizontal

	@property
	def vertical(self):
		'The current working vertical position.'
		return self.vector.vertical

	@property
	def perspective(self):
		'The recently used axis.'
		return 'vertical'

	@staticmethod
	@functools.lru_cache(16)
	def tab(v, size = 4):
		return (' ' * size) * v

	@staticmethod
	@functools.lru_cache(16)
	def visible_tab(v, size = 4):
		return (('-' * (size-1)) + '|') * v

	def draw(self, unit,
		Indent=libfields.Indentation,
		Constant=libfields.Constant,
		Spacing=libfields.Spacing,
		isinstance=isinstance,
		len=len,
		iter=iter):
		'Draw an individual unit for rendering.'

		for path, x in unit.subfields():
			if isinstance(x, Indent):
				if x > 0:
					if libfields.has_content(unit):
						yield (self.tab(x), (), None)
					else:
						yield (self.visible_tab(x), (), 0x222222)
			elif isinstance(x, Spacing):
				yield (str(x), (), None)
			elif isinstance(x, Constant):
				if x in libfields.python['keywords']:
					color = 0x005fd7
				elif x in libfields.python['cores']:
					#color = 0x870087
					#color = 0x875faf
					color = 0x875fff
				elif x in libfields.python['terminators']:
					color = 0x770000
				else:
					color = 0xAAAAAA
				yield (x.value(), (), color)
			else:
				if hasattr(x, 'value'):
					yield (x.value(), (), 0xAAAAAA)
				else:
					yield (x, (), 0xAAAAAA)

	# returns the text for the stop, position, and stop indicators.
	def calculate_horizontal_start_indicator(self, text, style, positions):
		return (text or ' ',) + style

	def calculate_horizontal_stop_indicator(self, text, style, positions,
		combining_wedge = symbols.combining['low']['wedge-left'],
	):
		return (text or ' ',) + style

	def calculate_horizontal_position_indicator(self, text, style, positions,
		vc = symbols.combining['right']['vertical-line'],
		fs = symbols.combining['full']['forward-slash'],
		xc = symbols.combining['high']['wedge-right'],
	):
		invert = True
		mode = self.keyboard.current[0]
		if not text:
			text = ' '

		if mode == 'edit':
			style = ('underline',)
			invert = False
		else:
			style = ()

		if positions[0] == positions[1]:
			# position is on start
			color = (0x00FF00, 0)
		elif positions[2] == positions[1]:
			color = (0xFF0000, 0)
		else:
			color = (0xF0F000, 0)

		if invert:
			color = (color[1], color[0])

		return (text, style,) + color

	# modification to text string
	horizontal_transforms = {
		'start': calculate_horizontal_start_indicator,
		'stop': calculate_horizontal_stop_indicator,
		'position': calculate_horizontal_position_indicator,
	}

	def collect_horizontal_range(self, line, positions, len = len, whole = slice(None,None)):
		"""
		Collect the fragments of the horizontal range from the rendered unit.

		Used to draw the horizontal range background.

		Nearly identical to libfields.Segments.select()
		"""
		llen = len(line)
		astart = positions[0]
		astop = positions[-1]

		start, stop = libfields.address([x[0] for x in line], astart, astop)

		n = stop[0] - start[0]
		if not n:
			# same sequence; simple slice
			if line and start[0] < llen:
				only = line[start[0]]
				text = only[0][start[1] : stop[1]]
				hrange = [(text,) + only[1:]]
			else:
				# empty range
				hrange = []
		else:
			slices = [(start[0], slice(start[1], None))]
			slices.extend([(x, whole) for x in range(start[0]+1, stop[0])])
			slices.append((stop[0], slice(0, stop[1])))

			hrange = [
				(line[p][0][pslice],) + line[p][1:] for p, pslice in slices
				if line[p][0][pslice]
			]

		prefix = [line[i] for i in range(start[0])]
		if start[0] < llen:
			prefix_part = line[start[0]]
			prefix.append((prefix_part[0][:start[1]],) + prefix_part[1:])

		if stop[0] < llen:
			suffix_part = line[stop[0]]
			suffix = [(suffix_part[0][stop[1]:],) + suffix_part[1:]]
			suffix.extend([line[i] for i in range(stop[0]+1, len(line))])
		else:
			suffix = []

		return ((astart, astop, hrange), prefix, suffix)

	def collect_horizontal_positions(self, line, *positions, len = len):
		"""
		Collect the style information and characters at the requested positions
		of the rendered unit.

		Used to draw range boundaries and the cursor.
		"""
		hr = list(set(positions)) # list of positions and size
		hr.sort(key = lambda x: x[0])

		l = len(line)
		offset = 0
		roffset = None

		li = iter(range(l))
		fl = 0

		areas = {}
		for x, size in hr:
			if x >= offset and x < (offset + fl):
				# between offset and offset + len(f[0])
				roffset = (x - offset)
			else:
				offset += fl

				for i in li: # iterator remains at position
					f = line[i]
					fl = len(f[0])
					if x >= offset and x < (offset + fl):
						roffset = (x - offset)
						break
					else:
						# x >= (offset + fl)
						offset += fl
				else:
					# cursor proceeds line range
					offset += fl
					roffset = fl
					fl = 0
					f = ("", (), None, None)

				text, *style = f
				while len(style) < 3:
					style.append(None)
				style = tuple(style)

			areas[x] = (x, size, text[roffset:roffset+size], style)

		return [areas[k[0]] for k in positions]

	def clear_horizontal_indicators(self, starmap = itertools.starmap):
		"""
		Called to clear the horizontal indicators for line switches.
		"""
		area = self.view.area
		shr = area.seek_horizontal_relative
		astyle = area.style

		wl = self.window_line(self.line)

		if wl >= self.view.height or wl < 0:
			# scrolled out of view
			self.horizontal_positions.clear()
			self.horizontal_range = None
			return

		events = [area.seek((0, wl))]
		append = events.append

		# cursor
		for k, old in self.horizontal_positions.items():
			# don't bother if it's inside the range.
			append(shr(old[0]))
			oldtext = old[2] or ' '
			oldstyle = old[3]
			append(astyle(oldtext, *oldstyle))
			append(shr(-(old[0]+len(oldtext))))

		# horizontal selection
		if self.horizontal_range is not None:
			rstart, rstop, text = self.horizontal_range

			append(shr(rstart))
			append(b''.join(starmap(astyle, text)))
			append(shr(-((rstop - rstart) + rstart)))

		self.horizontal_positions.clear()
		self.horizontal_range = None

		self.controller.emit(events)

	def render_horizontal_indicators(self,
		unit, horizontal,
		names = ('start', 'position', 'stop',),
		#range_color = 0x262626,
		range_color = None,
		starmap = itertools.starmap,
	):
		"""
		Changes the horizontal 
		"""
		area = self.view.area
		shr = area.seek_horizontal_relative
		astyle = area.style

		hs = horizontal

		line = list(self.draw(unit))
		hr, prefix, suffix = self.collect_horizontal_range(line, hs)

		if self.horizontal_range != hr:
			if self.horizontal_range is not None:
				rstart, rstop, text = self.horizontal_range

				clear_range = [
					shr(rstart),
					b''.join(starmap(astyle, text)),
					shr(-((rstop - rstart) + rstart)),
				]
			else:
				clear_range = []

			self.horizontal_range = hr

			rstart, rstop, text = hr
			range_part = [x[:1] + (x[1] + ('underline',), (x[2] or 0xAAAAAA) + 0x222222, range_color,) for x in text]

			set_range = [
				shr(rstart),
				b''.join(starmap(astyle, range_part)),
				shr(-((rstop - rstart) + rstart)),
			]
		else:
			range_part = [x[:1] + (x[1] + ('underline',), (x[2] or 0xAAAAAA) + 0x222222, range_color,) for x in hr[2]]
			clear_range = []
			set_range = []

		rline = prefix + range_part + suffix

		# now the positions
		hp = self.collect_horizontal_positions(rline, *zip(hs, (1,1,1)))

		# map the positions to names for the dictionary state
		new_hp = [(names[i], x) for i, x in zip(range(3), hp)]
		# put position at the end
		new_hp.append(new_hp[1])
		del new_hp[1]

		clear_positions = []
		set_positions = []
		for k, v in new_hp:

			# clear old posiition if different
			old = self.horizontal_positions.get(k, None)
			if old is not None and old != v:
				if old[:2] != v[:2]:
					# completely new position, clear
					clear_positions.append(shr(old[0]))
					oldtext = old[2] or ' '
					oldstyle = old[3]
					clear_positions.append(astyle(oldtext, *oldstyle))
					clear_positions.append(shr(-(old[0]+len(oldtext))))

			# new indicator
			offset, size, text, style = v
			s = self.horizontal_transforms[k](self, text.ljust(size, ' '), style, hs)

			set_positions.append(shr(offset))
			set_positions.append(astyle(*s))
			set_positions.append(shr(-(offset+len(s[0]))))

		self.horizontal_positions.update(new_hp)

		return clear_positions + clear_range + set_range + set_positions

	def update_horizontal_indicators(self):
		wl = self.window_line(self.line)

		if wl < self.view.height and wl >= 0:
			events = self.render_horizontal_indicators(self.unit, self.horizontal.snapshot())
			seek = self.view.area.seek((0, wl))
			events.insert(0, seek)
			self.controller.emit(events)

	def refresh_horizontal_indicators(self):
		'Line was wholly redrawn; dump indicator state and update.'
		self.horizontal_positions.clear()
		self.horizontal_range = None
		self.update_horizontal_indicators()

	def window_line(self, line):
		"""
		Map the given 
		"""
		origin, top, bottom = self.window.vertical.snapshot()
		return line - self.window.vertical.get()

	def change_unit(self, index):
		self.vector.vertical.move(index)
		self.update_vertical_state()

	def render(self, start, stop):
		'Render the given line range to the view.'
		origin, top, bottom = self.window.vertical.snapshot()
		ub = len(self.units)
		rl = min(bottom, ub)

		if start is None:
			start = top

		start = max(start, top)

		if stop is None:
			stop = bottom
		stop = min(stop, rl)

		r = range(start, stop)
		seq = self.view.sequence

		for i in r:
			seq[i-top].update(list(self.draw(self.units[i])))

		return (start-top, stop-top)

	def display(self, start, stop):
		'Send the given line range to the display.'
		self.controller.emit(list(self.view.draw(*self.render(start, stop))))

	def refresh(self):
		origin, top, bottom = self.window.vertical.snapshot()
		ub = len(self.units)
		rl = min(bottom, ub)
		r = range(top, rl)
		seq = self.view.sequence

		for i in r:
			u = self.units[i]
			seq[i-top].update(list(self.draw(u)))

		u = self.out_of_bounds
		for i in range(rl, bottom):
			seq[i-top].update(list(self.draw(self.out_of_bounds)))

		return list(self.view.draw())

	def insignificant(self, path, field):
		'Determines whether the field as having insignifianct content.'
		return isinstance(field, libfields.Formatting) or str(field) == " "

	def rotate(self, horizontal, unit, sequence, quantity, filtered = None):
		"""
		Select the next *significant* field, skipping the given quantity.

		The optional &filtered parameter will be given candidate fields
		that can be skipped.
		"""
		h = horizontal
		start, pos, stop = h.snapshot()

		i = iter(sequence)

		r = unit.find(pos)
		if r is None:
			return

		fpath, field, state = r

		# update the range to the new field.
		if start == state[0] and stop == start + state[1]:
			update_range = True
		else:
			update_range = False

		# get to the starting point
		for x in i:
			if x[0] == fpath and x[1] == field:
				# found current position, break into next iterator
				break
		else:
			# probably the end of the iterator; no change
			return

		n = None
		path = None
		previous = None

		for path, n in i:
			if not self.insignificant(path, n):
				previous = n
				quantity -= 1
				if quantity <= 0:
					# found the new selection
					break
		else:
			if previous is not None:
				n = previous
			else:
				return

		if n is not None:
			offset = self.unit.offset(path, n)
			self.field = n
			horizontal.configure(offset or 0, n.length(), 0)
			self.update_horizontal_indicators()
			self.movement = True

	def event_field_cut(self, event):
		self.rotate(self.vector.horizontal, sel, self.unit.subfields(), 1)
		sel[-2].delete(sel[-1])

	def event_delete(self, event):
		v = self.vector.vertical
		vs = v.snapshot()
		h = self.vector.horizontal.snapshot()
		if h == (0, 0, 0):
			# delete range
			del self.units[vs[0]:vs[2]] # log undo action
			self.clear_horizontal_indicators()
			v.move(0, 1)
			v.collapse()
			self.update_vertical_state()
			self.movement = True
			self.scrolled()
			self.update_horizontal_indicators()
		else:
			pass

	def event_select_line(self, event, quantity=1):
		h = self.vector.horizontal

		abs = h.get()
		adjust = self.unit[0].length()
		ul = self.unit.length()

		self.clear_horizontal_indicators()

		h.configure(adjust, ul - adjust)

		if abs < adjust:
			pass
		elif abs >= ul:
			h.offset = h.magnitude
		else:
			h.move(abs)

		self.update_horizontal_indicators()
		self.movement = True

	def event_select_all(self, event, quantity=1):
		v = self.vector.vertical
		abs = v.get()
		v.configure(0, len(self.units))
		v.move(abs, 1)
		self.update_vertical_state()
		self.movement = True

	def event_select_block(self, event, quantity=1):
		self.block((self.line-1, self.line, self.line+1))

	def event_select_outerblock(self, event, quantity=1):
		self.outerblock(self.vector.vertical.snapshot())

	def event_select_adjacent(self, event, quantity=1):
		self.adjacent((self.line, self.line, self.line))

	# line [history] forward/backward
	def event_navigation_vertical_forward(self, event, quantity = 1):
		v = self.vector.vertical
		v.move(quantity)
		self.update_vertical_state()
		self.movement = True

	def event_navigation_vertical_backward(self, event, quantity = 1):
		self.vector.vertical.move(-quantity)
		self.update_vertical_state()
		self.movement = True

	# line [history] forward/backward
	def event_window_vertical_forward(self, event, quantity = 1):
		self.window.vertical.move(quantity)
		self.movement = True
		self.scrolled()

	def event_window_vertical_backward(self, event, quantity = 1):
		self.window.vertical.move(-quantity)
		self.movement = True
		self.clear_horizontal_indicators()
		self.scrolled()
		self.update_horizontal_indicators()

	def event_navigation_vertical_start(self, event):
		v = self.vector.vertical
		if v.offset == 0:
			# already at beginning, imply previous block at same level
			self.clear_horizontal_state()
			self.block((self.line-1, self.line, self.line), self.level, maximum = self.line)

		# zero the vertical offset
		v.offset = 0

		self.update_vertical_state()
		self.movement = True

	def event_navigation_vertical_stop(self, event):
		v = self.vector.vertical
		if v.offset == v.magnitude:
			# already at end, imply next block at same level
			self.clear_horizontal_state()
			self.block((self.line, self.line, self.line+1), self.level, minimum = self.line)

		v.offset = v.magnitude

		self.update_vertical_state()
		self.movement = True

	# horizontal

	def event_navigation_horizontal_forward(self, event, quantity = 1):
		"""
		Move the selection to the next significant field.
		"""
		h = self.horizontal
		self.rotate(h, self.unit, self.unit.subfields(), quantity)

	def event_navigation_horizontal_backward(self, event, quantity = 1):
		"""
		Move the selection to the previous significant field.
		"""
		h = self.horizontal
		self.rotate(h, self.unit, reversed(list(self.unit.subfields())), quantity)

	def event_navigation_horizontal_start(self, event):
		h = self.horizontal
		if h.offset == 0:
			r = self.unit.find(h.get()-1)
			if r is not None:
				# at the end
				path, field, (start, length, fi) = r
				change = h.datum - start
				h.magnitude += change
				h.datum -= change
		elif h.offset < 0:
			# move start exactly
			h.datum += h.offset
			h.offset = 0
		else:
			h.offset = 0

		self.update_horizontal_indicators()
		self.movement = True

	def event_navigation_horizontal_stop(self, event):
		h = self.horizontal
		if h.offset == h.magnitude:
			edge = h.get()
			r = self.unit.find(edge)
			if r is not None:
				# at the end
				path, field, (start, length, fi) = r
				if start + length <= self.unit.length():
					h.magnitude += length
					h.offset += length

		elif h.offset > h.magnitude:
			# move start exactly
			h.magnitude = h.offset
		else:
			h.offset = h.magnitude

		self.update_horizontal_indicators()
		self.movement = True

	def event_navigation_forward_character(self, event, quantity = 1):
		h = self.vector.horizontal
		h.move(quantity)
		self.update_horizontal_indicators()
		self.movement = True
	event_control_space = event_navigation_forward_character

	def event_navigation_backward_character(self, event, quantity = 1):
		h = self.vector.horizontal
		h.move(-quantity)
		self.update_horizontal_indicators()
		self.movement = True
	event_control_backspace = event_navigation_forward_character

	def event_navigation_jump_character(self, event, quantity = 1):
		h = self.vector.horizontal
		character = event.string

		il = libfields.indentation(self.unit).characters()
		line = str(self.unit[1])
		start = max(h.get() - il, 0)

		if start < 0 or start > len(line):
			start = 0
		if line[start:start+1] == character:
			# skip if it's on it already
			start += 1

		offset = line.find(character, start)

		if offset > -1:
			h.configure(offset + il, 1, 0)
			self.update_horizontal_state()
			self.movement = True

	def select_void(self, linerange, ind = libfields.indentation):
		v = self.vector.vertical
		for i in linerange:
			u = self.units[i]
			if ind(u) == 0 and u.length() == 0:
				v.move(i-v.get())
				self.vector.horizontal.configure(0, 0, 0)
				self.update_vertical_state()
				self.movement = True
				break
		else:
			# ignore; no void
			pass

	def event_navigation_void_forward(self, event):
		self.select_void(range(self.line+1, len(self.units)))

	def event_navigation_void_backward(self, event):
		self.select_void(range(self.line-1, -1, -1))

	def event_vertical_set_start(self, event):
		self.vector.vertical.start()
		self.movement = True

	def event_horizontal_set_start(self, event):
		self.vector.horizontal.start()
		self.update_horizontal_indicators()
		self.movement = True

	def event_vertical_set_stop(self, event):
		self.vector.vertical.halt()
		self.movement = True

	def event_horizontal_set_stop(self, event):
		self.vector.horizontal.halt()
		self.update_horizontal_indicators()
		self.movement = True

	def new(self, indentation = libfields.Indentation(0), Text = libfields.Text):
		return libfields.Sequence((indentation, Text(libfields.String(""))))

	def open_vertical(self, il, quantity, temporary = False):
		"""
		Create a quantity of new lines at the cursor position.
		"""
		v = self.vertical
		h = self.horizontal

		i = v.get()
		new = i + 1
		self.units[new:new] = [self.new(il) for x in range(quantity)]

		v.move(quantity)
		h.configure(il.length(), 0)

		self.update_vertical_state()
		self.movement = True
		self.event_transition_edit(None)
		self.display(i, None)

	def clear_horizontal_state(self):
		"""
		Zero out the horizontal cursor.
		"""
		self.vector.horizontal.configure(0,0,0)
		self.field = None

	def clear_vertical_state(self):
		"""
		Zero out the horizontal cursor.
		"""
		self.vector.vertical.collapse()
		self.update_vertical_state()

	def get_indentation_level(self):
		'Get the indentation level of the line at the current vertical position.'
		return libfields.indentation(self.units[self.vector.vertical.get()])

	def event_open_behind(self, event, quantity = 1):
		il = self.get_indentation_level()
		self.clear_horizontal_state()
		v = self.vector.vertical
		v.move(-1)
		self.update_vertical_state()
		self.open_vertical(il, quantity)

	def event_open_ahead(self, event, quantity = 1):
		self.open_vertical(self.get_indentation_level(), quantity)

	def event_edit_return(self, event, quantity = 1):
		self.open_vertical(self.get_indentation_level(), quantity)

	def event_open_temporary(self, event, quantity = 1):
		pass

	def event_delta_substitute(self, event):
		"""
		Substitute the entire contents of the field.
		For structured fields, this will clear the all of the subfields.

		If the field is a Constant, the field will be replaced with an editable text field.
		"""
		h = self.horizontal
		adjustments = self.unit[0].length()
		inverse = self.unit[1].delete(h.minimum - adjustments, h.maximum - adjustments)
		h.zero()
		self.clear_horizontal_indicators()
		self.display(self.line, self.line+1)
		self.update_horizontal_indicators()
		self.movement = True
		self.keyboard.set('edit')

	def event_delta_substitute_series(self, event):
		"""
		Substitute a series of fields separated with path delimiters.
		"""
		pass

	def empty(self, unit):
		"""
		Determine whether or not the given unit is empty.
		"""
		ul = len(unit)
		if ul == 0:
			return True
		if isinstance(unit[0], libfields.Indentation):
			return ul < 2
		return False

	def event_transition_edit(self, event):
		"""
		Transition into edit-mode. If the line does not have an initialized field
		or the currently selected field is a Constant, an empty Text field will be created.
		"""
		old_mode = self.keyboard.current
		self.keyboard.set('edit')
		self.update_horizontal_indicators()

	def insert_characters(self, characters):
		"""
		Insert characters into the focus.
		"""
		v = self.vector.vertical
		h = self.vector.horizontal

		chars = libfields.String(characters)
		adjustments = self.unit[0].length()

		offset = h.get() - adjustments

		self.unit[1].insert(offset, chars)
		h.expand(h.offset, len(chars))

		u = v.get()

		self.clear_horizontal_indicators()
		self.display(u, u+1)
		self.update_horizontal_indicators()
		self.movement = True

	def delete_characters(self, quantity):
		v = self.vector.vertical
		h = self.vector.horizontal

		offset = h.get() - self.unit[0].length()

		if quantity < 0:
			start = offset + quantity
			stop = offset
			l = -quantity
		else:
			start = offset
			stop = offset + quantity
			l = quantity

		self.unit[1].delete(start, stop)
		h.contract(h.offset, l)
		u = v.get()

		self.clear_horizontal_indicators()
		self.display(u, u+1)
		self.update_horizontal_indicators()
		self.movement = True

	def event_insert_character(self, event):
		"""
		Insert a character at the current cursor position.
		"""
		if event.type == 'literal':
			self.insert_characters(event.string)

	def transition_control(self):
		"""
		Transition into control-mode.
		"""
		old_mode = self.keyboard.current
		self.keyboard.set('control')
		self.update_horizontal_indicators()

	def event_transition_control(self, event):
		self.transition_control()

	def event_edit_commit(self, event):
		self.transition_control()

	def insert(self, characters):
		"""
		Insert the characters at the cursor position.
		"""
		if self.field is None:
			self.field = self.unit[1]

		h = self.vector.horizontal
		p = h.get()
		p -= self.unit[0].length()
		self.field.insert(p, libfields.String(characters))
		h.expand(p, len(characters))
		self.movement = True

	def event_edit_space(self, event):
		"""
		Insert a constant into the field sequence and
		create a new text field for further editing.
		"""
		self.insert_characters(' ')

	def event_delta_insert_space(self, event):
		'Insert a literal space'
		self.insert_characters(' ')

	def indent(self, sequence, quantity = 1, ignore_empty = False):
		"""
		Increase or decrease the indentation level of the given sequence.

		The sequence is prefixed with a constant corresponding to the tab-level,
		and replaced when increased.
		"""
		l = 0
		if not sequence or not isinstance(sequence[0], libfields.Indentation):
			new = init = libfields.Indentation(quantity)
			sequence.prefix(init)
		else:
			init = sequence[0]
			l = init.length()
			new = sequence[0] = libfields.Indentation(init + quantity)
			if self.field is init:
				self.field = new

		# contract or expand based on tabsize
		self.vector.horizontal.datum += (new.length() - l)
		self.movement = True

	def event_indent_increment(self, event, quantity = 1):
		self.indent(self.unit, quantity)
		self.clear_horizontal_indicators()
		self.display(self.line, self.line+1)
		self.update_horizontal_indicators()

	def event_indent_decrement(self, event, quantity = 1):
		self.indent(self.unit, -quantity)
		self.clear_horizontal_indicators()
		self.display(self.line, self.line+1)
		self.update_horizontal_indicators()

	event_edit_tab = event_indent_increment
	event_edit_shift_tab = event_indent_decrement

	def event_print_unit(self, event, quantity = 1):
		self.controller.transcript.write(repr(self.unit)+'\n')

	def event_delta_delete_backward(self, event, quantity = 1):
		self.delete_characters(quantity * -1)

	def event_field_delta_delete_forward(self, event, quantity = 1):
		self.delete_characters(quantity)

	def event_field_transition_control(self, event, quantity = None):
		self.keyboard.set('control')

class Lines(Fields):
	"""
	Fields based line editor.
	"""
	def __init__(self):
		super().__init__()
		self.prompt = Prompt()
		self.keyboard.set('control')
		self.source = None

		with open('/x/wip/io/console.py') as f:
			i = []
			seq = libfields.Sequence
			txt = libfields.Text.from_sequence
			for x in f.readlines():
				indentation, *text = libfields.parse(x)
				x = [libfields.Constant(y) for y in text]
				i.append(seq((indentation, txt(x))))

			#i = map(lambda x: libfields.Sequence(), f.readlines())
			self.units = libfields.Segments(i)

		self.unit = self.units[0]
		self.field = self.unit[0]
		nunits = len(self.units)
		self.vector.vertical.configure(0, nunits, 0)

class Status(Fields):
	"""
	The status line above the prompt.
	This projection is always present and receives events for pane management.
	"""
	def projection_changed(self, old, new):
		"""
		Updates the status field
		"""
		self.projection_type = new.__class__
		return self.refresh()

	def refresh(self):
		self.view.sequence[0].update([
			("[", (), 0x00FF00),
			("status:", (), 0x008800),
			(self.projection_type.__name__, (), 0x008800),
			("]", (), 0x00FF00),
		])
		return list(self.view.draw())

	def event_navigation_horizontal_forward(self, event, quantity = 1):
		"""
		Select the next pane.
		"""
		pass

	def event_navigation_horizontal_backward(self, event, quantity = 1):
		"""
		Select the previouse pane.
		"""
		pass

	# line [history] forward/backward
	def event_navigation_vertical_forward(self, event, quantity = 1):
		"""
		Rotate the selected pane to the next projection.
		"""
		pass

	def event_navigation_vertical_backward(self, event, quantity = 1):
		"""
		Rotate the selected pane to the previous projection.
		"""
		pass

class Prompt(Fields):
	"""
	The status and prompt of the console's command interface.

	This projection manages the last two lines on the screen and provides
	a globally accessible command interface for managing the content panes.

	The units of a prompt make up the history.
	"""
	separator = prompt_separator 

	def __init__(self):
		super().__init__()
		self.keyboard.set("control")
		self.unit = self.new()

		self.units.append(self.unit)
		self.vector.vertical.configure(0, 0, 1)

	def new(self):
		return libfields.Sequence()

	def draw(self, unit):
		for path, x in unit.value():
			if x is self.separator:
				yield (x.value(), (), 0x222222)
			else:
				yield (x.value(),)

	def refresh(self):
		v = self.view
		v.sequence[0].update(list(self.draw(self.unit)))
		#cchars = symbols.combining['low']['wedge-left'] + symbols.combining['high']['wedge-left']
		#caret = libterminal.Overwrite(cchars)
		return list(self.view.draw())

	def execute(self, event):
		console = self.controller
		if str(self.unit) == "exit":
			console.context.process.terminate()

class Root(Prompt):
	"""
	Default prompt for transcripts.
	"""
	event_field_control_return = Prompt.execute
	event_field_control_enter = Prompt.execute
	event_field_edit_return = Prompt.execute

class Transcript(Projection):
	"""
	A trivial line buffer. While &Log projections are usually preferred, a single
	transcript is always available for critical messages.
	"""
	@staticmethod
	def system():
		"""
		Get system data.
		"""
		import platform, getpass
		return {
			'user': getpass.getuser(),
			'host': platform.node(),
		}

	def __init__(self):
		super().__init__()
		self.lines = ['']
		self.bottom = 0 # bottom of window
		self.prompt = Root()

	def reference(self, console):
		"""
		Allocate a reference to the write method paired with a draw.
		"""
		#@console.context.task
		def write_reference(data, write = self.write, update = self.refresh, console = console):
			write(data)
			#console.emit(update())
		return write_reference

	def write(self, text):
		"""
		Append only to in memory line buffer.
		"""
		size = len(self.lines)

		new_lines = text.split('\n')
		nlines = len(new_lines) - 1

		self.lines[-1] += new_lines[0]
		self.lines.extend(new_lines[1:])

		vh = self.view.height
		self.bottom += nlines
		self.controller.emit(self.refresh())

	def move(self, lines):
		"""
		Move the window.
		"""
		self.bottom += lines

	def update(self):
		height = self.view.height
		if height >= self.bottom:
			top = 0
		else:
			top = self.bottom - height

		for start, stop in self.modified:
			edge = stop - top
			if edge >= height:
				stop -= (edge - height)

			for i in range(start, stop):
				line = self.lines[i]
				vi = i - top
				self.view.sequence[vi].update(((line,),))

			yield from self.view.draw(start - top, stop - top)

	def refresh(self):
		# don't bother using the view's scroll.
		height = self.view.height
		start = self.bottom - height
		seq = self.view.sequence

		for i, j in zip(range(0 if start < 0 else start, self.bottom), range(height)):
			seq[j].update(((self.lines[i],),))

		return self.view.draw()

class Empty(Projection):
	"""
	An empty, immutable sequence.
	"""

def input(transformer, queue, tty):
	"""
	Thread transformer function translating input to Character events for &Console.
	"""
	enqueue = transformer.context.enqueue
	emit = transformer.emit
	escape_state = 0

	# using incremental decoder to handle partial writes.
	state = codecs.getincrementaldecoder('utf-8')('replace')

	chars = ""
	while True:
		data = os.read(tty.fileno(), 1024)
		chars += state.decode(data)
		events = libterminal.construct_character_events(chars)

		enqueue(functools.partial(emit, events))
		chars = ""

def output(transformer, queue, tty):
	"""
	Thread transformer function receiving display transactions and writing to the terminal.
	"""
	while True:
		out = queue.get()
		tty.write(b''.join(out))
		tty.flush()

class Console(core.Join):
	"""
	The application that responds to keyboard input in order to make display changes.
	"""
	@property
	def prompt(self):
		"""
		The prompt of the current pane.
		"""
		return self.visible[self.pane].prompt

	def __init__(self):
		self.tty = None
		self.display = libterminal.Display() # used to draw the frame.
		self.transcript = Transcript() # the always available in memory buffer
		self.status = Status() # the status line

		self.refreshing = set() # set of panes to be refreshed
		self.motion = set() # set of panes whose position indicators changed

		self.areas = {
			'status': libterminal.Area(),
			'prompt': libterminal.Area(),
			'panes': (libterminal.Area(), libterminal.Area()),
		}

		self.panes = [self.transcript, Lines()]
		self.visible = list(self.panes)

		self.pane = 1 # focus pane (visible)
		self.projection = self.panes[1] # focus projection; receives events

	def install(self, tty):
		self.tty = tty
		self.dimensions = self.get_tty_dimensions()

		self.prompt.connect(libterminal.View(self.areas['prompt']))
		self.status.view = libterminal.View(self.areas['status'])
		for x, a in zip(self.panes, self.areas['panes']):
			x.connect(libterminal.View(a))

	def focus(self, projection):
		"""
		Set the focus to the given projection and return the necessary display events.
		"""
		old = self.projection
		self.projection = projection
		new = projection.vector.snapshot()

		return [old.blur(), self.status.projection_changed(old, projection), projection.focus()]

	def pane_verticals(self, index):
		'Calculate the vertical offsets of the pane.'
		if index is None:
			return None

		n = len(self.visible)
		width = self.dimensions[0] - (n+1) # substract framing
		pane_size = width // n # remainder goes to last pane

		pane_size += 1 # include initial
		left = pane_size * index
		if index == n - 1:
			right = self.dimensions[0]
		else:
			right = pane_size * (index+1)
		return (left, right)

	def adjust(self, dimensions):
		"""
		The window changed and the views and controls need to be updated.
		"""
		n = len(self.visible)
		width, height = dimensions
		size = (width // n) - 1

		# for status and prompt
		self.status.adjust((0, height-2), (width, 1)) # width change
		self.visible[self.pane].prompt.adjust((0, height-1), (width, 1)) # width change

		pheight = height - 3

		for p, i in zip(self.visible, range(n)):
			p.pane = i
			left, right = self.pane_verticals(i)
			left += 1
			p.adjust((left, 0), (right - left, pheight))

		# remainder for last pane minus one for the border
		return self.frame()

	def frame(self, color = 0x222222):
		"""
		Draw the frame of the console. Vertical separators and horizontal.
		"""
		n = len(self.visible)
		width, height = self.dimensions
		pane_size = width // n
		vh = height - 3 # vertical separator height and horizontal position

		# horizontal
		display = self.display
		yield display.seek((0, vh))
		yield display.style(symbols.lines['horizontal'] * self.dimensions[0], color = color)

		# verticals
		seq = symbols.lines['vertical'] + '\n\b'
		top = symbols.lines['vertical'] + '\n\b'
		bottom = symbols.intersections['bottom']
		seq = display.style((seq * vh) + bottom, color = color)

		# initial vertical
		yield display.seek((0, 0)) + seq

		last = None
		for i in range(0, n-1):
			left, right = self.pane_verticals(i)
			if last != left:
				yield display.seek((left, 0)) + seq
			yield display.seek((right, 0)) + seq
			last = right

		# edge of screen; no need to backspace
		seq = symbols.lines['vertical'] + '\n'
		seq = display.style((seq * vh) + bottom, color = color)
		yield display.seek((width, 0)) + seq

	def set_position_indicators(self, projection,
		colors=(0x008800, 0xF0F000, 0x880000),
		vprecede=symbols.wedge['up'],
		vproceed=symbols.wedge['down'],
		vwedges=(symbols.wedge['right'], symbols.wedge['left']),
		hprecede=symbols.wedge['left'],
		hproceed=symbols.wedge['right'],
	):
		events = bytearray()
		verticals = self.pane_verticals(projection.pane)
		win = projection.window
		vec = projection.vector

		seek = self.display.seek
		style = self.display.style

		v_limit = self.dimensions[1] - 3

		if verticals is not None:
			h_offset, h_limit = verticals
			hpointer = symbols.wedge['up']
			vtop = win.vertical.get()

			for side, wedge in zip(verticals, vwedges):
				for y, color in zip(vec.vertical.snapshot(), colors):
					if y is not None:
						y = y - vtop
						if y < 0:
							# position is above the window
							pointer = vprecede
							y = 0
						elif y >= v_limit:
							# position is below the window
							pointer = vproceed
							y = v_limit - 1
						else:
							pointer = wedge

						events += seek((side, y))
						events += style(pointer, color = color)

			# adjust for horizontal sets
			h_offset += 1 # avoid intersection with vertical
		else:
			hpointer = symbols.wedge['down']
			h_offset = 0
			h_limit = projection.dimensions[0]

		horiz = vec.horizontal.snapshot()
		for x, color in zip(horiz, colors):
			if x is not None:
				if x < 0:
					pointer = hprecede
					x = h_offset
				elif x > h_limit:
					pointer = hproceed
					x = h_limit
				else:
					pointer = hpointer
					x += h_offset

				events += seek((x, v_limit))
				events += style(pointer, color = color)

		# record the setting for subsequent clears
		projection.snapshot = (vec.snapshot(), win.snapshot())
		return events

	def clear_position_indicators(self, projection,
		v_line = symbols.lines['vertical'],
		h_line = symbols.lines['horizontal'],
		h_intersection = symbols.intersections['bottom'],
		color = 0x222222
	):
		if projection.snapshot is None:
			return

		seek = self.display.seek
		style = self.display.style

		# (horiz, vert) tuples
		vec, win = projection.snapshot # stored state

		verticals = self.pane_verticals(projection.pane)
		v_limit = self.dimensions[1] - 3

		vtop = win[1][1]

		events = bytearray()

		# verticals is None when it's a prompt
		if verticals is not None:
			r = style(v_line, color = color)

			for v in verticals:
				for y in vec[1]:
					if y is not None:
						y = y - vtop
						if y < 0:
							y = 0
						elif y >= v_limit:
							y = v_limit - 1

						events += seek((v, y))
						events += r

			h_offset, h_limit = verticals
			h_offset += 1 # for horizontals
			vertical_set = () # panes don't intersect with the joints
		else:
			# it's a prompt or status
			h_offset = 0
			h_limit = self.dimensions[0]

			# identifies intersections
			vertical_set = set()
			for i in range(len(self.visible)):
				left, right = self.pane_verticals(i)
				v.add(left)
				v.add(right)

		h_vertical = self.dimensions[1] - 3 # status and prompt

		for x in vec[0]:
			if x < 0:
				x = h_offset
			elif x > h_limit:
				x = h_limit
			else:
				x += h_offset

			if x in vertical_set:
				sym = h_intersection
			else:
				sym = h_line

			events += seek((x, v_limit))
			events += style(sym, color = color)

		projection.snapshot = None
		return events

	def delta(self):
		"""
		The terminal window changed in size. Get the new dimensions and refresh the entire
		screen.
		"""
		self.dimensions = self.get_tty_dimensions()

		initialize = [
			self.display.clear(),
			b''.join(self.adjust(self.dimensions)),
		]

		for x in self.visible:
			initialize.extend(x.refresh())

		initialize.extend(self.prompt.refresh())
		initialize.extend(self.status.refresh())
		self.emit(initialize)

	def actuate(self):
		for x in self.panes:
			x.inherit(self)
		self.status.inherit(self)

		initialize = [
			self.display.clear(),
			self.display.caret_hide(),
			self.display.disable_line_wrap(),
			b''.join(self.adjust(self.dimensions)),
		]

		self.status.projection_type = self.transcript.__class__

		for x in self.visible:
			initialize.extend(x.refresh())
		initialize.extend(self.prompt.refresh())
		initialize.extend(self.status.refresh())

		# redirect log to the transcript
		process = self.context.process
		wr = self.transcript.reference(self)

		process.log = wr
		process.system_event_connect(('signal', 'terminal.delta'), self, self.delta)

		libterminal.device.set_raw(self.tty.fileno())
		self.emit(initialize)
		self.panes[1].focus()

	def process(self, keys, trap = keyboard.trap.event):
		# receives Key() instances and emits display events
		context = self.context
		process = context.process

		events = list()

		for k in keys:
			# projection can change from individual keystrokes.
			projection = self.projection 
			# discover if a pane has focus
			if projection in self.visible:
				pi = self.visible.index(projection)
			else:
				# prompt
				pi = None

			# 
			trapped = trap(k)
			if trapped is not None:
				(target_id, event_selection, params) = trapped
				if event_selection == ('process', 'exit'):
					process.terminate()
					return
			else:
				# projection may change during iteration
				result = projection.key(self, k)
				if result is not None:
					#self.rstack.append(result)
					pass

				if projection.scrolling:
					self.refreshing.add(projection)

				if projection.movement:
					self.motion.add(projection)

		for x in tuple(self.motion):
			s = self.clear_position_indicators(x) + self.set_position_indicators(x)
			self.emit((s,))
			x.movement = False
			self.motion.discard(x)

		for x in tuple(self.refreshing):
			if x.pane is not None:
				events.extend(projection.refresh())
			x.scrolling = False
			self.refreshing.discard(x)

		self.emit(events)

	def get_tty_dimensions(self):
		"""
		Get the current tty dimensions.
		"""
		return libterminal.device.dimensions(self.tty.fileno())

def initialize(program):
	"""
	Initialize the given program with a console.
	"""
	libterminal.restore_at_exit() # cursor will be hidden and raw is enabled

	console_flow = core.Flow() # terminal input -> console -> terminal output
	console_flow.inherit(program)
	program.place(console_flow, 'console-operation')

	c = Console()
	console_flow.configure(core.Thread(), c, core.Thread())

	tty = open(libterminal.device.path, 'r+b')
	# Thread()'s instances take functions

	console_flow.sequence[-1].install(output, tty)
	console_flow.sequence[1].install(tty)
	console_flow.sequence[0].install(input, tty)

	program.place(c, 'console') # the Console() instance
	c.actuate()
