import functools
import operator
import collections

from ...terminal import library as libterminal
from .. import library as iolib
from . import keyboard

class Cache(object):
	"""
	Mapping interface for user trans-refraction communication.

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
		"Initialize a cache slot."
		for k in keys:
			if k not in self.storage:
				self.storage[k] = self.Sequence()

	def index(self):
		"Return a sequence of storage slots."
		return self.storage.keys()

	def put(self, key, cobject):
		"Put the given object as the cache entry."
		slot = self.storage[key]
		type, object = cobject
		slot.append((type, object))

		if len(slot) > self.limit:
			slot.popleft()

	def get(self, key, offset = 0):
		"Get the contents of the cache slot."
		r = self.storage[key][-(1 + offset)]

		if r[0] == 'reference':
			r = r[1]()

		return r

	def clear(self, key):
		"Remove the all the contents of the given slot."
		self.storage[key].clear()

class IRange(tuple):
	"Inclusive numeric range used for cases where the range size is one or more."

	__slots__ = ()

	@property
	def direction(self):
		"Returns -1 if the stop is less than the start."
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
		"Create a range consisting of a single unit."
		return Class((index, index))

	def __contains__(self, x):
		"Whether or not the range contains the given number."
		return self[0] <= x <= self[1]

	def relation(self, r):
		pass

	def contiguous(self, r):
		"The given range is coniguous with the other."
		tr = tuple(r)
		return self[0]-1 in tr or self[1]+1 in tr

	def join(self, r):
		"Combine the ranges."
		return self.normal(min(self[0], r[0]), max(self[1], r[1]))

	def exclusive(self):
		"Return as an exclusive-end range pair."
		return (self[0], self[1]+1)

	def units(self, step = 1):
		"Return an iterator to the units in the range."
		if self.direction > 0:
			return range(self[0], self[1]+1, step)
		else:
			return range(self[0], self[1]-1, -step)

class RMapping(object):
	"Range mapping. Mapping of ranges."
	from bisect import bisect

	def __init__(self, combine = operator.methodcaller("__add__")):
		self.ranges = []
		self.association = {}
		self.combine = combine

	def get(self, key):
		index = self.bisect(self.ranges, (key, key))

class Refraction(iolib.Resource):
	"""
	A Refraction of a source onto a connected area of the display.

	Refraction resources are used by Console transformers to manage the parts
	of the display.
	"""

	create_keyboard_mapping = keyboard.Selection.standard
	default_keyboard_mapping = 'edit'

	@property
	def dimensions(self):
		return self.view.area.dimensions

	@property
	def horizontal(self):
		"The current working horizontal position."
		return self.vector.horizontal

	@property
	def vertical(self):
		"The current working vertical position."
		return self.vector.vertical

	@property
	def last_axis(self):
		"The recently used axis."
		if self.vector_last_axis is self.horizontal:
			return 'horizontal'
		else:
			return 'vertical'

	@property
	def axis(self):
		"Return the &libterminal.Position of the last axis used."
		return self.vector_last_axis

	@property
	def keyset(self):
		return self.keyboard.current

	def __init__(self):
		self.movement = False
		self.view = None
		self.area = None
		self.pane = None # pane index of refraction; None if not a pane or hidden

		# keeps track of horizontal positions that are modified for cursor and range display
		self.horizontal_positions = {}
		self.horizontal_range = None

		# Physical location of the refraction.
		self.vector = libterminal.Vector()
		self.vector_last_axis = self.vector.vertical # last used axis
		self.vertical_index = 0 # the focus line

		# View location of the refraction.
		self.window = libterminal.Vector()

		self.range_queue = collections.deque()

		# Recorded snapshot of vector and window.
		# Used by Console to clear outdated cursor positions.
		self.snapshot = None

		self.keyboard = self.create_keyboard_mapping() # per-refraction to maintain state
		self.keyboard.set(self.default_keyboard_mapping)
		self.distributing = False

	@staticmethod
	@functools.lru_cache(16)
	def event_method(target, event):
		return 'event_' + '_'.join(event)

	def route(self, event):
		"Route the event to the target given the current processing state."
		mapping, event = self.keyboard.event(event)
		if event is None:
			# report no such binding
			return None

		return (mapping, event)

	def key(self, console, event, getattr=getattr, range=range):
		"Process the given key event."
		routing = self.route(event)
		if routing is None:
			return ()

		mapping, (target_id, event_selection, params) = routing
		method_name = self.event_method(target_id, event_selection)
		method = getattr(self, method_name)

		if self.distributing and event_selection[0] == 'delta':
			self.clear_horizontal_indicators()
			v = self.vertical
			h = self.horizontal
			vs = v.get()
			v.move(0, 1)
			hs = self.horizontal.snapshot()

			for i in range(v.magnitude):
				h.restore(hs)
				self.update_unit()
				method(event, *params)
				v.move(1)

			v.set(vs)
			rob = None
			self.update_vertical_state()
			if self.distribute_once == True:
				self.distributing = not self.distributing
				self.distribute_once = None
		else:
			rob = method(event, *params)

		if self.controller.refraction is self:
			self.update_horizontal_indicators()

		return rob

	def event_distribute_sequence(self, event):
		self.distributing = not self.distributing
		self.distribute_once = False

	def event_distribute_one(self, event):
		self.distributing = not self.distributing
		self.distribute_once = True

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
		"Called when the refraction is adjusted."
		w = self.window
		w.horizontal.configure(w.horizontal.datum, dimensions[0], 0)
		w.vertical.configure(w.vertical.datum, dimensions[1], 0)

	def conceal(self):
		"Called when the refraction is hidden from the display."
		pass

	def reveal(self):
		"Called when the refraction is revealed. May not be focused."
		pass

	@property
	def revealed(self):
		"Whether the refraction is currently visible."
		return self in self.controller.visible

	def focus(self):
		"Set position indicators and activate cursor."
		console = self.controller
		events = console.set_position_indicators(self)
		console.emit([events])

	@property
	def focused(self):
		"Whether the refraction is the current focus; receives key events."
		return self.controller.refraction is self

	def blur(self):
		"Clear position indicators and lock cursor."
		console = self.controller
		events = console.clear_position_indicators(self)
		console.emit([events])

	def connect(self, view):
		"""
		Connect the area to the refraction for displaying the units.

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
		"Clear the refraction state."
		pass

	def update(self, start, stop, *lines):
		"Render all the display lines in the given ranges."
		pass

	def render(self, start, stop):
		pass

	def refresh(self):
		"Render all lines in the refraction."
		pass
