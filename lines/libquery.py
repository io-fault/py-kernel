pass

class Query(object):
	"""
	Range queries for managing range operations.

	Manages the collection of query operations for selecting ranges.
	"""
	def __init__(self, type, scanner, condition):
		self.type = type
		self.scanner = scanner
		self.condition = condition
		self.state = None
		self.paramters = ()

	def dispatch(self, sequence, index, minimum, maximum):
		"""
		Identify the range where the given conditions hold True.
		"""
		l = []
		start, pos, stop = index # position is reference point

		ranges = ((-1, minimum, range(start, minimum-1, -1)), (1, maximum, range(stop, maximum+1)))

		for direction, default, r in ranges:
			condition = condition_constructor(direction, sequence[pos], *self.parameters)
			if condition is None:
				# all
				l.append(default)
			else:
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

def indentation_block(direction, initial, level = None, level_adjustment = 0):
	"""
	Select indentation block.
	"""
	# if there's no indentation and it's not empty, check contiguous lines
	if level is None:
		il = indentation(initial)
	else:
		il = level

	if il == 0:
		# document-level; that is all units
		return None

	ilevel = il + level_adjustment

	def indentation_condition(item, ilevel=ilevel, cstate=list((0,None))):
		iil = indentation(item)

		if iil < ilevel:
			if has_content(item):
				# non-empty decrease in indentation
				return 1 + cstate[0]
			else:
				# track empty line
				cstate[0] += 1
		else:
			if cstate[0]:
				cstate[0] = 0

		return None

	return indentation_condition

def contiguous_block(direction, initial, level = None, level_adjustment = 0):
	"""
	Select a contiguous range.
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
