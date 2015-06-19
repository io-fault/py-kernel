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
from . import lines as lineslib
from . import library as iolib
from . import core
from . import keyboard

from ..terminal import symbols

range_color_palette = {
	'start-inclusive': 0x00CC00,
	'stop-inclusive': 0xFF8700, # orange (between yellow and red)

	'offset-active': 0xF0F000, # yellow, actual position
	'offset-inactive': 0,

	'start-exclusive': 0x005F00,
	'stop-exclusive': 0xFF0000,
}

color_reference = {
	'teal': 0x005f5f,
	'orange': 0xff8700,
	'purple': 0x875fff,
	'cream': 0xffd787,
	'brick': 0x5f0000,
}

# colors used for range highlighting
color_highlights = [
	0x878700,
]

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

class Query(object):
	"""
	Range queries for managing range operations.
	"""

class Projection(iolib.core.Resource):
	"""
	A projection of a source onto a connected area of the display.

	Projection resources are used by Console transformers to manage the parts
	of the display.
	"""
	create_keyboard_mapping = keyboard.Selection.standard
	default_keyboard_mapping = 'edit'

	@property
	def dimensions(self):
		return self.view.area.dimensions

	@property
	def horizontal(self):
		'The current working horizontal position.'
		return self.vector.horizontal

	@property
	def vertical(self):
		'The current working vertical position.'
		return self.vector.vertical

	@property
	def last_axis(self):
		'The recently used axis.'
		if self.vector_last_axis is self.horizontal:
			return 'horizontal'
		else:
			return 'vertical'

	@property
	def axis(self):
		'Return the &libterminal.Position of the last axis used.'
		return self.vector_last_axis

	@property
	def keyset(self):
		return self.keyboard.current

	def __init__(self):
		self.movement = False
		self.view = None
		self.area = None
		self.pane = None # pane index of projection; None if not a pane or hidden

		# keeps track of horizontal positions that are modified for cursor and range display
		self.horizontal_positions = {}
		self.horizontal_range = None

		# Physical location of the projection.
		self.vector = libterminal.Vector()
		self.vector_last_axis = self.vector.vertical # last used axis
		self.vertical_index = 0 # the focus line

		# View location of the projection.
		self.window = libterminal.Vector()

		self.range_queue = collections.deque()

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

	def calibrate(self, dimensions):
		"""
		Called when the projection is adjusted.
		"""
		w = self.window
		w.horizontal.configure(w.horizontal.datum, dimensions[0], 0)
		w.vertical.configure(w.vertical.datum, dimensions[1], 0)

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

	@property
	def revealed(self):
		'Whether the projection is currently visible.'
		return self in self.controller.visible

	def focus(self):
		"""
		Set position indicators and activate cursor.
		"""
		console = self.controller
		events = console.set_position_indicators(self)
		console.emit([events])

	@property
	def focused(self):
		'Whether the projection is the current focus; receives key events.'
		return self.controller.projection is self

	def blur(self):
		"""
		Clear position indicators and lock cursor.
		"""
		console = self.controller
		events = console.clear_position_indicators(self)
		console.emit([events])

	def connect(self, view):
		"""
		Connect the area to the projection for displaying the units.

		Connect &None in order to conceal.
		"""
		self.view = view

		if view is None:
			self.area = None
			return self.conceal()
		else:
			self.area = view.area
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

class IRange(tuple):
	"""
	Inclusive numeric range used for cases where the range size is one or more.
	"""
	__slots__ = ()

	@property
	def direction(self):
		'Returns -1 if the stop is less than the start.'
		return 1 if self[0] >= self[1] else -1

	@property
	def start(self):
		return self[0]

	@property
	def stop(self):
		return self[1]

	@classmethod
	def normal(Class, *args):
		"""
		Create a normal range using the given boundaries; the minimum given will be the
		start and the maximum will be the stop.
		"""
		return Class((min(*args), max(*args)))

	@classmethod
	def single(Class, index):
		"""
		Create a range consisting of a single unit.
		"""
		return Class((index, index))

	def __contains__(self, x):
		'Whether or not the range contains the given number.'
		return self[0] <= x <= self[1]

	def relation(self, r):
		pass

	def contiguous(self, r):
		'The given range is coniguous with the other.'
		tr = tuple(r)
		return self[0]-1 in tr or self[1]+1 in tr

	def join(self, r):
		'Combine the ranges.'
		return self.normal(min(self[0], r[0]), max(self[1], r[1]))

	def exclusive(self):
		'Return as an exclusive-end range pair.'
		return (self[0], self[1]+1)

	def units(self, step = 1):
		'Return an iterator to the units in the range'
		if self.direction > 0:
			return range(self[0], self[1]+1, step)
		else:
			return range(self[0], self[1]-1, -step)

class RMapping(object):
	"""
	Range mapping. Mapping of ranges 
	"""
	from bisect import bisect

	def __init__(self, combine = operator.methodcaller("__add__")):
		self.ranges = []
		self.association = {}
		self.combine = combine

	def get(self, key):
		index = self.bisect(self.ranges, (key, key))

class Fields(Projection):
	"""
	A &fields based projection that maintains focus and field selection state.
	"""
	separator = libfields.field_separator

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
	margin = 8 # number of lines that remains below or above the cursor
	out_of_bounds = libfields.Sequence((libfields.Indentation.acquire(0),))

	@property
	def current_vertical(self):
		'The curent vertical index as a single IRange instance.'
		return IRange((self.vertical_index, self.vertical_index))

	def focus(self):
		super().focus()
		self.update_horizontal_indicators()

	def selection(self):
		"""
		Calculate the selection from the vector position.
		"""
		vi = self.vertical.get()
		unit = self.units[vi]
		path, field, state = line.find(self.horizontal.get())
		return (vi, unit, path, field)

	def block(self, index, ilevel = None, minimum = 0, maximum = None):
		"""
		Indentation block ranges.
		"""

		if maximum is None:
			maximum = len(self.units) - 1

		if ilevel is None:
			self.level = libfields.indentation(self.units[index[1]])
		else:
			self.level = ilevel

		start, stop = libfields.block(
			self.units, index, minimum, maximum,
			libfields.indentation_block, self.level
		)

		stop += 1 # positions are exclusive on the end
		self.vertical.configure(start, stop - start, index[1] - start)
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
		v = self.vertical

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
		self.vertical_query = 'adjacent'
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

		self.unit = unit

		# Adjust the vertical position without modifying the range.
		self.clear_horizontal_indicators()
		self.vertical_index = line
		v = self.vector.vertical
		v.move(v.get() - line)

		h.configure(uo, field.length(), 0)
		self.update_horizontal_indicators()

	def constrain_horizontal_range(self):
		"Apply the limits of the vertical index to the vector's horizontal range."
		h = self.horizontal
		hmin = self.get_indentation_level().characters()
		h.limit(hmin, self.unit.characters())

	def update_unit(self):
		"""
		Unconditionally update the vertical index and unit without scrolling.
		"""
		v = self.vertical
		nl = v.get()
		nunits = len(self.units)
		if nl < 0:
			nl = 0
			v.set(nl)
		elif nl > nunits:
			nl = nunits
			v.set(nl)

		new = self.units[nl:nl+1]
		if new:
			self.unit = new[0]
		else:
			self.unit = self.out_of_bounds

		self.vertical_index = nl

	def update_vertical_state(self):
		"""
		Update the cache of the position based on the vector.
		"""
		v = self.vector.vertical
		w = self.window.vertical

		nl = v.get()
		nunits = len(self.units)
		if nl < 0:
			nl = 0
			v.set(nl)
		elif nl > nunits:
			nl = nunits
			v.set(nl)

		if self.vertical_index == nl:
			# vertical did not change.
			return

		new = self.units[nl:nl+1]
		if new:
			self.unit = new[0]
		else:
			self.unit = self.out_of_bounds

		self.vertical_index = nl
		self.update_window()

	def update_window(self):
		"""
		Invoked after &vertical_index is updated to scroll to the new location.
		"""
		nl = self.vertical_index
		w = self.window.vertical
		# make sure it's within the margin or it's on an edge
		origin, top, bottom = w.snapshot()

		if self.vertical_query == 'paging':
			# ignore the margin during paging
			margin = 0
		else:
			margin = self.margin

		mtop = top + margin
		mbottom = bottom - margin

		# adjust the window if movement traversed into the margin
		if nl < mtop and top > 0:
			# vertical index has crossed over the top margin
			new_top = -(mtop - nl)
			w.move(new_top)
			if w.offset > -margin:
				# scroll in margin chunks, not single lines
				w.offset = -margin
			self.scrolled()
		elif nl > mbottom and bottom < len(self.units):
			# vertical index has crossed over the bottom margin
			w.move(nl - mbottom)

			if w.offset < margin:
				w.offset = margin
			self.scrolled()
		else:
			self.constrain_horizontal_range()

	def scrolled(self):
		"""
		Bind the window to the appropriate edges.
		"""
		h = self.window.horizontal
		v = self.window.vertical

		# origin != top means a scroll occurred
		hscrolled = h.offset
		vscrolled = v.offset

		if not hscrolled and not vscrolled:
			return

		self.clear_horizontal_indicators()

		# normalize the window by setting the datum to stop
		overflow = v.maximum - len(self.units)
		if overflow > 0:
			v.move(-overflow)

		underflow = v.get()
		if underflow < 0:
			v.move(-underflow)

		v.reposition()
		self.controller.emit(self.refresh())
		self.update_horizontal_indicators()

	def __init__(self):
		super().__init__()

		self.units = libfields.Segments() # the sequence of buffered Fields.

		# cached access to line and specific field
		self.unit = None # controlling unit; object containing line
		self.movement = True
		self.scrolling = True
		self.level = 0 # indentation level

		# method of range production
		self.vertical_query = 'explicit'
		self.vertical_query_override = 'explicit'
		self.horizontal_query = 'field'
		self.horizontal_query_override = 'implicit'

		self.distribution = None

		self.past = []
		self.future = []

	def log(self, *inverse):
		"""
		Log a change.
		"""
		if not self.past:
			self.past.append([])
		self.past[-1].append((None, inverse),) # timestamp

		if self.future:
			self.future.clear()

	def checkpoint(self):
		"""
		Insert a checkpoint into the changelog to mark stopping points for undo and redo
		operations.
		"""
		self.past.append([])

	def undo(self, quantity):
		"""
		Undo the given quantity of *transactions*.
		"""
		if self.past[-1]:
			actions = self.past[-1]
			del self.past[-1]
		else:
			actions = self.past[-2]
			del self.past[-2]

		actions.reverse()

		redo = []
		add = redo.append

		self.clear_horizontal_indicators()

		ranges = []
		for ts, (undo, lr) in actions:
			method, args = undo
			inverse = method(*args)

			if ranges and ranges[-1].contiguous(lr):
				ranges[-1] = ranges[-1].join(lr)
			else:
				ranges.append(lr)

			add((None, (inverse, lr)))

		self.future.insert(0, redo)

		for r in ranges:
			for x in self.units[r.start:r.stop]:
				x[1].reformat()
			self.display(*r.exclusive()) # filters out-of-sight lines

		self.update_unit()
		self.update_window()

	def redo(self, quantity):
		"""
		Redo the given quantity of *transactions*.
		"""
		actions = self.future[0]
		actions.reverse()
		del self.future[0]

		undo = []
		add = undo.append

		self.clear_horizontal_indicators()

		for ts, (redo, lr) in actions:
			method, args = redo
			inverse = method(*args)
			self.display(*lr.exclusive()) # filters out-of-sight lines
			add((None, (inverse, lr)))

		self.past.append(undo)

		self.update_unit()
		self.update_window()

	def find(self, pattern):
		"""
		Alter the vertical and horizontal query to search.
		"""
		self.vertical_query = self.horizontal_query = 'pattern'
		self.pattern = pattern
		self.event_navigation_vertical_stop(None)

	def event_delta_undo(self, event, quantity = 1):
		self.undo(quantity)

	def event_delta_redo(self, event, quantity = 1):
		self.redo(quantity)

	def event_delta_map(self, event):
		"""
		Map the the following commands across the vertical range.
		"""
		self.distribution = 'vertical'

	@staticmethod
	@functools.lru_cache(16)
	def tab(v, size = 4):
		return (' ' * size) * v

	@staticmethod
	@functools.lru_cache(16)
	def visible_tab(v, size = 4):
		return (('-' * (size-1)) + '|') * v

	def comment(self, q, iterator, color = color_reference['brick']):
		'Draw the comment.'
		yield (q.value(), (), color)
		for path, x in iterator:
			yield (x.value(), (), color)

	def quotation(self, q, iterator, color = 0x666666):
		'Draw the quotation.'
		yield (q.value(), (), color)
		for path, x in iterator:
			yield (x.value(), (), color)
			if x == q:
				break

	def draw(self, unit,
		Indent=libfields.Indentation,
		Constant=libfields.Constant,
		isinstance=isinstance,
		len=len,
		has_content=libfields.has_content,
		iter=iter, next=next):
		'Draw an individual unit for rendering.'
		fs = 0

		if len(unit) > 1:
			classify = unit[1].classifications
		else:
			classify = ()

		i = iter(unit.subfields())
		path, x = next(i)

		if isinstance(x, Indent):
			if x > 0:
				if has_content(unit):
					yield (self.tab(x), (), None)
				else:
					yield (self.visible_tab(x), (), 0x222222)

		spaces = 0

		for path, x in i:
			if x.empty:
				continue

			val = x.value()

			if x == " ":
				# space
				spaces += 1
				continue
			elif spaces:
				yield (" " * spaces, (), 0xBBBBBB)
				spaces = 0

			if x == "#":
				yield from self.comment(x, i)
				continue
			elif x in unit[1].quotations:
				yield from self.quotation(x, i)
				continue
			elif val.isdigit() or (val.startswith('0x') and val[2:].isdigit()):
				yield (x.value(), (), color_reference['teal'])
				continue
			elif x is self.separator:
				fs += 1
				yield (str(fs), (), 0x202020)
				continue

			if x in classify:
				cc = classify[x]
				if cc == 'keyword':
					color = 0x005fd7
				elif cc == 'core':
					color = 0x875fff
				else:
					color = 0xAAAAAA
			else:
				color = 0xAAAAAA

			if hasattr(x, 'value'):
				yield (x.value(), (), color)
			else:
				yield (x, (), color)
		else:
			# trailing spaces
			if spaces:
				yield ("#" * spaces, ('underline',), 0xaf0000, None)

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
		range_color_palette = range_color_palette,
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

		if positions[1] >= positions[2]:
			# after or at exclusive stop
			color = (range_color_palette['stop-exclusive'], 0)
		elif positions[1] < positions[0]:
			# before start
			color = (range_color_palette['start-exclusive'], 0)
		elif positions[0] == positions[1]:
			# position is on start
			color = (range_color_palette['start-inclusive'], 0)
		elif positions[2]-1 == positions[1]:
			# last included character
			color = (range_color_palette['stop-inclusive'], 0)
		else:
			color = (range_color_palette['offset-active'], 0)

		if invert:
			color = (color[1], color[0])

		return (text, style,) + color

	# modification to text string
	horizontal_transforms = {
		'start': calculate_horizontal_start_indicator,
		'stop': calculate_horizontal_stop_indicator,
		'position': calculate_horizontal_position_indicator,
	}

	def collect_horizontal_range(self,
		line, positions,
		len = len,
		whole = slice(None,None),
		address = libfields.address,
	):
		"""
		Collect the fragments of the horizontal range from the rendered unit.

		Used to draw the horizontal range background.

		Nearly identical to libfields.Segments.select()
		"""
		llen = len(line)
		astart = positions[0]
		astop = positions[-1]

		if astart < astop:
			start, stop = address([x[0] for x in line], astart, astop)
		else:
			#astart += 1
			#astop -= 1
			start, stop = address([x[0] for x in line], astop, astart)

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

	def collect_horizontal_positions(self, line, positions, len = len):
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

		wl = self.window_line(self.vertical_index)

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
		Changes the horizontal indicators.
		"""
		window = self.window.horizontal
		area = self.view.area
		shr = area.seek_horizontal_relative
		astyle = area.style

		line = list(self.draw(unit))
		hs = horizontal
		hr, prefix, suffix = self.collect_horizontal_range(line, hs)

		if self.keyboard.mapping == 'edit':
			range_style = ()
		else:
			range_style = ('underline',)

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
			range_part = [x[:1] + (x[1] + range_style, (x[2] or 0xAAAAAA) + 0x222222, range_color,) for x in text]

			set_range = [
				shr(rstart),
				b''.join(starmap(astyle, range_part)),
				shr(-((rstop - rstart) + rstart)),
			]
		else:
			range_part = [x[:1] + (x[1] + range_style, (x[2] or 0xAAAAAA) + 0x222222, range_color,) for x in hr[2]]
			clear_range = []
			set_range = []

		# rline is the unit line with the range changes
		rline = prefix + range_part + suffix

		# now the positions
		offset_and_size = tuple(zip(hs, (1,1,1)))
		hp = self.collect_horizontal_positions(rline, offset_and_size)

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
		wl = self.window_line(self.vertical_index)

		if wl < self.view.height and wl >= 0:
			h = self.horizontal
			h.limit(0, self.unit.characters())
			events = self.render_horizontal_indicators(self.unit, h.snapshot())
			seek = self.view.area.seek((0, wl))
			events.insert(0, seek)
			self.controller.emit(events)

		self.movement = True

	def window_line(self, line):
		"""
		Map the given absolute index to an index relative to the window.
		"""
		return line - self.window.vertical.datum

	def relative_index(self, rline):
		"""
		Map the given vertical index relative to the window to an absolute index.
		"""
		return self.window.vertical.datum - rline

	def change_unit(self, index):
		"""
		Move the current vertical position to the given index.
		"""
		self.vertical.move(index, 1)
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

	def display(self, start, stop, list = list):
		'Send the given line range to the display.'
		self.controller.emit(list(self.view.draw(*self.render(start, stop))))

	def refresh(self, start = 0):
		origin, top, bottom = self.window.vertical.snapshot()
		ub = len(self.units)
		rl = min(bottom, ub)
		r = range(top + start, rl)
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
		return isinstance(field, (libfields.Formatting, libfields.Constant)) or str(field) == " "

	def rotate(self, horizontal, unit, sequence, quantity, filtered = None):
		"""
		Select the next *significant* field, skipping the given quantity.

		The optional &filtered parameter will be given candidate fields
		that can be skipped.
		"""
		start, pos, stop = horizontal.snapshot()

		i = iter(sequence)

		r = unit.find(pos)
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
			horizontal.configure(offset or 0, n.length(), 0)
			self.update_horizontal_indicators()
			self.movement = True

	def event_console_save(self, event):
		console = self.controller
		console.prompt.prepare(libfields.String("write"), libfields.String(self.source))
		console.event_toggle_prompt(None)

	def event_console_seek_line(self, event):
		console = self.controller
		prompt = console.prompt
		prompt.prepare(libfields.String("seek"), libfields.String(""))
		prompt.event_select_horizontal_line(None)
		prompt.horizontal.move(1, -1)
		prompt.keyboard.set('edit')
		console.event_toggle_prompt(None)

	def event_field_cut(self, event):
		self.rotate(self.horizontal, sel, self.unit.subfields(), 1)
		sel[-2].delete(sel[-1])

	def truncate_vertical(self, start, stop):
		"""
		Remove a vertical range from the projection.
		"""
		# delete range
		units = self.units[start:stop]
		self.units.delete(start, stop)

		self.display(start, None)
		# handle case where the window extend beyond the document.
		nunits = len(self.units)
		if nunits < self.view.height:
			# erase any lines not updated beyond the EOF
			v = self.view
			wl = self.window_line(nunits)
			stop = wl + (stop-start)
			v.clear(wl, stop)
			self.controller.emit(list(v.render(wl, stop)))

		self.update_vertical_state()

		return (self.insert_vertical, (start, units))

	def insert_vertical(self, offset, sequence):
		"""
		"""
		self.units.insert(offset, sequence)
		self.update_unit()
		self.display(offset, None)
		return (self.truncate_vertical, (offset, offset + len(sequence)))

	def translocate_vertical(self, index, units, target, start, stop):
		"""
		Relocate the vertical range to the &target position.
		"""
		seq = units[start:stop]
		self.log(self.truncate_vertical(start, stop), IRange((start, stop-1)))
		size = stop - start
		if target >= start:
			target -= size
			if target < 0:
				target = 0
		self.log(self.insert_vertical(target, seq), IRange((target, target+size)))

	def translocate_horizontal(self, index, unit, target, start, stop):
		seq = str(unit[1])[start:stop]
		self.log(unit[1].delete(start, stop), IRange.single(index))

		# adjust target if it follows start
		size = stop - start
		if target >= start:
			target -= size
			if target < 0:
				target = 0

		r = IRange.single(index)
		self.log(unit[1].insert(target, libfields.String(seq)), r)
		unit[1].reformat()
		self.display(*r.exclusive())

	def event_delta_translocate(self, event):
		"""
		Relocate the range to the current position.
		"""
		axis = self.last_axis
		self.clear_horizontal_indicators()

		if axis == 'vertical':
			start, position, stop = self.vertical.snapshot()
			size = stop - start

			if position > start:
				newstart = position - size
				newstop = position
			else:
				newstart = position
				newstop = position + size

			self.translocate_vertical(None, self.units, position, start, stop)
			self.vertical.restore((newstart, self.vertical.get(), newstop))
			self.movement = True
		elif axis == 'horizontal':
			adjustment = self.indentation_adjustments(self.unit)
			start, position, stop = map((-adjustment).__add__, self.horizontal.snapshot())
			size = stop - start

			if position > start:
				newstart = position - size
				newstop = position
			else:
				newstart = position
				newstop = position + size

			self.translocate_horizontal(self.vertical_index, self.unit, position, start, stop)
			self.horizontal.restore((newstart, self.vertical.get(), newstop))
			self.movement = True
		else:
			pass

		self.checkpoint()

	def event_delta_transpose(self, event):
		"""
		Relocate the current range with the queued.
		"""
		axis = self.last_axis
		self.clear_horizontal_indicators()

		if axis == 'vertical':
			s1 = self.vertical.snapshot()

			self.event_navigation_range_dequeue(None)

			s2 = self.vertical.snapshot()

			# make s2 come second
			if s2[0] < s1[0]:
				s = s1
				s1 = s2
				s2 = s

			adjust = s2[2] - s2[0]

			self.translocate_vertical(None, self.units, s1[0], s2[0], s2[2])
			self.translocate_vertical(None, self.units, s2[0]+adjust, s1[0]+adjust, s1[2]+adjust)

			self.movement = True
		elif axis == 'horizontal':
			axis, dominate, current, range = self.range_queue.popleft()
			if axis == 'vertical':
				return

			s1_unit = self.units[dominate]
			s1_adjust = self.indentation_adjustments(self.unit)
			s1_range = tuple(map((-s1_adjust).__add__, range.exclusive()))

			s2_unit = self.unit
			s2_adjust = self.indentation_adjustments(self.unit)
			start, position, stop = map((-s2_adjust).__add__, self.horizontal.snapshot())
			s2_range = (start, stop)

			if s1_unit == s2_unit:
				# same line
				if s1_range[0] > s2_range[0]:
					r = s1_range
					s1_range = s2_range
					s2_range = r

				s1_range = (s1_range[0], min(s1_range[1], s2_range[0]))
				s2_range = (max(s1_range[1], s2_range[0]), s2_range[1])

				s = str(s1_unit[1])
				s1_text = s[s1_range[0]:s1_range[1]]
				s2_text = s[s2_range[0]:s2_range[1]]

				replacement = ''.join([
					s[:s1_range[0]],
					s2_text,
					s[s1_range[1]:s2_range[0]],
					s1_text,
					s[s2_range[1]:]
				])

				inverse = s1_unit[1].set([replacement])
				ir = IRange.single(self.vertical_index)
				self.log(inverse, ir)
				s1_unit[1].reformat()

				self.movement = True
				self.clear_horizontal_indicators()
				self.display(*ir.exclusive())
				self.update_horizontal_indicators()
			else:
				s1_text = str(s1_unit[1])[s1_range[0]:s1_range[1]]
				inverse = s1_unit[1].delete(s1_range[0], s1_range[1])
				s1_changelines = IRange.single(dominate)
				self.log(inverse, s1_changelines)

				s2_text = str(s2_unit[1])[s2_range[0]:s2_range[1]]
				inverse = s2_unit[1].delete(s2_range[0], s2_range[1])
				s2_changelines = IRange.single(self.vertical_index)
				self.log(inverse, s2_changelines)

				inverse = s1_unit[1].insert(s1_range[0], s2_text)
				self.log(inverse, s1_changelines)
				inverse = s2_unit[1].insert(s2_range[0], s1_text)
				self.log(inverse, s2_changelines)

				s1_unit[1].reformat()
				s2_unit[1].reformat()

				self.movement = True
				self.clear_horizontal_indicators()
				self.display(*s1_changelines.exclusive())
				self.display(*s2_changelines.exclusive())
				self.update_horizontal_indicators()
		else:
			pass

		self.checkpoint()

	def event_delta_truncate(self, event):
		"""
		Remove the range of the last axis.
		"""
		axis = self.last_axis
		self.clear_horizontal_indicators()

		if axis == 'vertical':
			start, position, stop = self.vertical.snapshot()

			self.log(self.truncate_vertical(start, stop), IRange((start, stop-1)))
			self.vertical.contract(0, stop - start)
			self.vertical.set(position)
			self.movement = True
		elif axis == 'horizontal':
			adjustment = self.indentation_adjustments(self.unit)
			start, position, stop = map((-adjustment).__add__, self.horizontal.snapshot())

			r = IRange.single(self.vertical_index)
			self.log(self.unit[1].delete(start, stop), r)
			abs = self.horizontal.get()
			self.horizontal.contract(0, stop - start)
			self.horizontal.set(abs)
			self.display(*r.exclusive())
			self.movement = True
		else:
			pass

		self.checkpoint()
		self.update_unit()
		self.update_horizontal_indicators()

	def event_select_horizontal_line(self, event, quantity=1):
		"""
		Alter the horizontal range to be the length of the current vertical index.
		"""
		h = self.horizontal

		abs = h.get()
		adjust = self.unit[0].length()
		ul = self.unit.length()

		self.clear_horizontal_indicators()

		h.configure(adjust, ul - adjust)
		self.vector_last_axis = h
		self.horizontal_query = 'line'

		if abs < adjust:
			h.offset = 0
		elif abs >= ul:
			h.offset = h.magnitude
		else:
			h.move(abs - h.datum)

		self.update_horizontal_indicators()

	def event_select_vertical_line(self, event, quantity=1):
		"""
		Alter the vertical range to contain a single line.
		"""
		v = self.vertical
		abs = v.get()
		v.configure(abs, 1)
		self.vector_last_axis = v
		self.movement = True

	def event_select_series(self, event):
		"""
		Expand the horizontal range to include fields separated by an access, routing, delimiter.
		"""
		line = self.unit[1]
		fields = list(self.unit.subfields())
		offset = self.horizontal.get()

		current = 0
		index = 0
		for path, field in fields:
			l = field.length()
			if offset - l < current:
				break
			index += 1
			current += l

		# index is the current field
		nfields = len(fields)
		start = index

		for i in range(index, nfields):
			path, f = fields[i]
			if f.merge == False and f not in line.routers:
				break
		else:
			# series query while on edge of line.
			return

		stop = self.unit.offset(*fields[i])

		for i in range(index, -1, -1):
			path, f = fields[i]
			if isinstance(f, libfields.Indentation):
				i = 1
				break
			if f.merge == False and f not in line.routers:
				i += 1
				break
		start = self.unit.offset(*fields[i])

		self.horizontal_query = 'series'
		h = self.vector_last_axis = self.horizontal

		h.restore((start, offset, stop))
		self.update_horizontal_indicators()

	def event_select_block(self, event, quantity=1):
		self.vertical_query = 'indentation'
		self.block((self.vertical_index, self.vertical_index, self.vertical_index+1))

	def event_select_outerblock(self, event, quantity=1):
		self.vertical_query = 'indentation'
		self.outerblock(self.vector.vertical.snapshot())

	def event_select_adjacent(self, event, quantity=1):
		self.vertical_query = 'adjacent'
		self.adjacent((self.vertical_index, self.vertical_index, self.vertical_index))

	def event_place_start(self, event):
		a = self.axis
		d, o, m = a.snapshot()
		a.restore((o, o, m))

		self.movement = True
		if self.last_axis == 'horizontal':
			self.update_horizontal_indicators()

	def event_place_stop(self, event):
		a = self.axis
		d, o, m = a.snapshot()
		a.restore((d, o, o))

		self.movement = True
		if self.last_axis == 'horizontal':
			self.update_horizontal_indicators()

	def seek(self, vertical_index):
		"""
		Go to a specific vertical index.
		"""
		v = self.vector.vertical
		d, o, m = v.snapshot()
		self.clear_horizontal_indicators()
		v.restore((d, vertical_index, m))
		self.update_vertical_state()
		self.movement = True
		self.update_horizontal_indicators()

	# line [history] forward/backward
	def event_navigation_vertical_forward(self, event, quantity = 1):
		v = self.vertical
		self.clear_horizontal_indicators()
		v.move(quantity)
		self.vector_last_axis = v
		self.update_vertical_state()
		self.movement = True
		self.update_horizontal_indicators()

	def event_navigation_vertical_backward(self, event, quantity = 1):
		v = self.vertical
		self.clear_horizontal_indicators()
		v.move(-quantity)
		self.vector_last_axis = v
		self.update_vertical_state()
		self.movement = True
		self.update_horizontal_indicators()

	def event_navigation_vertical_paging(self, event, quantity = 1):
		v = self.vector.vertical
		win = self.window.vertical.snapshot()
		v.restore((win[0], v.get(), win[2]))

		self.vector_last_axis = v
		self.vertical_query = 'paging'
		self.update_vertical_state()
		self.movement = True

	def event_navigation_vertical_sections(self, event, quantity = 1):
		v = self.vector.vertical
		win = self.window.vertical.snapshot()
		height = abs(int((win[2] - win[0]) / 2.5))
		v.restore((win[0] + height, v.get(), win[2] - height))

		self.vertical_query = 'paging'
		self.vector_last_axis = v
		self.update_vertical_state()
		self.movement = True

	# line [history] forward/backward
	def event_window_vertical_forward(self, event, quantity = 1):
		self.clear_horizontal_indicators()
		self.window.vertical.move(quantity)
		self.movement = True
		self.scrolled()
		self.update_horizontal_indicators()

	def event_window_vertical_backward(self, event, quantity = 1):
		self.clear_horizontal_indicators()
		self.window.vertical.move(-quantity)
		self.movement = True
		self.scrolled()
		self.update_horizontal_indicators()

	def vertical_query_previous(self):
		v = self.vertical
		qtype = self.vertical_query
		if qtype == 'paging':
			v.page(-1)
		elif qtype == 'pattern':
			start = 0
			stop = v.get()
			nunits = len(self.units)
			index = -1
			i = 0

			searching = 2
			while searching:
				units = zip(reversed(list(self.units.select(start, stop))), range(stop-1, start-1, -1))

				for u, i in units:
					index = str(u[1]).rfind(self.pattern)
					if index > -1:
						break
				else:
					searching -= 1
					start = stop
					stop = nunits
					continue

				# found match
				break

			if index > -1:
				self.horizontal.configure(self.indentation_adjustments(u) + index, len(self.pattern))
				v.set(i)
		else:
			vi = self.vertical_index
			self.block((vi-2, vi-1, vi-1), self.level, maximum=vi-1)

	def event_navigation_vertical_start(self, event):
		v = self.vertical
		self.vector_last_axis = v
		self.clear_horizontal_indicators()

		if v.offset == 0 or self.vertical_query == 'pattern':
			# already at beginning, imply previous block at same level
			self.vertical_query_previous()
		else:
			v.offset = 0

		self.update_vertical_state()
		self.constrain_horizontal_range()
		self.update_horizontal_indicators()

	def vertical_query_next(self):
		v = self.vertical
		qtype = self.vertical_query
		if qtype == 'paging':
			v.page(1)
		elif qtype == 'pattern':
			vi = v.get() + 1
			l = len(self.units)
			index = -1
			i = vi

			searching = 2
			while searching:
				units = zip(self.units.select(vi,l), itertools.count(vi))

				for u, i in units:
					index = str(u[1]).find(self.pattern)
					if index > -1:
						break
				else:
					searching -= 1
					l = vi
					vi = 0
					continue

				# found match
				break

			if index > -1:
				self.horizontal.configure(self.indentation_adjustments(u) + index, len(self.pattern))
				v.set(i)
		else:
			vi = self.vertical_index
			self.block((vi, vi, vi+1), self.level, minimum = vi)

	def event_navigation_vertical_stop(self, event):
		v = self.vertical
		self.vector_last_axis = v
		self.clear_horizontal_indicators()

		if v.offset == v.magnitude or self.vertical_query == 'pattern':
			# already at end, imply next block at same level
			self.vertical_query_next()
		else:
			v.offset = v.magnitude

		self.update_vertical_state()
		self.constrain_horizontal_range()
		self.update_horizontal_indicators()
		self.movement = True

	# horizontal

	def event_navigation_horizontal_forward(self, event, quantity = 1):
		"""
		Move the selection to the next significant field.
		"""
		h = self.horizontal
		self.vector_last_axis = h
		self.rotate(h, self.unit, self.unit.subfields(), quantity)
		self.update_horizontal_indicators()

	def event_navigation_horizontal_backward(self, event, quantity = 1):
		"""
		Move the selection to the previous significant field.
		"""
		h = self.horizontal
		self.vector_last_axis = h
		self.rotate(h, self.unit, reversed(list(self.unit.subfields())), quantity)
		self.update_horizontal_indicators()

	def event_navigation_horizontal_start(self, event):
		h = self.horizontal
		self.vector_last_axis = h

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

	def event_navigation_horizontal_stop(self, event):
		h = self.horizontal
		self.vector_last_axis = h

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

	def event_navigation_forward_character(self, event, quantity = 1):
		h = self.horizontal
		self.vector_last_axis = h

		h.move(quantity)
		h.limit(0, self.unit.characters())
		self.update_horizontal_indicators()
	event_control_space = event_navigation_forward_character

	def event_navigation_backward_character(self, event, quantity = 1):
		h = self.vector.horizontal
		self.vector_last_axis = h

		h.move(-quantity)
		h.limit(self.get_indentation_level().length(), self.unit.characters())
		self.update_horizontal_indicators()
	event_control_backspace = event_navigation_forward_character

	def indentation_adjustments(self, unit):
		return libfields.indentation(self.unit).characters()

	def event_navigation_jump_character(self, event, quantity = 1):
		h = self.vector.horizontal
		self.vector_last_axis = h

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
			h.set(offset + il)
			self.update_horizontal_indicators()

	def select_void(self, linerange, ind = libfields.indentation):
		v = self.vector.vertical
		self.vector_last_axis = v

		for i in linerange:
			u = self.units[i]
			if ind(u) == 0 and u.length() == 0:
				self.clear_horizontal_indicators()
				v.move(i-v.get())
				self.horizontal.configure(0, 0, 0)
				self.update_vertical_state()
				self.constrain_horizontal_range()
				self.update_horizontal_indicators()
				self.movement = True
				break
		else:
			# ignore; no void
			pass

	def event_navigation_void_forward(self, event):
		self.select_void(range(self.vertical_index+1, len(self.units)))

	def event_navigation_void_backward(self, event):
		self.select_void(range(self.vertical_index-1, -1, -1))

	def range_enqueue(self, vector, axis):
		position = getattr(self.vector, axis)
		start, point, stop = axis.snapshot()

		if axis == 'horizontal':
			self.range_queue.append((axis, vector.vertical.get(), point, IRange((start, stop-1))))
		elif axis == 'vertical':
			self.range_queue.append((axis, None, None, IRange((start, stop-1))))
		else:
			raise Exception("unknown axis")

	def event_navigation_range_enqueue(self, event):
		start, point, stop = self.axis.snapshot()
		axis = self.last_axis

		if axis == 'horizontal':
			self.range_queue.append((axis, self.vertical.get(), point, IRange((start, stop-1))))
		elif axis == 'vertical':
			self.range_queue.append((axis, None, None, IRange((start, stop-1))))
		else:
			raise Exception("unknown axis")

	def event_navigation_range_dequeue(self, event):
		axis, dominate, current, range = self.range_queue.popleft()

		if axis == 'horizontal':
			self.clear_horizontal_indicators()
			self.vertical.set(dominate)
			self.horizontal.restore((range[0], self.horizontal.get(), range[1]+1))
			self.update_vertical_state()
			self.update_horizontal_indicators()
		elif axis == 'vertical':
			# no move is performed, so indicators don't need to be updaed.
			self.vertical.restore((range[0], self.vertical.get(), range[1]+1))
			self.movement = True
		else:
			raise Exception("unknown axis")

	def new(self,
		Class = lineslib.profile('text')[0],
		indentation = libfields.Indentation.acquire(0),
		Sequence = libfields.Sequence,
		String = libfields.String
	):
		return Sequence((indentation, Class(String(""))))

	def open_vertical(self, il, position, quantity, temporary = False, len = len):
		"""
		Create a quantity of new lines at the cursor position.
		"""
		vi = self.vertical_index
		nunits = len(self.units)
		new = min(vi + position, nunits)

		if new < nunits:
			relation = self.units[new][1].__class__
		elif nunits:
			relation = self.units[vi][1].__class__
		else:
			relation = self.document_line_class

		self.units[new:new] = [self.new(relation, il) for x in range(quantity)]
		start = new

		v = self.vertical
		v.expand(new - v.get(), quantity)
		v.set(start)
		#v.configure(start, quantity, 0)
		self.vector_last_axis = v

		self.horizontal.configure(il.length(), 0)

		self.clear_horizontal_indicators()
		self.update_unit()
		self.update_window()
		self.display(max(0, new-quantity), None)

		return ((self.truncate_vertical, (new, new+quantity)), IRange((new, new+quantity-1)))

	def clear_horizontal_state(self):
		"""
		Zero out the horizontal cursor.
		"""
		self.horizontal.configure(0,0,0)

	def clear_vertical_state(self):
		"""
		Zero out the horizontal cursor.
		"""
		self.vertical.collapse()
		self.update_vertical_state()

	def get_indentation_level(self):
		'Get the indentation level of the line at the current vertical position.'
		return libfields.indentation(self.unit)

	def event_open_behind(self, event, quantity = 1):
		inverse = self.open_vertical(self.get_indentation_level(), 0, quantity)
		self.log(*inverse)
		self.keyboard.set('edit')
		self.movement = True
		self.update_horizontal_indicators()

	def event_open_ahead(self, event, quantity = 1):
		inverse = self.open_vertical(self.get_indentation_level(), 1, quantity)
		self.log(*inverse)
		self.keyboard.set('edit')
		self.movement = True
		self.update_horizontal_indicators()

	def event_open_into(self, event):
		h = self.horizontal
		hs = h.snapshot()
		self.clear_horizontal_indicators()

		adjustment = self.indentation_adjustments(self.unit)
		start, position, stop = map((-adjustment).__add__, hs)

		remainder = str(self.unit[1])[position:]

		r = IRange.single(self.vertical_index)
		self.log(self.unit[1].delete(position, position+len(remainder)), r)

		ind = libfields.Indentation.acquire(self.get_indentation_level() + 1)
		inverse = self.open_vertical(ind, 1, 2)
		self.log(*inverse)

		new = self.units[self.vertical.get()+1][1]
		nr = IRange.single(self.vertical_index+1)

		self.log(new.insert(0, remainder), nr)
		new.reformat()

		self.display(self.vertical_index-1, None)
		self.update_horizontal_indicators()
		self.movement = True

	def event_edit_return(self, event, quantity = 1):
		inverse = self.open_vertical(self.get_indentation_level(), 1, quantity)
		self.log(*inverse)
		self.movement = True
		self.update_horizontal_indicators()

	def event_open_temporary(self, event, quantity = 1):
		pass

	def event_delta_substitute(self, event):
		"""
		Substitute the contents of the selection.
		For structured fields, this will clear the all of the subfields.
		"""
		h = self.horizontal
		adjustments = self.indentation_adjustments(self.unit)
		start, position, stop = map((-adjustments).__add__, h.snapshot())
		vi = self.vertical_index

		inverse = self.unit[1].delete(start, stop)
		r = IRange.single(vi)
		self.log(inverse, r)

		h.zero()
		self.clear_horizontal_indicators()
		self.display(*r.exclusive())
		self.transition_keyboard('edit')
		self.movement = True

	def event_delta_substitute_previous(self, event):
		"""
		Substitute the horizontal selection with previous substitution later.
		"""
		h = self.horizontal
		adjustments = self.indentation_adjustments(self.unit)
		start, position, stop = map((-adjustments).__add__, h.snapshot())

		self.clear_horizontal_indicators()

		self.unit[1].delete(start, stop)
		le = self.last_edit
		self.unit[1].insert(start, le)
		self.unit[1].reformat()

		self.horizontal.configure(start+adjustments, len(le))
		self.display(*self.current_vertical.exclusive())
		self.update_horizontal_indicators()

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

	def insert_characters(self, characters):
		"""
		Insert characters into the focus.
		"""
		v = self.vector.vertical
		h = self.vector.horizontal

		text = self.unit[1]

		if isinstance(characters, libfields.String):
			chars = characters
		else:
			if characters in text.constants:
				chars = text.constants[characters]
			else:
				chars = libfields.String(characters)

		adjustments = self.unit[0].length()

		offset = h.get() - adjustments

		u = v.get()
		inverse = text.insert(offset, chars)
		r = IRange.single(u)
		self.log(inverse, r)

		h.expand(h.offset, len(chars))

		self.clear_horizontal_indicators()
		self.display(*r.exclusive())
		self.update_horizontal_indicators()

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

		u = v.get()
		r = IRange.single(u)
		inverse = self.unit[1].delete(start, stop)
		self.log(inverse, r)

		h.contract(h.offset, l)
		if quantity > 0:
			h.move(quantity)

		self.clear_horizontal_indicators()
		self.display(*r.exclusive())
		self.update_horizontal_indicators()

	def event_insert_character(self, event):
		"""
		Insert a character at the current cursor position.
		"""
		if event.type == 'literal':
			self.insert_characters(event.string)

	def transition_insert_character(self, key):
		"""
		Used as a capture hook to insert literal characters.
		"""
		if key.type == 'literal':
			self.insert_characters(key.string)
			self.delete_characters(1)
		self.transition_keyboard(self.previous_keyboard_mode)
		del self.previous_keyboard_mode

	def event_delta_replace_character(self, event):
		"""
		Replace the character underneath the cursor and progress its position.
		"""
		self.event_capture = self.transition_insert_character
		self.previous_keyboard_mode = self.keyboard.current[0]
		self.transition_keyboard('capture')

	def transition_keyboard(self, mode):
		old_mode = self.keyboard.current[0]
		if old_mode == mode:
			return

		self.clear_horizontal_indicators()
		self.keyboard.set(mode)
		if self.focused:
			self.update_horizontal_indicators()

	def event_transition_control(self, event):
		self.transition_keyboard('control')

	def event_transition_edit(self, event):
		"""
		Transition into edit-mode. If the line does not have an initialized field
		or the currently selected field is a Constant, an empty Text field will be created.
		"""
		self.transition_keyboard('edit')

	def horizontal_selection(self):
		'Get the string of the current horizontal selection.'
		h = self.horizontal
		adjustments = self.indentation_adjustments(self.unit)
		start, position, stop = map((-adjustments).__add__, h.snapshot())
		return str(self.unit[1])[start:stop]

	def record_last_edit(self):
		'Record the text of the edit performed.'
		self.last_edit = self.horizontal_selection()

	def event_edit_commit(self, event):
		self.checkpoint()
		self.record_last_edit()
		self.transition_keyboard('control')

	def event_edit_abort(self, event):
		"""
		Exit edit mode and revert all alterations that were made while editing.
		"""
		self.undo(1)
		self.transition_keyboard('control')

	def event_edit_space(self, event):
		"""
		Insert a constant into the field sequence and
		create a new text field for further editing.
		"""
		self.insert_characters(libfields.Delimiter(' '))

	def event_delta_insert_space(self, event):
		'Insert a literal space'
		self.insert_characterslibfields.Delimiter((' '))

	def indent(self, sequence, quantity = 1, ignore_empty = False,
		IClass = libfields.Indentation.acquire
	):
		"""
		Increase or decrease the indentation level of the given sequence.

		The sequence is prefixed with a constant corresponding to the tab-level,
		and replaced when increased.
		"""
		h = self.vector.horizontal

		l = 0
		if not sequence or not isinstance(sequence[0], libfields.Indentation):
			new = init = IClass(quantity)
			sequence.prefix(init)
		else:
			init = sequence[0]
			l = init.length()
			level = init + quantity
			if level < 0:
				level = 0
			new = sequence[0] = IClass(level)

		# contract or expand based on tabsize
		h.datum += (new.length() - l)
		if h.datum < 0:
			h.datum = 0
		h.constrain()

		self.update_horizontal_indicators()

	def event_indent_increment(self, event, quantity = 1):
		self.clear_horizontal_indicators()
		self.indent(self.unit, quantity)

		r = IRange.single(self.vertical_index)
		self.log((self.indent, (self.unit, -quantity)), r)

		self.display(*r.exclusive())
		self.constrain_horizontal_range()

	def event_indent_decrement(self, event, quantity = 1):
		self.clear_horizontal_indicators()
		self.indent(self.unit, -quantity)

		r = IRange.single(self.vertical_index)
		self.log((self.indent, (self.unit, quantity)), r)

		self.display(*r.exclusive())
		self.constrain_horizontal_range()

	event_edit_tab = event_indent_increment
	event_edit_shift_tab = event_indent_decrement

	def print_unit(self):
		self.controller.transcript.write(repr(self.unit)+'\n')
		self.controller.transcript.write(repr(self.controller.cache.storage))

	def event_delta_delete_backward(self, event, quantity = 1):
		self.delete_characters(quantity * -1)

	def event_delta_delete_forward(self, event, quantity = 1):
		self.delete_characters(quantity)

	def event_copy(self, event):
		'Copy the range to the default cache entry.'
		if self.last_axis == 'vertical':
			start, p, stop = self.vertical.snapshot()
			r = '\n'.join([
				''.join(map(str, x.value())) for x in
				self.units.select(start, stop)
			])
		else:
			r = str(self.unit[1])[self.horizontal.slice()]
		self.controller.cache.put(None, ('text', r))

	def event_delta_split(self, event):
		h = self.horizontal
		hs = h.snapshot()
		self.clear_horizontal_indicators()

		adjustment = self.indentation_adjustments(self.unit)
		start, position, stop = map((-adjustment).__add__, hs)

		remainder = str(self.unit[1])[position:]

		r = IRange.single(self.vertical_index)
		self.log(self.unit[1].delete(position, position+len(remainder)), r)

		inverse = self.open_vertical(self.get_indentation_level(), 1, 1)
		self.log(*inverse)

		new = self.unit[1]
		nr = IRange.single(self.vertical_index)

		self.log(new.insert(0, remainder), nr)
		new.reformat()

		self.display(self.vertical_index-1, None)
		self.update_horizontal_indicators()
		self.movement = True

	def event_delta_join(self, event):
		join = self.unit[1]
		ulen = self.unit.characters()
		collapse = self.vertical_index+1
		following = str(self.units[collapse][1])

		joinlen = len(join.value())
		self.log(join.insert(joinlen, following), IRange.single(self.vertical_index))
		join.reformat()

		self.log(self.truncate_vertical(collapse, collapse+1), IRange.single(collapse))

		self.display(self.vertical_index, None)
		h = self.horizontal.set(ulen)
		self.update_horizontal_indicators()
		self.movement = True

	def unit_class(self, index, len = len):
		'Get the corresponding line class for hte index'
		if len(self.units):
			return self.units[index][1].__class__
		else:
			return self.document_line_class

	def paste(self, index, cache = None, Sequence = libfields.Sequence):
		typ, s = self.controller.cache.get(cache)
		sl = str(s).split('\n')
		nl = len(sl)

		Class = self.unit_class(self.vertical_index)
		parse = Class.parse

		paste = []
		for x in sl:
			ind, *line = parse(x)
			seq = Sequence((ind, Class.from_sequence(line)))
			paste.append(seq)

		r = (index, index+nl)
		self.units[r[0]:r[0]] = paste
		self.display(r[0], None)
		self.log((self.truncate_vertical, r), IRange((r[0], r[1]-1)))

	def event_paste_after(self, event):
		self.paste(self.vertical_index+1)

	def event_paste_before(self, event):
		self.paste(self.vertical_index)

	def event_paste_into(self, event):
		pass

	def focus(self):
		super().focus()
		self.update_horizontal_indicators()

	def blur(self):
		super().blur()
		self.clear_horizontal_indicators()

class Lines(Fields):
	"""
	Fields based line editor.
	"""
	def __init__(self, line_class = lineslib.profile('text')[0]):
		super().__init__()
		self.keyboard.set('control')
		self.source = None
		self.document_line_class = line_class

		initial = self.new(line_class)
		self.units = libfields.Segments([initial])
		self.unit = initial
		nunits = len(self.units)
		self.vector.vertical.configure(0, nunits, 0)

	def serialize(self, write, chunk_size = 128, encoding = 'utf-8'):
		size = 0

		for i in range(0, len(self.units), chunk_size):
			cws = self.units.select(i, i+chunk_size)
			c = '\n'.join([''.join(x.value()) for x in cws])
			c = c.encode(encoding)
			write(c)
			write(b'\n')
			size += len(c) + 1

		return size

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

class Prompt(Lines):
	"""
	The prompt providing access to the console's command interface.

	This projection manages the last two lines on the screen and provides
	a globally accessible command interface for managing the content panes.

	The units of a prompt make up the history.
	"""
	margin = 0

	def sequence(self, unit):
		current = ""

		for path, x in unit.subfields():
			if isinstance(x, libfields.FieldSeparator) and x:
				yield current
				current = ""
			elif isinstance(x, libfields.Formatting):
				pass
			else:
				current += x.value()
		else:
			# a trailing empty field will be ignored
			if current:
				yield current

	def execute(self, event):
		command = list(self.sequence(self.unit))
		cname = command[0]

		method = getattr(self, 'command_' + cname)
		result = method(*command[1:])
		self.event_open_ahead(event)
		self.window.vertical.move(1)
		self.scrolled()
		self.transition_keyboard('control')

	event_edit_return = execute
	event_control_return = execute

	def prepare(self, *fields):
		"""
		Set the command line to a sequence of fields.
		"""
		self.unit[1].sequences = list(itertools.chain.from_iterable(
			zip(fields, itertools.repeat(self.separator, len(fields)))
		))
		self.controller.emit(self.refresh())

	def event_edit_space(self, event):
		self.insert_characters(self.separator)

	def event_edit_tab(self, event):
		self.insert_characters(libfields.space)

	def event_edit_shift_tab(self, event):
		pass

	def command_system(self, command, *args, **environ):
		pass

	def command_exit(self):
		"""
		Immediately exit the process. Unsaved files will not be saved.
		"""
		self.context.process.terminate(0)

	def command_forget(self):
		"""
		Destroy the prompt's history.
		"""
		pass

	def command_search(self,
		term : 'string',
	):
		console = self.controller
		p = console.visible[console.pane]
		p.find(term)
		console.focus_pane()

	def command_printobject(self):
		console = self.controller
		p = console.visible[console.pane]
		p.print_unit()

	def command_open(self,
		source : 'route',
		type : 'type' = None,
		mechanism : 'type' = 'Lines',
		encoding : 'encoding' = 'utf-8',
	):
		"""
		Open a new projection using the identified source.

		The implementation will be selected based on the file type.
		"""
		console = self.controller

		if type is None:
			profile = lineslib.profile_from_filename(source)
		else:
			profile = type

		Line, mod = lineslib.profile(profile)

		i = []
		new = Lines(Line)
		path = os.path.abspath(source)

		if os.path.exists(path):
			# open empty if it doesn't exist
			with open(path, encoding = encoding) as f:
				parse = Line.parse

				seq = libfields.Sequence
				txt = Line.from_sequence
				append = i.append

				for x in f.readlines():
					indentation, *line = parse(x)
					append(seq((indentation, txt(line))))

		new.source = path
		new.units = libfields.Segments(i)

		new.inherit(self.controller)
		console.panes.append(new)

		console.display_projection(console.pane, new)
		console.focus_pane()

	def command_write(self, target : 'path'):
		"""
		Write the value of the current working pane to the given target.
		"""
		console = self.controller

		with open(target, 'w+b') as f:
			p = console.visible[console.pane]
			size = p.serialize(f.write)
			self.controller.transcript.write('%d\n' %(size,))
			f.truncate(size)
			f.flush()

		console.focus_pane()

	def command_seek(self, vertical_index : 'whole number'):
		"""
		Move the projection's vector to a specific vertical index. (Line Number).
		"""
		console = self.controller
		#p = console.projection
		p = console.visible[console.pane]
		p.seek(int(vertical_index) - 1)

		console.focus_pane()

	def command_close(self):
		"""
		Close the current working pane.
		"""
		console = self.controller
		p = console.visible[console.pane]
		if len(console.visible) == len(console.panes):
			return

		console.event_pane_rotate_projection(None)
		if p is not console.transcript:
			del console.panes[console.panes.index(p)]

	def command_chsrc(self, target : 'path'):
		"""
		Change the source of the current working pane.
		"""
		console = self.controller
		p = console.visible[console.pane]
		p.source = target

	def command(self, event):
		pass

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

		self.bottom += nlines
		if self.view is not None:
			self.controller.emit(self.refresh())

	def reveal(self):
		super().reveal()
		self.bottom = len(self.lines)

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

def output(transformer, queue, tty):
	"""
	Thread transformer function receiving display transactions and writing to the terminal.
	"""
	write = tty.write
	flush = tty.flush
	get = queue.get
	while True:
		try:
			while True:
				out = get()
				write(b''.join(out))
				flush()
		except BaseException as exception:
			transformer.context.process.exception(transformer, exception, "Terminal Output")

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

class Cache(object):
	"""
	Mapping interface for user trans-projection communication.

	Maintains a set of slots for storing a sequence of typed objects; the latest item
	in the slot being the default. A sequence is used in order to maintain a history of
	cached objects. The configured limit restricts the number recalled.

	Console clipboard.
	"""
	__slots__ = ('storage', 'limit')
	Storage = dict
	Sequence = collections.deque

	def __init__(self, limit = 8):
		self.storage = self.Storage()
		self.limit = limit

	def allocate(self, *keys):
		'Initialize a cache slot.'
		for k in keys:
			if k not in self.storage:
				self.storage[k] = self.Sequence()

	def index(self):
		'Return a sequence of storage slots.'
		return self.storage.keys()

	def put(self, key, cobject):
		'Put the given object as the cache entry.'
		slot = self.storage[key]
		type, object = cobject
		slot.append((type, object))

		if len(slot) > self.limit:
			slot.popleft()

	def get(self, key, offset = 0):
		'Get the contents of the cache slot.'
		r = self.storage[key][-(1 + offset)]

		if r[0] == 'reference':
			r = r[1]()

		return r

	def clear(self, key):
		'Remove the all the contents of the given slot.'
		self.storage[key].clear()

class Console(core.Join):
	"""
	The application that responds to keyboard input in order to make display changes.
	"""
	def __init__(self):
		self.tty = None
		self.cache = Cache() # user cache / clipboard index
		self.cache.allocate(None)
		self.display = libterminal.Display() # used to draw the frame.
		self.transcript = Transcript() # the always available in memory buffer
		self.status = Status() # the status line
		self.prompt = Prompt() # prompt below status

		self.refreshing = set() # set of panes to be refreshed
		self.motion = set() # set of panes whose position indicators changed

		self.areas = {
			'status': libterminal.Area(),
			'prompt': libterminal.Area(),
			'panes': (libterminal.Area(), libterminal.Area()),
		}

		self.panes = [self.transcript, Lines(), Lines()]
		self.rotation = 0
		self.visible = list(self.panes[:2])

		self.pane = 1 # focus pane (visible)
		self.projection = self.panes[1] # focus projection; receives events

	def install(self, tty):
		self.tty = tty
		self.dimensions = self.get_display_dimensions()

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

	def display_projection(self, pane, projection):
		"""
		Display the &projection on the designated pane.
		"""
		if projection in self.visible:
			# already displayed; focus?
			return

		current = self.visible[pane]
		self.emit([self.clear_position_indicators(current)])
		current.conceal()
		current.pane = None
		v = current.view
		current.connect(None)

		self.emit([v.area.clear()])

		self.visible[pane] = projection
		projection.pane = pane
		projection.connect(v)

		if self.projection is current:
			self.projection = projection

		projection.calibrate(v.area.dimensions)
		projection.reveal()
		self.emit([self.set_position_indicators(projection)])
		self.emit(projection.refresh())

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
		self.prompt.adjust((0, height-1), (width, 1)) # width change

		pheight = height - 3

		for p, i in zip(self.visible, range(n)):
			p.pane = i
			left, right = self.pane_verticals(i)
			left += 1
			p.adjust((left, 0), (min(right - left, (width-1) - left), pheight))

		return self.frame()

	def frame(self, color = 0x222222, nomap = str.maketrans({})):
		"""
		Draw the frame of the console. Vertical separators and horizontal.
		"""
		display = self.display
		seek = display.seek
		style = display.style

		n = len(self.visible)
		width, height = self.dimensions
		pane_size = width // n
		vh = height - 3 # vertical separator height and horizontal position

		# horizontal
		yield seek((0, vh))
		yield style(symbols.lines['horizontal'] * self.dimensions[0], color = color)

		# verticals
		seq = symbols.lines['vertical'] + '\n\b'
		top = symbols.lines['vertical'] + '\n\b'
		bottom = symbols.intersections['bottom']
		bottom_left = symbols.corners['bottom-left']
		bottom_right = symbols.corners['bottom-right']
		seq = style((seq * vh) + bottom, color = color, control_map = nomap)

		# initial vertical
		yield seek((0, 0)) + seq

		last = None
		for i in range(0, n-1):
			left, right = self.pane_verticals(i)
			if last != left:
				yield seek((left, 0)) + seq
			yield seek((right, 0)) + seq
			last = right

		# edge of screen; no need to backspace
		seq = symbols.lines['vertical'] + '\n'
		seq = style((seq * vh) + bottom, color = color, control_map = nomap)

		yield seek((width, 0)) + seq
		# corners
		yield seek((width, height - 3)) + style(bottom_right, color = color, control_map = nomap)
		yield seek((0, height - 3)) + style(bottom_left, color = color, control_map = nomap)

	def set_position_indicators(self, projection,
		colors=(0x008800, 0xF0F000, 0x880000),
		vprecede=symbols.wedges['up'],
		vproceed=symbols.wedges['down'],
		vwedges=(symbols.wedges['right'], symbols.wedges['left']),
		hprecede=symbols.wedges['left'],
		hproceed=symbols.wedges['right'],
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
			hpointer = symbols.wedges['up']
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
			hpointer = symbols.wedges['down']
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
		h_bottom_left = symbols.corners['bottom-left'],
		h_bottom_right = symbols.corners['bottom-right'],
		color = 0x222222
	):
		"""
		Clear the position indicators on the frame.
		"""
		events = bytearray()

		if projection.snapshot is None:
			return events

		seek = self.display.seek
		style = self.display.style

		# (horiz, vert) tuples
		vec, win = projection.snapshot # stored state

		verticals = self.pane_verticals(projection.pane)
		v_limit = self.dimensions[1] - 3

		vtop = win[1][1]

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
				vertical_set.add(left)
				vertical_set.add(right)

		h_vertical = self.dimensions[1] - 3 # status and prompt

		corners = {0: h_bottom_left, self.dimensions[0]: h_bottom_right}

		for x in vec[0]:
			if x < 0:
				x = h_offset
			elif x > h_limit:
				x = h_limit
			else:
				x += h_offset

			if x in vertical_set:
				sym = corners.get(x, h_intersection)
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
		self.dimensions = self.get_display_dimensions()

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
		self.prompt.inherit(self)

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

	def event_process_exit(self, event):
		self.context.process.terminate(1)

	def focus(self, projection):
		"""
		Focus the given projection, blurring the current.
		"""
		assert projection in (self.status, self.prompt) or projection in self.visible

		cp = self.projection
		if cp is projection:
			return

		cp.blur()
		self.projection = projection
		projection.focus()

	def focus_prompt(self):
		"""
		Focus the prompt.
		"""
		return self.focus(self.prompt)

	def focus_pane(self):
		"""
		Focus the [target] pane.
		"""
		return self.focus(self.visible[self.pane])

	def event_toggle_prompt(self, event):
		"""
		Toggle the focusing of the prompt.
		"""
		if self.projection is self.prompt:
			self.focus_pane()
		else:
			self.focus_prompt()

	def event_prepare_open(self, event):
		prompt = self.prompt
		prompt.prepare(libfields.String("open"), libfields.String(""))
		prompt.event_select_horizontal_line(None)
		prompt.horizontal.move(1, -1)
		prompt.keyboard.set('edit')
		self.event_toggle_prompt(None)

	def event_pane_rotate_projection(self, event, direction = 1):
		"""
		Display the next projection in the current working pane according to
		the persistent rotation state.
		"""
		pid = self.pane
		visibles = self.visible
		current = self.visible[pid]
		npanes = len(self.panes)

		if direction > 0:
			start = 0
			stop = npanes
		else:
			start = npanes - 1
			stop = -1

		rotation = self.rotation + direction
		i = itertools.chain(range(rotation, stop, direction), range(start, rotation, direction))

		for r in i:
			p = self.panes[r]

			if p in visibles:
				continue

			# found a projection
			break
		else:
			# cycled; all panes visible
			return

		self.rotation = r
		self.display_projection(pid, p)

	def switch_pane(self, pane):
		"""
		Focus the given pane.

		The new focus pane will only receive a &Projection.focus call iff
		the old pane's projection is the current receiver, &Console.projection.
		"""
		if pane == self.pane:
			return

		old = self.visible[self.pane]
		new = self.visible[pane]

		if self.projection is old:
			old.blur()
			self.pane = pane
			self.projection = new
			new.focus()
		else:
			self.pane = pane

		return new

	def event_console_rotate_pane(self, event):
		"""
		Select the next pane horizontally. If on the last pane, select the first one.
		"""
		p = self.pane + 1
		if p >= len(self.visible):
			p = 0
		self.focus(self.switch_pane(p))

	@staticmethod
	@functools.lru_cache(8)
	def event_method(target, event):
		return 'event_' + '_'.join(event)

	def process(self, keys, trap = keyboard.trap.event, list = list):
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
				# prompt or status
				pi = None

			# 
			trapped = trap(k)
			if trapped is not None:
				(target_id, event_selection, params) = trapped
				method_name = self.event_method(target_id, event_selection)
				method = getattr(self, method_name)

				result = method(k, *params)
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
			if x in self.visible and x is self.projection:
				s = self.clear_position_indicators(x) + self.set_position_indicators(x)
				self.emit((s,))
			x.movement = False
			self.motion.discard(x)

		for x in tuple(self.refreshing):
			if x.pane is not None and x in self.visible:
				events.extend(projection.refresh())
			x.scrolling = False
			self.refreshing.discard(x)

		self.emit(events)

	def get_display_dimensions(self):
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