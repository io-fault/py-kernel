"""
Field entry management package.
"""
import abc
import operator
import keyword
import itertools

class Field(metaclass = abc.ABCMeta):
	"""
	Protocol for Field types.
	"""

	@property
	@abc.abstractmethod
	def empty(self):
		"""
		Designates that the Field contains no content.
		"""

	@property
	@abc.abstractmethod
	def full(self):
		"""
		Designates that the field is full and cannot accept inserts.
		"""

	@abc.abstractmethod
	def characters(self):
		"""
		Number of characters [cells] used for *display*.
		"""

	@abc.abstractmethod
	def value(self):
		"""
		The value of the field or structure.
		"""

	@abc.abstractmethod
	def subfields(self):
		"""
		The absolute sequence of fields contained within the Field.
		Nested fields must be unnested by including the Field context. 

		Returns an iterator producing a triple:
		
			(path, relative_offset, field)

		Where path is a tuple containing the sequence of containing fields
		and the corresponding index:

			(index, field), ...
		"""

	@abc.abstractmethod
	def count(self):
		"""
		Number of subfields contained by the field.
		&None if the field is not a container.
		"""

def changelength(delta):
	"""
	Calculate the length of a delta.
	"""
	l = 0
	for x in delta:
		if x[0] == 'delete':
			start, stop = x[1]
			l -= (stop - start)
		if x[0] == 'insert':
			l += len(x[1][-1])
	return l

def address(seq, start, stop, len = len, range = range):
	"""
	Find the address of the absolute slice.
	"""
	start = start or 0
	assert start <= stop
	assert start >= 0
	assert stop >= 0

	sl = len(seq)

	start_index = 0
	position = 0

	# find start
	for i in range(0, sl):
		ilen = len(seq[i])
		position += ilen
		if position >= start:
			# found the position
			start_index = i
			start_index_offset = position - ilen
			break
	else:
		# request beyond the text length
		return ((sl, 0), (sl, 0))
	start_roffset = start - start_index_offset

	# find stop
	position = start_index_offset
	for i in range(start_index, sl):
		ilen = len(seq[i])
		position += ilen
		if position >= stop:
			# found the position
			stop_index = i
			stop_index_offset = position - ilen
			break
	else:
		# stop offset exceeds total length
		stop_index_offset = position # total string length
		stop_index = sl - 1 # end of sequence

	stop_roffset = stop - stop_index_offset

	# compound slice
	return (
		(start_index, start_roffset),
		(stop_index, stop_roffset),
	)

def delete(seq, start, stop, empty = "", len = len, range = range):
	starts, stops = address(seq, start, stop)
	start_index, start_roffset = starts
	stop_index, stop_roffset = stops

	sl = len(seq)

	if start_index == stop_index:
		# removing a substring
		s = seq[start_index]
		# overwrite the index
		seq[start_index] = s[:start_roffset] + s[stop_roffset:]
	else:
		s = seq[start_index]
		seq[start_index] = s[:start_roffset]

		if stop_index < sl:
			# assign stop as well given its inside the seq
			s = seq[stop_index]
			seq[stop_index] = s[stop_roffset:]

		# clear everything between start+1 and stop
		for i in range(start_index+1, stop_index):
			seq[i] = empty

	return seq

def insert(seq, offset, insertion, empty = "", len = len):
	if not insertion:
		return seq

	if offset <= 0:
		# prepend
		if seq and seq[0] == empty:
			seq[0] = insertion
		else:
			seq.insert(0, insertion)
		return seq

	sl = len(seq)

	position = 0
	for i in range(0, sl):
		# scan for the item that contains the offset
		ilen = len(seq[i])
		position += ilen
		if position > offset:
			break
	else:
		# appending
		if seq and seq[-1] == empty:
			seq[-1] = insertion
		else:
			seq.append(insertion)
		return seq

	roffset = offset - (position - ilen)

	if roffset == 0 and seq[i-1] == empty:
		# empty string at position
		# substitute and continue
		seq[i-1] = insertion
		return seq

	# not prepending or appending, so split the sequence and the middle element if any
	# prefix and suffix at position
	suffix = seq[i:]

	if not suffix:
		# empty suffix
		seq.append(insertion)
		return seq

	prefix = seq[:i]

	if roffset == 0:
		# very beginning of suffix, so append to prefix
		prefix.append(insertion)
		prefix.extend(suffix)
	else:
		# roffset > 0, so split suffix[0]

		prefix.append(suffix[0][:roffset])
		prefix.append(insertion)
		suffix[0] = suffix[0][roffset:]

		prefix.extend(suffix)

	return prefix

operations = {
	'insert': insert,
	'delete': delete,
}

class Segments(object):
	"""
	Manage a series of sequences as if it were one sequence.
	Primarily used to control maximum memory moves for each insertion.
	"""
	__slots__ = ('sequences','length')
	Type = list
	segment_size = 64

	def __init__(self, iterable = None):
		if iterable:
			self.partition(iterable)
		else:
			self.sequences = self.Type()
			self.length = 0

	def __getitem__(self, item):
		if isinstance(item, slice):
			start = item.start or 0
			stop = len(self) if item.stop is None else item.stop
			return list(self.select(start, stop))
		else:
			start, stop = item, item+1
			for x in self.select(start, stop):
				return x

	def __setitem__(self, item, value):
		if isinstance(item, slice):
			start = item.start or 0
			stop = len(self) if item.stop is None else item.stop
			if (stop - start) > 0:
				self.delete(start, stop)
			self.insert(start, value)
		else:
			start, stop = item, item+1
			saddress = address(self.sequences, start, stop)
			self.sequences[start[0]][start[1]] = value

	def __delitem__(self, item):
		if isinstance(item, slice):
			start = item.start or 0
			stop = len(self) if item.stop is None else item.stop
		else:
			start, stop = item, item+1
		self.delete(start, stop)

	def __len__(self):
		return sum(map(len, self.sequences))

	def __iadd__(self, sequence):
		append(self.sequences, sequence)

	def select(self, start, stop, whole = slice(None)):
		"""
		Return an iterator to the requested slice.
		"""
		start, stop = address(self.sequences, start, stop)

		n = stop[0] - start[0]
		if not n:
			# same sequence; simple slice
			if self.sequences and start[0] < len(self.sequences):
				return iter(self.sequences[start[0]][start[1] : stop[1]])
			else:
				# empty
				return iter(())

		slices = [(start[0], slice(start[1], None))]
		slices.extend([(x, whole) for x in range(start[0]+1, stop[0])])
		slices.append((stop[0], slice(0, stop[1])))

		return itertools.chain.from_iterable([
			iter(self.sequences[p][pslice]) for p, pslice in slices
		])

	def __iter__(self):
		return itertools.chain.from_iterable(iter(x) for x in self.sequences)

	def clear(self):
		"""
		Truncate the entire sequence.
		"""
		self.__init__()

	def partition(self, iterable = None):
		"""
		Organize the segments so that they have appropriate sizes.
		"""
		sequences = list()
		segment = None

		if iterable is None:
			this = iter(self)
		else:
			this = iter(iterable)

		while True:
			buf = self.Type(itertools.islice(this, self.segment_size))
			sequences.append(buf)
			if len(buf) < self.segment_size:
				break
		self.sequences = sequences

	def prepend(self, sequence):
		self.sequences = prepend(self.sequences, sequence)

	def append(self, sequence):
		offset = len(self)
		newlen = len(sequence)
		self.sequences.append(sequence)
		return ('delete', (offset, offset+newlen))

	def insert(self, offset, sequence):
		self.sequences = insert(self.sequences, offset, sequence)

	def delete(self, start, stop):
		# normalize and restrict slice size as needed.
		l = len(self)
		stop = max(stop, 0)
		start = max(start, 0)
		if stop > l:
			stop = l
		if start > l:
			start = l
		if start > stop:
			l = start
			start = stop
			stop = l

		delete(self.sequences, start, stop)

	def replace(self, start, stop, sequence):
		"""
		Replace the range with the given sequence.
		"""
		self.sequences = replace(self.sequences, start, stop, sequence)
		seq = delete(self.sequences, start, stop)
		self.sequences = seq.insert(start, sequence)

@Field.register
class String(str):
	"""
	A simple string field. The contents are immutable and it identifies itself as full.
	"""
	__slots__ = ()

	def __getitem__(self, args):
		return self.__class__(super().__getitem__(args))

	@property
	def empty(self):
		return self == ""

	@property
	def full(self):
		return True

	def count(self):
		return None

	def delete(self, start, stop):
		return 0

	def insert(self, position, string):
		return None

	def value(self):
		return self

	def length(self):
		return len(self)

	def divide(self, offset):
		return (self.__class__(self[:offset]), self.__class__(self[offset:]))

class Constant(String):
	pass

@Field.register
class Text(object):
	"""
	Mutable text object using manipulation instructions
	and checkpoints to represent a single string.
	"""
	__slots__ = ('sequences',)
	empty_entry = String("")
	segment_size = 128 # normalized  string size in checkpoint
	delimiters = ()

	@property
	def empty(self):
		return len(self) == 0

	@property
	def full(self):
		'Whether or not more characters can be inserted.'
		if self.limit is None:
			return False
		return len(self) < self.limit

	def characters(self):
		return self.__len__()

	def __init__(self, string = String("")):
		self.sequences = [string]

	@classmethod
	def from_sequence(Class, sequence):
		r = Class.__new__(Class)
		r.sequences = sequence
		return r

	def apply(self, operations):
		"""
		Apply a series of operations to the Text field.
		"""
		pass

	def set(self, characters):
		"""
		Set the field characters. Used loading fields.
		Destroys the log (delta sequence).
		"""
		self.sequences = characters

	def clear(self):
		"""
		Set the text to an empty string.
		"""
		self.set([self.empty_entry])

	def insert(self, offset, string, op = insert):
		self.sequences = op(self.sequences, offset, string, empty = self.empty_entry)
		#address(self.sequences, offset)
		return ('delete', (offset, offset + len(string)))

	def delete(self, start, stop):
		# normalize and restrict slice size as needed.
		l = len(self)
		stop = max(stop, 0)
		start = max(start, 0)
		if stop > l:
			stop = l
		if start > l:
			start = l
		if start > stop:
			l = start
			start = stop
			stop = l

		section = str(self)[start:stop] # TODO: keep exact changes

		self.sequences = delete(self.sequences, start, stop, empty = self.empty_entry)
		return ('insert', (start, section))

	def replace(self, start, stop, string):
		di = self.delete(start, stop)
		ii = self.insert(start, string)
		return [di, ii]

	def __iadd__(self, string):
		self.mutate(('append', string))

	def __len__(self):
		return sum(map(len, self.sequences))
	length = __len__

	def count(self):
		return len(self.sequences)

	def value(self):
		return ''.join(self.sequences)

	def subfields(self, path = ()):
		return zip(((self, i) for i in range(len(self.sequences))), self.sequences)

	def __str__(self):
		return self.value()

	def __repr__(self):
		return repr(self.sequences)

class Line(Text):
	pass

class FieldSeparator(Constant):
	"""
	A space-like character used to delimit fields for commands.

	Primarily used by Prompts to distinguish between spaces and field separation.
	"""
	pass

@Field.register
class Formatting(int):
	"""
	A field that represents a sequence of tabs.
	Cannot be used inside &Text fields.
	"""
	__slots__ = ()
	character = ''
	identity = 'empty'
	size = 0

	@property
	def empty(self):
		return self.length() == 0

	@property
	def full(self):
		return True

	def characters(self):
		return self * self.size

	def count(self):
		return None

	def insert(self, *args):
		return None

	def delete(self, *args):
		return None

	def __str__(self):
		return self.character * (self * self.size)

	def __len__(self):
		return self.size * self

	def value(self):
		return (self.identity, self)

	def length(self):
		return self * self.size

class Spacing(Formatting):
	"""
	A field that represents a series of spaces.
	"""
	__slots__ = ()
	character = ' '
	identity = 'space'
	size = 1

class Indentation(Formatting):
	"""
	A field that represents a series of tabs.
	"""
	__slots__ = ()
	character = '\t'
	identity = 'tab'
	size = 4

class Terminator(Formatting):
	"""
	A field that represents a newline.
	"""
	__slots__ = ()
	character = '\n'
	identity = 'newline'
	size = 1

@Field.register
class Sequence(list):
	__slots__ = ()

	@property
	def empty(self):
		'Whether the sequence contains non-empty fields.'
		for x in self:
			if not x.empty:
				return False
		return True

	def count(self):
		"""
		The number of fields immediately contained.
		"""
		return len(self)

	def prefix(self, *fields):
		self[0:0] = fields

	def suffix(self, *fields):
		self.extend(fields)

	def insert(self, position, *fields):
		self[position:position] = fields
		return (self.deletion, fields)

	def insertion(self, seq):
		sinsert = super().insert
		for p, f in seq:
			sinsert(p, f)

		return (self.deletion, [x[1] for x in seq])

	def delete(self, *fields, get0 = operator.itemgetter(0)):
		"""
		Delete a set of fields from the sequence.
		"""
		indexes = list(map(self.index, fields))
		index_fields = list(zip(indexes, fields))
		index_fields.sort(key = get0)

		for i, f in reversed(index_fields):
			del self[i]

		return (self.insertion, index_fields)

	def clear(self):
		inverse = (self.extend, self[:])
		super().clear()
		return inverse

	def __str__(self):
		return ''.join(str(x[0]) for x in self.value())

	def length(self, len = operator.methodcaller('length')):
		"""
		The sum of the *display* length of the contained fields.
		"""
		return sum(map(len, self))

	def subfields(self, path = (), range = range, len = len, isinstance = isinstance):
		"""
		Map the nested sequences into a serialized form.

		The tuples produced are pairs containing the field and path to the field.
		The path being the sequence of sequences containing the field.
		"""
		if self in path:
			# recursive
			raise Exception('recursive fields')

		for i in range(len(self)):
			x = self[i]
			if isinstance(x, (self.__class__, Text)):
				yield from x.subfields(path + ((self, i),))
			else:
				yield (path + ((self, i),), x)
	value = subfields

	def offset(self, path, field):
		"""
		Get the horizontal positioning of the field within the unit.
		"""
		offset = 0

		for upath, ufield in self.subfields():
			if ufield == field and upath == path:
				# found the filed
				break
			offset += ufield.length()
		else:
			return None

		return offset

	def find(self, offset, state = None):
		"""
		Find the field at the relative offset.

		If the offset is beyond the end of the sequence,
		the last item will be returned.
		If the offset is less than zero, the first.
		"""
		if self.empty:
			return ((), self, (0, 0, ()))

		path = None
		field = None

		if state is None:
			i = iter(self.subfields())
			current = 0
			l = 0
		else:
			current, l, i = state
			current += l

		for path, field in i:
			l = field.length()
			if offset - l < current:
				return (path, field, (current, l, i))
			current += l

		# offset is beyond edge, so select last
		return None

space = Constant(" ")
translation_set = (
	'terminators',
	'routers',
	'delimiters',
	'operators',
	'groupings',
	'quotations',
)

# cover python
python = {
	'keywords': {
		x: Constant(x) for x in keyword.kwlist
	},
	'cores': {
		x: Constant(x) for x in __builtins__.keys()
	},

	'terminators': {
		x: Constant(x) for x in ":;"
	},
	'routers': {
		x: Constant(x) for x in "."
	},
	'delimiters': {
		x: Constant(x) for x in ","
	},
	'operators': {
		x: Constant(x) for x in "@!&^*%+=-|\\/<>?~"
	},
	'groupings': {
		x: Constant(x) for x in "()[]{}"
	},
	'quotations': {
		x: Constant(x) for x in (
			"'",
			'"',
		)
	},
}

def table(language):
	for x in translation_set:
		yield from python[x].keys()

def aggregate(language):
	for x in translation_set:
		yield from python[x].items()

pd = {x:' ' for x in table(python)}
pd['\n'] = None # implied with display

python['table'] = str.maketrans(pd)
del pd
python['constants'] = dict(aggregate(python))
python['classify'] = {}

def parse(line, context = None, language = python, Indentation = Indentation):
	"""
	Parse a line of Python text into Fields.
	"""
	kws = language['keywords']
	cores = language['cores']

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
			*t, edge = x.translate(language['table']).split(' ')
			for y in t:
				if y:
					if y in kws:
						# constant keyword
						yield kws[y]
					elif x in cores:
						yield cores[y]
					else:
						yield y

				# handle following delimiter
				offset += len(y)
				yield language['constants'][xline[offset]]
				offset += 1

			# last field; no delimiter
			if edge:
				yield edge
			offset += len(edge)
		offset += 1 # space

		if offset < l:
			yield space
	# include line terminator
	#yield Terminator(1)

def indentation(seq):
	'Return the indentation level or zero if none.'
	if seq is None:
		return None

	if not seq.empty:
		if isinstance(seq[0], Indentation):
			return seq[0]
	return Indentation(0)

def has_content(line):
	'Whether or not the non-formatting fields have content.'
	for path, x in line.subfields():
		if isinstance(x, Formatting):
			continue
		if x.length() > 0:
			return True
	return False

def block(sequence, index, minimum, maximum, condition_constructor, *parameters):
	"""
	Identify the range where the given condition remains true.
	"""
	l = []
	start, pos, stop = index # position is reference point

	ranges = ((-1, minimum, range(start, minimum-1, -1)), (1, maximum, range(stop, maximum)))

	for direction, default, r in ranges:
		condition = condition_constructor(direction, sequence[pos], *parameters)
		r = iter(r)

		for i in r:
			offset = condition(sequence[i])
			if offset is not None:
				l.append(i - (offset * direction))
				break
		else:
			l.append(default)
			continue

	return tuple(l)

def indentation_block(direction, initial, level = None, level_adjustment = 0):
	"""
	Detect indentation blocks.
	"""

	# if there's no indentation and it's not empty, check contiguous lines
	# if there is indentation or
	if level is None:
		il = indentation(initial)

		if initial is None:
			def true(*args):
				return 0
			return true
	else:
		il = level

	if il:
		ilevel = il + level_adjustment

		def indentation_condition(item, ilevel=ilevel, cstate=list((0,))):
			iil = indentation(item)

			if iil < ilevel and has_content(item):
				# non-empty decrease in indentation
				return 1

			return None

		return indentation_condition
	else:
		# zero indentation level, scan contiguous
		def contiguous_condition(item):
			if indentation(item) == 0 and has_content(item):
				return None
			return 0

		return contiguous_condition

def contiguous_block(direction, initial, level = None, level_adjustment = 0):
	"""
	Detect a contiguous block at the designated indentation level.
	If the initial item is empty, the adjacent empty items will be selected,
	if the initial item is not empty, only populated items will be selected.
	"""
	if level is None:
		il = indentation(initial)
	else:
		il = Indentation(level)

	if has_content(initial):
		def contiguous_content(item, ilevel = il + level_adjustment):
			if indentation(item) != il or not has_content(item):
				# the item was empty or the indentation didn't match
				return 1
			return None
		return contiguous_content
	else:
		def contiguous_empty(item, ilevel = il + level_adjustment):
			if indentation(item) != il or has_content(item):
				# the item was empty or the indentation didn't match
				return 1
			return None
		return contiguous_empty
