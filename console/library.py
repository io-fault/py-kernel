import sys
import os
import queue
import functools
import locale
import codecs
import keyword
import itertools
import weakref

from ...chronometry import library as timelib
from ...filesystem import library as fslib # autosave/session persistence

from ...terminal import library as libterminal # terminal display
from ...terminal import symbols
from ...status import library as libstatus
from ...computation import library as complib

from .. import library as iolib

from . import libfields
from . import libquery
from . import lines as lineslib

from . import core
from . import palette

IRange = core.IRange

contexts = (
	'system', # the operating system 
	'unit', # the program the editor is running in
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

class Session(iolib.Processor):
	"""
	A set of buffers and execution contexts accessed by a Console.

	Session provides a storage abstraction, persistent cache, and retention policy.
	"""

	def __init__(self, route):
		self.route = route
		self.transcript = None
		self.connections = weakref.WeakValueDictionary()
		self.refractions = {}
		self.persistence = None #libfs.Dictionary()

class Fields(core.Refraction):
	"""
	A &fields based refraction that maintains focus and field selection state.
	"""
	separator = libfields.field_separator

	delete_across_units = False
	margin = 8 # number of lines that remains below or above the cursor
	out_of_bounds = libfields.Sequence((libfields.Indentation.acquire(0),))

	@property
	def current_vertical(self):
		'The curent vertical index as a single IRange instance.'
		return IRange((self.vertical_index, self.vertical_index))

	def log(self, message):
		self.context.process.log(message)

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

	def new(self,
		Class = lineslib.profile('text')[0],
		indentation = libfields.Indentation.acquire(0),
		Sequence = libfields.Sequence,
		String = libfields.String
	):
		"""
		Create and return new Field Sequence.
		"""
		return Sequence((indentation, Class(String(""))))

	def open_vertical(self, il, position, quantity, temporary=False, len=len):
		"Create a quantity of new lines at the cursor &position."

		vi = self.vertical_index
		nunits = len(self.units)
		new = min(vi + position, nunits)

		if new < nunits:
			relation = self.units[new][1].__class__
		elif nunits:
			if vi >= nunits:
				relation = self.units[vi-1][1].__class__
			else:
				relation = self.units[vi][1].__class__
		else:
			relation = self.document_line_class

		self.units[new:new] = [self.new(relation, il) for x in range(quantity)]
		start = new

		v = self.vertical
		v.expand(new - v.get(), quantity)
		v.set(start)
		self.vector_last_axis = v

		self.horizontal.configure(il.length(), 0)

		self.clear_horizontal_indicators()
		self.update_unit()
		self.update_window()
		self.display(max(0, new-quantity), None)

		return ((self.truncate_vertical, (new, new+quantity)), IRange((new, new+quantity-1)))

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

	def constrain_horizontal_range(self):
		"Apply the limits of the vertical index to the vector's horizontal range."
		h = self.horizontal
		hmin = self.get_indentation_level().characters()
		h.limit(hmin, self.unit.characters())

	def update_unit(self):
		"Unconditionally update the vertical index and unit without scrolling."

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
		self.constrain_horizontal_range()

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
		"Bind the window to the appropriate edges."
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

		# All lines are being updated.
		self.controller.emit(self.refresh())

	def __init__(self):
		super().__init__()

		self.units = complib.Segments() # the sequence of buffered Fields.

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
		"Log a change for undo-operations."
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
		"Undo the given quantity of *transactions*."
		if not self.past:
			return

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
		"Redo the given quantity of *transactions*."
		if not self.future:
			return

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
		"Alter the vertical and horizontal query to search."
		self.vertical_query = self.horizontal_query = 'pattern'
		self.pattern = pattern
		self.event_navigation_vertical_stop(None)

	def event_delta_undo(self, event, quantity = 1):
		self.undo(quantity)

	def event_delta_redo(self, event, quantity = 1):
		self.redo(quantity)

	def event_delta_map(self, event):
		"Map the the following commands across the vertical range."
		self.distribution = 'vertical'

	def offsets(self, unit, *indexes):
		"Calculate the cell offsets of the given unit."
		u = self.draw(unit)
		libterminal.offsets(u, indexes)

	@staticmethod
	@functools.lru_cache(16)
	def tab(v, size = 4):
		return (' ' * size) * v

	@staticmethod
	@functools.lru_cache(16)
	def visible_tab(v, size = 4):
		return (('-' * (size-1)) + '|') * v

	def comment(self, q, iterator, color = palette.theme['comment']):
		"Draw the comment."

		yield (q.value(), (), color)
		for path, x in iterator:
			yield (x.value(), (), color)

	def quotation(self, q, iterator, color = 0x666666):
		"Draw the quotation."

		yield (q.value(), (), color)
		for path, x in iterator:
			yield (x.value(), (), color)
			if x == q:
				break

	def draw(self, unit,
		Indent=libfields.Indentation,
		Constant=libfields.Constant,
		has_content=libfields.has_content,
		quotation=palette.theme['quotation'],
		isinstance=isinstance,
		len=len, hasattr=hasattr,
		iter=iter, next=next,
	):
		"Draw an individual unit for rendering."

		fs = 0

		if len(unit) > 1:
			uline = unit[1]
			classify = uline.classifications
		else:
			classify = ()
			uline = None

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

			val = str(x)

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
			elif x in uline.quotations:
				yield from self.quotation(x, i)
				continue
			elif val.isdigit() or (val.startswith('0x') and val[2:].isdigit()):
				yield (x.value(), (), quotation)
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
				elif cc == 'exoword':
					color = libterminal.pastels['cyan']
				else:
					color = 0xBBBBBB
			else:
				color = 0xBBBBBB

			yield (x, (), color)
		else:
			# trailing spaces
			if spaces:
				yield ("#" * spaces, ('underline',), 0xaf0000, None)

	# returns the text for the stop, position, and stop indicators.
	def calculate_horizontal_start_indicator(self, empty, text, style, positions):
		return (text or ' ',) + style

	def calculate_horizontal_stop_indicator(self, empty, text, style, positions,
		combining_wedge = symbols.combining['low']['wedge-left'],
	):
		return (text or ' ',) + style

	def calculate_horizontal_position_indicator(self, empty, text, style, positions,
		vc = symbols.combining['right']['vertical-line'],
		fs = symbols.combining['full']['forward-slash'],
		xc = symbols.combining['high']['wedge-right'],
		range_color_palette = palette.range_colors,
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

		if empty:
			color = (0x444444, 0)
		elif positions[1] >= positions[2]:
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
		len=len,
		whole=slice(None,None),
		address=libfields.address,
	):
		"""
		Collect the fragments of the horizontal range from the rendered unit.

		Used to draw the horizontal range background.

		Nearly identical to complib.Segments.select()
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

	def collect_horizontal_positions(self, line, positions,
		len=len, list=list, set=set,
		iter=iter, range=range, tuple=tuple,
	):
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

		slices = [areas[k[0]] for k in positions]
		return slices

	def clear_horizontal_indicators(self, starmap=itertools.starmap, cells=libterminal.cells):
		"Called to clear the horizontal indicators for line switches."
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
		for k, v in self.horizontal_positions.items():
			offset, old = v
			# don't bother if it's inside the range.
			append(shr(offset))
			oldtext = old[2] or ' '
			oldstyle = old[3]
			append(astyle(oldtext, *oldstyle))
			append(shr(-(offset+cells(oldtext))))

		# horizontal selection
		if self.horizontal_range is not None:
			rstart, rstop, (starti, stopi, text) = self.horizontal_range

			append(shr(rstart))
			append(b''.join(starmap(astyle, text)))
			append(shr(-((rstop - rstart) + rstart)))

		self.horizontal_positions.clear()
		self.horizontal_range = None

		self.controller.emit(events)

	def render_horizontal_indicators(
		self, unit, horizontal,
		names=('start', 'position', 'stop'),
		#range_color=0x262626,
		range_color=None,
		starmap=itertools.starmap,
		cells=libterminal.cells,
		offsets=libterminal.offsets,
		list=list, len=len, tuple=tuple, zip=zip
	):
		"Changes the horizontal position indicators."

		window = self.window.horizontal
		area = self.view.area
		shr = area.seek_horizontal_relative
		astyle = area.style

		line = list(self.draw(unit))
		for x in line:
			if len(x[0]) > 0:
				empty = False
				break
		else:
			empty = True

		hs = horizontal
		hr, prefix, suffix = self.collect_horizontal_range(line, hs)

		if self.keyboard.mapping == 'edit':
			range_style = ()
		else:
			range_style = ('underline',)

		if self.horizontal_range != hr:
			if self.horizontal_range is not None:
				rstart, rstop, (starti, stopi, text) = self.horizontal_range

				clear_range = [
					shr(rstart),
					b''.join(starmap(astyle, text)),
					shr(-((rstop - rstart) + rstart)),
				]
			else:
				clear_range = []

			rstart, rstop, text = hr
			rstarto, rstopo = offsets(line, rstart, rstop)
			range_part = [x[:1] + (x[1] + range_style, (x[2] or 0xAAAAAA) + 0x222222, range_color,) for x in text]

			self.horizontal_range = (rstarto, rstopo, hr)

			set_range = [
				shr(rstarto),
				b''.join(starmap(astyle, range_part)),
				shr(-((rstopo - rstarto) + rstarto)),
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
		new_hp = [(names[i], (tuple(offsets(line, x[0]))[0], x,)) for i, x in zip(range(3), hp)]
		# put position at the end
		new_hp.append(new_hp[1])
		del new_hp[1]

		clear_positions = []
		set_positions = []
		for k, (offset, v) in new_hp:

			# clear old posiition if different
			oldoffset, old = self.horizontal_positions.get(k, (None, None))
			if old is not None and old != v:
				if old[:2] != v[:2]:
					# completely new position, clear
					clear_positions.append(shr(oldoffset))
					oldtext = old[2] or ' '
					oldstyle = old[3]
					clear_positions.append(astyle(oldtext, *oldstyle))
					clear_positions.append(shr(-(oldoffset+cells(oldtext))))

			# new indicator
			index, size, text, style = v
			s = self.horizontal_transforms[k](self, empty, text.ljust(size, ' '), style, hs)

			set_positions.append(shr(offset))
			set_positions.append(astyle(*s))
			set_positions.append(shr(-(offset+cells(s[0]))))

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

	def render(self, start, stop,
			len=len, max=max, min=min,
			list=list, range=range, zip=zip,
		):
		"""
		Render the given line range into the terminal view.

		Returns the relative line range to be rendered.
		"""

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

		rstart = start - top
		rstop = stop - top
		relr = range(rstart, rstop)

		seq = self.view.sequence

		# Draw the unit into the Line in the view.
		draw = self.draw
		units = self.units
		for i, ri in zip(r, relr):
			seq[ri].update(list(draw(units[i])))

		return (rstart, rstop)

	def display(self, start, stop, list=list):
		"Send the given line range to the display."

		self.controller.emit(list(self.view.render(*self.render(start, stop))))

	def refresh(self, start=0, list=list):
		origin, top, bottom = self.window.vertical.snapshot()
		ub = len(self.units)
		rl = min(bottom, ub)
		r = range(top + start, rl)
		seq = self.view.sequence

		draw = self.draw
		units = self.units
		for i in r:
			u = units[i]
			seq[i-top].update(list(draw(u)))

		u = self.out_of_bounds
		for i in range(rl, bottom):
			seq[i-top].update(list(self.draw(self.out_of_bounds)))

		return list(self.view.render())

	def insignificant(self, path, field):
		"Determines whether the field as having insignifianct content."
		return isinstance(field, (libfields.Formatting, libfields.Constant)) or str(field) == " "

	def rotate(self, direction, horizontal, unit, sequence, quantity,
			filtered=None, iter=iter
		):
		"""
		Select the next *significant* field, skipping the given quantity.

		The optional &filtered parameter will be given candidate fields
		that can be skipped.
		"""

		start, pos, stop = horizontal.snapshot()
		if direction > 0:
			point = stop
		else:
			point = start
		point = pos

		i = iter(sequence)

		r = unit.find(point)
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

	def event_console_search(self, event):
		console = self.controller
		prompt = console.prompt
		prompt.prepare(libfields.String("search"), libfields.String(""))
		prompt.horizontal.configure(8, 8, 0)
		prompt.event_transition_edit(event)
		console.focus_prompt()
		self.update_horizontal_indicators()

	def event_console_save(self, event):
		console = self.controller
		console.prompt.prepare(libfields.String("write"), libfields.String(self.source))
		console.focus_prompt()

	def event_console_seek_line(self, event):
		console = self.controller
		prompt = console.prompt
		prompt.prepare(libfields.String("seek"), libfields.String(""))
		prompt.event_select_horizontal_line(None)
		prompt.horizontal.move(0, -1)
		prompt.keyboard.set('edit')
		console.focus_prompt()

	def event_field_cut(self, event):
		self.rotate(self.horizontal, sel, self.unit.subfields(), 1)
		sel[-2].delete(sel[-1])

	def truncate_vertical(self, start, stop):
		"Remove a vertical range from the refraction."

		# delete range
		units = self.units[start:stop]
		self.units.delete(start, stop)

		self.display(start, None)

		# handle case where the window extends beyond the document.
		# lines that once had content are now empty, so they need
		# to be cleared if the visible units is less than the view's height.
		nunits = len(self.units)
		vunits = nunits - self.window.vertical.get()
		if vunits < self.view.height:
			# erase any lines not updated beyond the EOF
			v = self.view
			wl = self.window_line(nunits)
			stop = wl + (stop-start)
			v.clear(wl, stop)
			self.controller.emit(list(v.render(wl, stop)))

		self.update_vertical_state()

		return (self.insert_vertical, (start, units))

	def insert_vertical(self, offset, sequence):
		self.units.insert(offset, sequence)
		self.update_unit()
		self.display(offset, None)
		return (self.truncate_vertical, (offset, offset + len(sequence)))

	def translocate_vertical(self, index, units, target, start, stop):
		"Relocate the vertical range to the &target position."
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
		"Relocate the range to the current position."
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

	def event_delta_transpose_vertical(self, event):
		self.clear_horizontal_indicators()
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
		self.checkpoint()

	def event_delta_transpose_horizontal(self, event):
		self.clear_horizontal_indicators()

		axis, dominate, current, range = self.range_queue.popleft()
		if axis == 'vertical':
			return

		# adjustments to position for same line
		adjust = 0

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
				# normalize the range position: s1 comes before s2.
				s1_range, s2_range = s2_range, s1_range

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

			adjust = - ((s1_range[1] - s1_range[0]) - (s2_range[1] - s2_range[0]))
			self.movement = True
			self.display(*ir.exclusive())
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
			self.display(*s1_changelines.exclusive())
			self.display(*s2_changelines.exclusive())

		self.horizontal.configure(adjust + s2_adjust + s2_range[0], s1_range[1] - s1_range[0])
		self.checkpoint()

	def event_delta_transpose(self, event):
		"Relocate the current range with the queued."

		axis = self.last_axis

		if axis == 'vertical':
			self.event_delta_transpose_vertical(event)
		elif axis == 'horizontal':
			self.event_delta_transpose_horizontal(event)
		else:
			pass

	def event_delta_truncate(self, event):
		"Remove the range of the last axis."
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

	def event_select_horizontal_line(self, event, quantity=1):
		"Alter the horizontal range to be the length of the current vertical index."
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

	def event_select_vertical_line(self, event, quantity=1):
		"Alter the vertical range to contain a single line."
		v = self.vertical
		abs = v.get()
		v.configure(abs, 1)
		self.vector_last_axis = v
		self.movement = True

	def event_select_single(self, event):
		"Modify the horizontal range to field beneath the position indicator."
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

	def event_select_series(self, event):
		"Expand the horizontal range to include fields separated by an access, routing, delimiter."
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

	def event_place_stop(self, event):
		a = self.axis
		d, o, m = a.snapshot()
		a.restore((d, o, o))

		self.movement = True

	def event_navigation_move_bol(self, event):
		self.clear_horizontal_indicators()
		offset = self.indentation_adjustments(self.unit)
		self.horizontal.move((-self.horizontal.datum)+offset, 1)

	def event_navigation_move_eol(self, event):
		self.clear_horizontal_indicators()
		offset = self.indentation_adjustments(self.unit)
		self.horizontal.move(offset + self.unit[1].characters(), 0)

	# line [history] forward/backward
	def event_navigation_vertical_forward(self, event, quantity = 1):
		"Move the position to the next line."
		v = self.vertical
		self.clear_horizontal_indicators()
		v.move(quantity)
		self.vector_last_axis = v
		self.update_vertical_state()
		self.movement = True

	def event_navigation_vertical_backward(self, event, quantity = 1):
		"Move the position to the previous line."
		v = self.vertical
		self.clear_horizontal_indicators()
		v.move(-quantity)
		self.vector_last_axis = v
		self.update_vertical_state()
		self.movement = True

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
	def event_window_vertical_forward(self, event, quantity=1, point=None):
		self.clear_horizontal_indicators()
		self.window.vertical.move(quantity)
		self.movement = True
		self.scrolled()

	def event_window_vertical_backward(self, event, quantity=1, point=None):
		self.clear_horizontal_indicators()
		self.window.vertical.move(-quantity)
		self.movement = True
		self.scrolled()

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
					index = str(u[1]).find(self.pattern)
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
				adj = libfields.indentation(u).characters()
				self.horizontal.configure(adj + index, len(self.pattern))
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
				adj = libfields.indentation(u).characters()
				self.horizontal.configure(adj + index, len(self.pattern))
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
		self.movement = True

	# horizontal

	def event_navigation_horizontal_forward(self, event, quantity = 1):
		"""
		Move the selection to the next significant field.
		"""
		h = self.horizontal
		self.vector_last_axis = h
		self.rotate(1, h, self.unit, self.unit.subfields(), quantity)

	def event_navigation_horizontal_backward(self, event, quantity = 1):
		"""
		Move the selection to the previous significant field.
		"""
		h = self.horizontal
		self.vector_last_axis = h
		self.rotate(-1, h, self.unit, reversed(list(self.unit.subfields())), quantity)

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

	def event_navigation_forward_character(self, event, quantity = 1):
		h = self.horizontal
		self.vector_last_axis = h

		h.move(quantity)
		h.limit(0, self.unit.characters())
	event_control_space = event_navigation_forward_character

	def event_navigation_backward_character(self, event, quantity = 1):
		h = self.vector.horizontal
		self.vector_last_axis = h

		h.move(-quantity)
		h.limit(self.get_indentation_level().length(), self.unit.characters())
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
		elif axis == 'vertical':
			# no move is performed, so indicators don't need to be updaed.
			self.vertical.restore((range[0], self.vertical.get(), range[1]+1))
			self.movement = True
		else:
			raise Exception("unknown axis")

	def clear_horizontal_state(self):
		"Zero out the horizontal cursor."
		self.horizontal.configure(0,0,0)

	def clear_vertical_state(self):
		"Zero out the horizontal cursor."
		self.vertical.collapse()
		self.update_vertical_state()

	def get_indentation_level(self):
		"Get the indentation level of the line at the current vertical position."
		return libfields.indentation(self.unit)

	def event_open_behind(self, event, quantity = 1):
		"Open a new vertical behind the current vertical position."
		inverse = self.open_vertical(self.get_indentation_level(), 0, quantity)
		self.log(*inverse)
		self.keyboard.set('edit')
		self.movement = True

	def event_open_ahead(self, event, quantity = 1):
		"Open a new vertical ahead of the current vertical position."

		if len(self.units) == 0:
			return self.event_open_behind(event, quantity)

		inverse = self.open_vertical(self.get_indentation_level(), 1, quantity)
		self.log(*inverse)
		self.keyboard.set('edit')
		self.movement = True

	def event_open_into(self, event):
		"Open a newline between the line at the current position with greater indentation."
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
		self.movement = True

	def event_edit_return(self, event, quantity = 1):
		"Open a newline while in edit mode."
		inverse = self.open_vertical(self.get_indentation_level(), 1, quantity)
		self.log(*inverse)
		self.movement = True

	def event_delta_substitute(self, event):
		"Substitute the contents of the selection."
		h = self.horizontal
		adjustments = self.indentation_adjustments(self.unit)
		start, position, stop = map((-adjustments).__add__, h.snapshot())
		vi = self.vertical_index

		#last_substituted = self.unit[1][start:stop]
		inverse = self.unit[1].delete(start, stop)
		r = IRange.single(vi)
		self.log(inverse, r)

		h.zero()
		self.clear_horizontal_indicators()
		self.display(*r.exclusive())
		self.transition_keyboard('edit')
		self.movement = True

	def event_delta_substitute_previous(self, event):
		"Substitute the horizontal selection with previous substitution later."
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

	def empty(self, unit):
		"Determine whether or not the given unit is empty."
		ul = len(unit)
		if ul == 0:
			return True
		if isinstance(unit[0], libfields.Indentation):
			return ul < 2
		return False

	def insert_characters(self, characters,
		isinstance=isinstance, StringField=libfields.String
	):
		"Insert characters into the focus."
		v = self.vector.vertical
		h = self.vector.horizontal

		text = self.unit[1]

		if isinstance(characters, StringField):
			chars = characters
		else:
			if characters in text.constants:
				chars = text.constants[characters]
			else:
				chars = StringField(characters)

		adjustments = self.indentation_adjustments(self.unit)
		offset = h.get() - adjustments # absolute offset

		u = v.get()
		inverse = text.insert(offset, chars)
		r = IRange.single(u)
		self.log(inverse, r)

		h.expand(h.offset, len(chars))

		self.clear_horizontal_indicators()
		self.display(*r.exclusive())

	def delete_characters(self, quantity):
		v = self.vector.vertical
		h = self.vector.horizontal

		adjustments = self.indentation_adjustments(self.unit)
		offset = h.get() - adjustments

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

	def event_delta_insert_character(self, event):
		"Insert a character at the current cursor position."
		if event.type == 'literal':
			self.insert_characters(event.string)

	def transition_insert_character(self, key):
		"Used as a capture hook to insert literal characters."
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

	def event_delta_delete_tobol(self, event):
		"Delete all characters between the current position and the begining of the line."
		u = self.unit[1]
		adjustments = self.indentation_adjustments(self.unit)
		offset = self.horizontal.get() - adjustments
		inverse = u.delete(0, offset)

		r = IRange.single(self.vertical.get())
		self.log(inverse, r)

		self.clear_horizontal_indicators()
		self.horizontal.set(adjustments)
		self.display(*r.exclusive())

	def event_delta_delete_toeol(self, event):
		"Delete all characters between the current position and the end of the line."

		u = self.unit[1]
		adjustments = self.indentation_adjustments(self.unit)
		offset = self.horizontal.get() - adjustments
		eol = len(u)
		inverse = u.delete(offset, eol)

		r = IRange.single(self.vertical.get())
		self.log(inverse, r)

		self.clear_horizontal_indicators()
		self.display(*r.exclusive())

	def event_delta_delete_backward_adjacent_class(self, event,
			classify=libquery.classify
		):
		"""
		Delete the characters before the position indicator
		until the class changes. Or, delete the previous word.
		"""
		pass

	def event_delta_delete_forward_adjacent_class(self, event,
			classify=libquery.classify
		):
		"Delete the characters after the position until the class changes."
		pass

	def transition_keyboard(self, mode):
		old_mode = self.keyboard.current[0]
		if old_mode == mode:
			return

		self.clear_horizontal_indicators()
		self.keyboard.set(mode)

	def event_transition_control(self, event):
		self.transition_keyboard('control')

	def event_transition_edit(self, event):
		"""
		Transition into edit-mode. If the line does not have an initialized field
		or the currently selected field is a Constant, an empty Text field will be created.
		"""
		self.transition_keyboard('edit')

	def horizontal_selection(self):
		"Get the string of the current horizontal selection."

		h = self.horizontal
		adjustments = self.indentation_adjustments(self.unit)
		start, position, stop = map((-adjustments).__add__, h.snapshot())

		return str(self.unit[1])[start:stop]

	def record_last_edit(self):
		"Record the text of the edit performed."
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

	def event_delta_edit_insert_space(self, event):
		"""
		Insert a constant into the field sequence and
		create a new text field for further editing.
		"""
		self.insert_characters(libfields.Delimiter(' '))

	def event_delta_insert_space(self, event):
		"Insert a literal space."
		self.insert_characterslibfields.Delimiter((' '))

	def event_delta_indent_increment(self, event, quantity = 1):
		if self.distributing and not libfields.has_content(self.unit):
			# ignore indent if the line is empty and deltas are being distributed
			return

		self.clear_horizontal_indicators()
		self.indent(self.unit, quantity)

		r = IRange.single(self.vertical_index)
		self.log((self.indent, (self.unit, -quantity)), r)

		self.display(*r.exclusive())
		self.constrain_horizontal_range()

	def event_delta_indent_decrement(self, event, quantity = 1):
		if self.distributing and not libfields.has_content(self.unit):
			# ignore indent if the line is empty and deltas are being distributed
			return

		self.clear_horizontal_indicators()
		self.indent(self.unit, -quantity)

		r = IRange.single(self.vertical_index)
		self.log((self.indent, (self.unit, quantity)), r)

		self.display(*r.exclusive())
		self.constrain_horizontal_range()

	def event_delta_indent_null(self, event, quantity = None):
		"Remove all indentation from the line."
		il = self.get_indentation_level()
		return self.event_delta_indent_decrement(event, il)

	event_edit_tab = event_delta_indent_increment
	event_edit_shift_tab = event_delta_indent_decrement

	def print_unit(self):
		self.controller.transcript.write(repr(self.unit)+'\n')
		self.controller.transcript.write(repr(self.controller.cache.storage))

	def event_delta_delete_backward(self, event, quantity = 1):
		self.delete_characters(-1*quantity)

	def event_delta_delete_forward(self, event, quantity = 1):
		self.delete_characters(quantity)

	def event_copy(self, event):
		"Copy the range to the default cache entry."
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
		if remainder:
			self.log(self.unit[1].delete(position, position+len(remainder)), r)

		inverse = self.open_vertical(self.get_indentation_level(), 1, 1)
		self.log(*inverse)

		new = self.unit[1]
		nr = IRange.single(self.vertical_index)

		self.log(new.insert(0, remainder), nr)
		new.reformat()

		self.display(self.vertical_index-1, None)
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
		self.movement = True

	def unit_class(self, index, len = len):
		"Get the corresponding line class for the index."

		nunits = len(self.units)
		if nunits and index >= 0 and index < nunits:
			return self.units[index][1].__class__
		else:
			return self.document_line_class

	def event_paste_after(self, event):
		self.paste(self.vertical_index+1)

	def event_paste_before(self, event):
		self.paste(self.vertical_index)

	def event_paste_into(self, event):
		pass

	def seek(self, vertical_index):
		"Go to a specific vertical index."
		v = self.vector.vertical
		d, o, m = v.snapshot()
		self.clear_horizontal_indicators()
		v.restore((d, vertical_index, m))
		self.update_vertical_state()
		self.movement = True

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

	def write(self, index, string, line_separator = '\n', Sequence = libfields.Sequence):
		"Create new lines to write the string into."

		sl = str(string).split(line_separator)
		nl = len(sl)

		Class = self.unit_class(index)
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

	def append(self, string):
		self.write(len(self.units), string)

	def paste(self, index, cache = None):
		typ, s = self.controller.cache.get(cache)
		return self.write(index, s)

	def focus(self):
		super().focus()
		self.update_horizontal_indicators()

	def blur(self):
		super().blur()
		self.clear_horizontal_indicators()

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

class Lines(Fields):
	"Fields based line editor"

	def __init__(self, line_class=lineslib.profile('text')[0]):
		super().__init__()
		self.keyboard.set('control')
		self.source = None
		self.document_line_class = line_class

		initial = self.new(line_class)
		self.units = complib.Segments([initial])
		self.unit = initial
		nunits = len(self.units)
		self.vector.vertical.configure(0, nunits, 0)

	def serialize(self, write, chunk_size = 128, encoding = 'utf-8'):
		"Serialize the Refraction's content into the given &write function."
		size = 0

		for i in range(0, len(self.units), chunk_size):
			cws = self.units.select(i, i+chunk_size)
			c = '\n'.join([''.join(x.value()) for x in cws])
			c = c.encode(encoding)
			write(c)
			write(b'\n')
			size += len(c) + 1

		return size

	def event_edit_return(self, event):
		"Splits the line at the cursor position."
		return self.event_delta_split(event)

import subprocess
class Shell(Lines):
	"Fault Shell"

	def __init__(self):
		super().__init__()

		self.command_history = []
		self.command_history_position = None
		self.current_prompt = 0

	def execute(self, event):
		command = list(self.sequence(self.unit))
		self.command_history.append(command)

		#cname = command[0]
		#result = method(*command[1:])
		sp = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=None)
		stdout, stderr = sp.communicate(timeout=5)
		self.append("")
		if stdout:
			self.append(stdout.decode())

		self.seek(len(self.units)-1)
		self.event_open_ahead(event)
		self.current_prompt = self.vertical.get()
		self.scrolled()

	event_edit_return = execute
	event_control_return = execute

	def event_delta_edit_insert_space(self, event):
		self.insert_characters(self.separator)

	def prepare(self, *fields):
		"""
		Set the command line to a sequence of fields.
		"""
		self.clear_horizontal_indicators()
		l = list(itertools.chain.from_iterable(
			zip(fields, itertools.repeat(self.separator, len(fields)))
		))
		# remove additional field separator
		del l[-1]
		self.unit[1].sequences = l
		self.controller.emit(self.refresh())

class Status(Fields):
	"The status line above the console prompt."

	def __init__(self):
		super().__init__()
		self.units = [
			libfields.Sequence([libfields.String("initialize")])
		]

	def draw(self, unit, getattr=getattr):
		for path, x in unit.subfields():
			yield x.terminal()

	def refraction_changed(self, new):
		"Called when a different refraction has become the focus."
		self.refraction_type = new.__class__

		title = libfields.Styled(
			self.refraction_type.__name__ or "unknown",
			fg = libterminal.pastels['blue']
		)

		self.units = [
			libfields.Sequence([
				title,
				libfields.Styled(": "),
				libfields.Styled(getattr(new, 'source', '<No Source>') or "none"),
			])
		]

		return self.refresh()

class Prompt(Lines):
	"""
	The prompt providing access to the console's command interface.

	This refraction manages the last two lines on the screen and provides
	a globally accessible command interface for managing the content panes.

	The units of a prompt make up the history.
	"""
	margin = 0

	def execute(self, event):
		command = list(self.sequence(self.unit))
		cname = command[0]

		method = getattr(self, 'command_' + cname)
		result = method(*command[1:])
		self.event_open_ahead(event)
		self.window.vertical.move(1)
		self.scrolled()
		self.transition_keyboard('control')
		self.clear_horizontal_indicators()

	event_edit_return = execute
	event_control_return = execute

	def prepare(self, *fields):
		"""
		Set the command line to a sequence of fields.
		"""
		self.clear_horizontal_indicators()
		l = list(itertools.chain.from_iterable(
			zip(fields, itertools.repeat(self.separator, len(fields)))
		))

		# remove additional field separator
		del l[-1]
		self.unit[1].sequences = l
		self.controller.emit(self.refresh())

	def event_delta_edit_insert_space(self, event):
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

	def command_shell(self):
		"Open a new shell in the current focus pane."
		console = self.controller
		new = Shell()
		new.source = "<memory>"
		new.units = complib.Segments([])
		new.requisite(self.controller)
		console.panes.append(new)
		console.display_refraction(console.pane, new)
		console.focus_pane()

	def command_open(self,
		source : 'route',
		type : 'type' = None,
		mechanism : 'type' = 'Lines',
		encoding : 'encoding' = 'utf-8',
	):
		"""
		Open a new refraction using the identified source.

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
		new.units = complib.Segments(i)

		new.subresource(self.controller)
		console.panes.append(new)

		console.display_refraction(console.pane, new)
		console.focus_pane()

	def command_write(self, target : 'path'):
		"""
		Write the value of the current working pane to the given target.
		"""
		console = self.controller

		with open(target, 'w+b') as f:
			p = console.visible[console.pane]
			size = p.serialize(f.write)
			self.controller.transcript.write('Wrote %d bytes to "%s"\n' %(size, target,))
			f.truncate(size)
			f.flush()

		console.focus_pane()

	def command_seek(self, vertical_index : 'whole number'):
		"""
		Move the refraction's vector to a specific vertical index. (Line Number).
		"""
		console = self.controller
		#p = console.refraction
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

		console.event_pane_rotate_refraction(None)
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

class Transcript(core.Refraction):
	"""
	A trivial line buffer. While &Log refractions are usually preferred, a single
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
	now = timelib.now
	escape_state = 0

	# using incremental decoder to handle partial writes.
	state = codecs.getincrementaldecoder('utf-8')('replace')

	chars = ""
	while True:
		data = os.read(tty.fileno(), 1024*2)
		chars += state.decode(data)
		try:
			events = libterminal.construct_character_events(chars)
		except ValueError:
			# read more
			continue

		enqueue(functools.partial(emit, (now(), events)))
		chars = ""

class Console(iolib.Reactor):
	"""
	The application that responds to keyboard input in order to make display changes.

	Console is a complex Transformer that consists of a set of &Refraction's. The
	refractions are associated with panes that make up the total screen.
	"""

	def __init__(self):
		super().__init__()

		self.tty = None
		self.cache = core.Cache() # user cache / clipboard index
		self.cache.allocate(None)
		self.display = libterminal.Display() # used to draw the frame.

		# Session refractions.
		self.session = Session(None) # connected session
		self.transcript = Transcript() # the always available in memory buffer

		# Per-console refractions
		self.status = Status() # the status line
		self.prompt = Prompt() # prompt below status

		self.refreshing = set() # set of panes to be refreshed
		self.motion = set() # set of panes whose position indicators changed

		self.areas = {
			'status': libterminal.Area(),
			'prompt': libterminal.Area(),
			'panes': (libterminal.Area(), libterminal.Area(), libterminal.Area()),
		}

		self.panes = [self.transcript, Lines(), Lines()]
		self.rotation = 0
		self.visible = list(self.panes[:3])

		self.pane = 1 # focus pane (visible)
		self.refraction = self.panes[1] # focus refraction; receives events

	def requisite(self, tty):
		self.tty = tty
		self.dimensions = self.get_display_dimensions()

		self.prompt.connect(libterminal.View(self.areas['prompt']))
		self.status.view = libterminal.View(self.areas['status'])
		for x, a in zip(self.panes, self.areas['panes']):
			x.connect(libterminal.View(a))

	def connect(self, session):
		"""
		Connect the console to the given session.
		"""

		return NotImplemented

	def display_refraction(self, pane, refraction):
		"""
		Display the &refraction on the designated pane index.
		"""
		if refraction in self.visible:
			# already displayed; focus?
			return

		current = self.visible[pane]
		self.emit([self.clear_position_indicators(current)])
		current.conceal()
		current.pane = None
		v = current.view
		current.connect(None)

		self.emit([v.area.clear()])

		self.visible[pane] = refraction
		refraction.pane = pane
		refraction.connect(v)

		if self.refraction is current:
			self.refraction = refraction

		refraction.calibrate(v.area.dimensions)
		refraction.reveal()
		self.emit([self.set_position_indicators(refraction)])
		self.emit(refraction.refresh())

		if False and isinstance(current, Lines):
			# remove hidden empty refractions
			del self.panes[self.panes.index(current)]

	def pane_verticals(self, index):
		"Calculate the vertical offsets of the pane."
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

	def locate_refraction(self, point):
		"Return the refraction that contains the given point."

		x, y = point
		width, height = self.dimensions

		# status and prompt consume the entire horizontal
		if y == height:
			return self.prompt
		elif y == height-1:
			return self.status

		size = width // len(self.visible)
		pane_index = x // size
		po = pane_index * size

		return self.visible[x // size]

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
		yield style(symbols.lines['horizontal'] * self.dimensions[0], textcolor = color)

		# verticals
		seq = symbols.lines['vertical'] + '\n\b'
		top = symbols.lines['vertical'] + '\n\b'
		bottom = symbols.intersections['bottom']
		bottom_left = symbols.corners['bottom-left']
		bottom_right = symbols.corners['bottom-right']
		seq = style((seq * vh) + bottom, textcolor = color, control_map = nomap)

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
		seq = style((seq * vh) + bottom, textcolor = color, control_map = nomap)

		yield seek((width, 0)) + seq
		# corners
		yield seek((width, height - 3)) + style(bottom_right, textcolor = color, control_map = nomap)
		yield seek((0, height - 3)) + style(bottom_left, textcolor = color, control_map = nomap)

	def set_position_indicators(self, refraction,
		colors=(0x008800, 0xF0F000, 0x880000),
		vprecede=symbols.wedges['up'],
		vproceed=symbols.wedges['down'],
		vwedges=(symbols.wedges['right'], symbols.wedges['left']),
		hproceed=symbols.wedges['left'],
		hprecede=symbols.wedges['right'],
		#vwedges=(symbols.lines['vertical'],)*2,
		#hproceed=symbols.lines['vertical'],
		#hprecede=symbols.lines['vertical'],
	):
		events = bytearray()
		verticals = self.pane_verticals(refraction.pane)
		win = refraction.window
		vec = refraction.vector

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
						events += style(pointer, textcolor = color)

			# adjust for horizontal sets
			h_offset += 1 # avoid intersection with vertical
		else:
			hpointer = symbols.wedges['down']
			h_offset = 0
			h_limit = refraction.dimensions[0]

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
				events += style(pointer, textcolor = color)

		# record the setting for subsequent clears
		refraction.snapshot = (vec.snapshot(), win.snapshot())
		return events

	def clear_position_indicators(self, refraction,
		v_line = symbols.lines['vertical'],
		h_line = symbols.lines['horizontal'],
		h_intersection = symbols.intersections['bottom'],
		h_bottom_left = symbols.corners['bottom-left'],
		h_bottom_right = symbols.corners['bottom-right'],
		color = 0x222222
	):
		"Clear the position indicators on the frame."
		events = bytearray()

		if refraction.snapshot is None:
			return events

		seek = self.display.seek
		style = self.display.style

		# (horiz, vert) tuples
		vec, win = refraction.snapshot # stored state

		verticals = self.pane_verticals(refraction.pane)
		v_limit = self.dimensions[1] - 3

		vtop = win[1][1]

		# verticals is None when it's a prompt
		if verticals is not None:
			r = style(v_line, textcolor = color)

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
			events += style(sym, textcolor = color)

		refraction.snapshot = None
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
		inv = self.context.process.invocation
		if 'system' in inv.parameters:
			name = inv.parameters['system'].get('name', None)
			args = inv.parameters['system'].get('arguments', ())
			initdir = inv.parameters['system'].get('directory', None)
		else:
			name = "<not invoked via system>"
			args = ()
			initdir = None

		for x in self.panes:
			x.subresource(self)
		self.status.subresource(self)
		self.prompt.subresource(self)

		initialize = [
			self.display.clear(),
			self.display.caret_hide(),
			self.display.disable_line_wrap(),
			b''.join(self.adjust(self.dimensions)),
			self.display.enable_mouse()
		]

		initialize.extend(self.status.refraction_changed(self.transcript))

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

		initial = \
			("If you cannot do things my way, I'll just have to find another user.\n\n") + \
			("fault.io system console\n\n") + \
			("") + \
			("Terminal must support meta-key in order for console to function properly.\n") + \
			("Terminal.app: Preferences -> Profile -> Keyboard -> Use option as Meta Key\n") + \
			("iTerm2: Preferences -> Profiles -> Keys -> +Esc Radio Buttons\n") + \
			("\nImmediate Exit: Shift-Meta-` (~); Toggle Console Prompt: Meta-`\n") + \
			("Open file using line editor: Meta-o;\n\n") + \
			("Pane Management\n") + \
			(" close: Close the current refraction without saving. (prompt command)\n") + \
			(" Meta-j: Use current pane to display the Next Refraction\n") + \
			(" Meta-k: Use current pane to display the Previous Refraction\n") + \
			("Mouse Support\n") + \
			(" Primary Click: Control and Edit Mode will move cursor.\n") + \
			(" Secondary Click: Opens Contextual Menu when in focus pane; otherwise focuses unfocused pane.\n") + \
			(" Scroll: Scrolls the pane regardless of focus state.\n") + \
			("\nThis refraction is the console's Transcript; the in-memory log of the process.\n\n")

		self.transcript.write(initial)
		self.panes[1].focus()

		for x in args:
			self.prompt.command_open(x)
		self.transcript.write("opened by: " + sys.executable + " " + name + " " + " ".join(args) + "\n")

	def focus(self, refraction):
		"Focus the given refraction, blurring the current. Does nothing if already focused."
		assert refraction in (self.status, self.prompt) or refraction in self.visible

		cp = self.refraction

		if refraction is not self.prompt:
			self.emit(self.status.refraction_changed(refraction))

		cp.blur()
		self.refraction = refraction
		refraction.focus()

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

	def switch_pane(self, pane):
		"""
		Focus the given pane.

		The new focus pane will only receive a &Refraction.focus call iff
		the old pane's refraction is the current receiver, &Console.refraction.
		"""
		if pane == self.pane:
			return

		old = self.visible[self.pane]
		new = self.visible[pane]

		if self.refraction is old:
			old.blur()
			self.pane = pane
			self.refraction = new
			new.focus()
			self.emit(self.status.refraction_changed(new))
		else:
			self.pane = pane

		return new

	def event_process_exit(self, event):
		self.context.process.terminate(1)

	def event_toggle_prompt(self, event):
		"""
		Toggle the focusing of the prompt.
		"""
		if self.refraction is self.prompt:
			self.focus_pane()
		else:
			self.focus_prompt()

	def event_prepare_open(self, event):
		prompt = self.prompt
		prompt.prepare(libfields.String("open"), libfields.String(""))
		prompt.event_select_horizontal_line(None)
		prompt.horizontal.move(0, -1)
		prompt.keyboard.set('edit')
		self.focus_prompt()

	def event_pane_rotate_refraction(self, event, direction = 1):
		"""
		Display the next refraction in the current working pane according to
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

			# found a refraction
			break
		else:
			# cycled; all panes visible
			return

		self.rotation = r
		self.display_refraction(pid, p)
		self.focus_pane()

	def event_console_rotate_pane_forward(self, event):
		"""
		Select the next pane horizontally. If on the last pane, select the first one.
		"""
		p = self.pane + 1
		if p >= len(self.visible):
			p = 0
		self.focus(self.switch_pane(p))

	def event_console_rotate_pane_backward(self, event):
		"""
		Select the previous pane horizontally. If on the first pane, select the last one.
		"""
		p = self.pane - 1
		if p < 0:
			p = len(self.visible) - 1 
		self.focus(self.switch_pane(p))

	@staticmethod
	@functools.lru_cache(8)
	def event_method(target, event):
		return 'event_' + '_'.join(event)

	def process(self, event, trap = core.keyboard.trap.event, list=list, tuple=tuple):
		"Process key events received from the device."

		# receives Key() instances and emits display events
		context = self.context
		process = context.process

		effects = list()
		ts, keys = event

		for k in keys:
			# refraction can change from individual keystrokes.
			refraction = self.refraction

			# mouse events may be directed to a different pane
			if k.type == 'mouse':
				# position is a point (pair)
				refraction = self.locate_refraction(k.identity[0])

			# discover if a pane has focus
			if refraction in self.visible:
				pi = self.visible.index(refraction)
			else:
				# prompt or status
				pi = None

			trapped = trap(k)
			if trapped is not None:
				(target_id, event_selection, params) = trapped
				method_name = self.event_method(target_id, event_selection)
				method = getattr(self, method_name)

				result = method(k, *params)
			else:
				# refraction may change during iteration
				result = refraction.key(self, k)
				if result is not None:
					#self.rstack.append(result)
					pass

				if refraction.scrolling:
					self.refreshing.add(refraction)

				if refraction.movement:
					self.motion.add(refraction)

		for x in tuple(self.motion):
			if x is self.refraction:
				if x in self.visible or x is self.prompt:
					s = self.clear_position_indicators(x) + self.set_position_indicators(x)
					self.emit((s,))
			x.movement = False
			self.motion.discard(x)

		for x in tuple(self.refreshing):
			if x.pane is not None and x in self.visible:
				effects.extend(refraction.refresh())
			x.scrolling = False
			self.refreshing.discard(x)

		self.emit(effects)

	def get_display_dimensions(self):
		"""
		Get the current tty dimensions.
		"""
		return libterminal.device.dimensions(self.tty.fileno())

def create(controller):
	"""
	Create a console as a subresource of the given controller.
	Returns the new Sector.
	"""

	# sector representing a set of sessions
	s = iolib.Sector()

	console_flow = iolib.Flow() # terminal input -> console -> terminal output
	console_flow.subresource(unit)

	c = Console()
	tty = open(libterminal.device.path, 'r+b')
	console_flow.requisite(iolib.Parallel(input, (tty,)), c, iolib.Parallel(output, (tty,)))

	console_flow.sequence[1].requisite(tty)
	console_flow.sequence[0].actuate()
	console_flow.sequence[-1].actuate()

	return s

def initialize(unit):
	"""
	Initialize the given unit with a console.

	XXX: deprecating
	"""
	libterminal.restore_at_exit() # cursor will be hidden and raw is enabled

	console_flow = iolib.Flow() # terminal input -> console -> terminal output
	console_flow.subresource(unit)
	unit.place(console_flow, 'console-operation')

	c = Console()
	tty = open(libterminal.device.path, 'r+b')
	console_flow.requisite(iolib.Parallel(input, (tty,)), c, iolib.Parallel(output, (tty,)))

	console_flow.sequence[1].requisite(tty)
	console_flow.sequence[0].actuate()
	console_flow.sequence[-1].actuate()

	unit.place(c, 'console') # the Console() instance
	os.environ['FIO_SYSTEM_CONSOLE'] = str(os.getpid())
	c.actuate()
