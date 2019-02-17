"""
# Core data types and classes.
"""
import builtins
import operator

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
