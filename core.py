"""
# Core data types and classes.
"""
import builtins
import operator

class Join(object):
	"""
	# An object whose purpose is to join the completion of multiple
	# processors into a single event. Joins are used to simplify coroutines
	# whose progression depends on a set of processors instead of one.

	# Joins also enable interrupts to trigger completion events so that
	# failures from unrelated Sectors can be communicated to callback.

	# [ Properties ]

	# /dependencies/
		# The original set of processors as a dictionary mapping
		# given names to the corresponding &Processor.

	# /pending/
		# The current state of pending exits that must
		# occur prior to the join-operation's completion.

	# /callback/
		# The callable that is performed after the &pending
		# set has been emptied; defined by &atexit.
	"""

	__slots__ = ('dependencies', 'pending', 'callback')

	def __init__(self, **processors):
		"""
		# Initialize the join with the given &processor set.
		"""

		self.dependencies = processors
		self.pending = set(processors.values())
		self.callback = None

	def connect(self):
		"""
		# Connect the &Processor.atexit calls of the configured
		# &dependencies to the &Join instance.
		"""

		for x in self.dependencies.values():
			x.atexit(self.exited)

		return self

	def __iter__(self, iter=iter):
		"""
		# Return an iterator to the configured dependencies.
		"""

		return iter(self.dependencies.values())

	def __getitem__(self, k):
		"""
		# Get the dependency the given identifier.
		"""

		return self.dependencies[k]

	def exited(self, processor):
		"""
		# Record the exit of the given &processor and execute
		# the &callback of the &Join if the &processor is the last
		# in the configured &pending set.
		"""

		self.pending.discard(processor)

		if not self.pending:
			# join complete
			self.pending = None

			cb = self.callback
			self.callback = None; cb(self) # clear callback to signal completion

	def atexit(self, callback):
		"""
		# Assign the callback of the &Join.

		# If the &pending set is empty, the callback will be immediately executed,
		# otherwise, overwrite the currently configured callback.

		# The &callback is executed with the &Join instance as its sole parameter.

		# [ Parameters ]

		# /callback/
			# The task to perform when all the dependencies have exited.
		"""

		if self.pending is None:
			callback(self)
			return

		self.callback = callback

class Condition(object):
	"""
	# A *reference* to a logical expression or logical function.

	# Conditional references are constructed from a subject object, attribute path, and parameters.
	# Used to clearly describe the objects that participate in a logical conclusion of interest.

	# Used by &Flow instances to describe the condition in which an obstruction is removed.
	# Conditions provide introspecting utilities the capacity to identify the cause of
	# an obstruction.
	"""

	__slots__ = ('focus', 'path', 'parameter')

	def __init__(self, focus, path, parameter = None):
		"""
		# [ Parameters ]
		# /focus/
			# The root object that is safe to reference
		# /path/
			# The sequence of attributes to resolve relative to the &focus.
		# /parameter/
			# Determines the condition is a method and should be given this
			# as its sole parameter. &None indicates that the condition is a property.
		"""
		self.focus = focus
		self.path = path
		self.parameter = parameter

	def __bool__(self):
		condition = self.attribute()

		if self.parameter is not None:
			return condition(self.parameter)
		else:
			# property
			return condition

	def __repr__(self):
		if self is Inexorable:
			return 'Inexorable'

		try:
			attval = self.attribute()
		except:
			attval = '<exception>'

		return "<Condition [%r].%s == %r>" %(
			self.focus, '.'.join(self.path), attval
		)

	def attribute(self, ag=operator.attrgetter):
		return ag('.'.join(self.path))(self.focus)

# A condition that will never be true.
Inexorable = Condition(builtins, ('False',))
