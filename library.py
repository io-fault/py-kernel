"""
# Processor class hierarchy for managing explicitly structured processes.
"""
import os
import sys
import collections
import functools
import inspect
import itertools
import traceback
import typing
import codecs

__shortname__ = 'libkernel'

def perspectives(resource, mro=inspect.getmro):
	"""
	# Return the stack of structures used for Resource introspection.

	# Traverses the MRO of the &resource class and executes the &structure
	# method; the corresponding class, properties, and subresources are
	# then appended to a list describing the &Resource from the perspective
	# of each class.

	# Returns `[(Class, properties, subresources), ...]`.
	"""

	l = []
	add = l.append
	covered = set()

	# start generic, and filter replays
	for Class in reversed(inspect.getmro(resource.__class__)[:-1]):
		if not hasattr(Class, 'structure') or Class.structure in covered:
			continue
		covered.add(Class.structure)

		struct = Class.structure(resource)

		if struct is None:
			continue
		else:
			add((Class, struct[0], struct[1]))

	return l

def sequence(identity, resource, perspective, traversed, depth=0):
	"""
	# Convert the structure tree of a &Resource into a sequence of tuples to be
	# formatted for display.
	"""

	if resource in traversed:
		return
	traversed.add(resource)

	yield ('resource', depth, perspective, (identity, resource))

	p = perspectives(resource)

	# Reveal properties.
	depth += 1
	for Class, properties, resources in p:
		if not properties:
			continue

		yield ('properties', depth, Class, properties)

	for Class, properties, resources in p:
		if not resources:
			continue

		for lid, subresource in resources:
			subtraversed = set(traversed)

			yield from sequence(lid, subresource, Class, subtraversed, depth=depth)

def format(identity, resource, sequenced=None, tabs="\t".__mul__):
	"""
	# Format the &Resource tree in fault.text.
	"""
	import pprint

	if sequenced is None:
		sequenced = sequence(identity, resource, None, set())

	for event in sequenced:
		type, depth, perspective, value = event

		if type == 'properties':
			for k, v in value:
				if not isinstance(k, str):
					field = repr(k)
				else:
					field = k

				if isinstance(v, str) and '\n' in v:
					string = v
					# newline triggers property indentation
					lines = string.split('\n')
					pi = tabs(depth+1)
					string = '\n' + pi + ('\n' + pi).join(lines)
				else:
					string = repr(v)
					if len(string) > 32:
						string = pprint.pformat(v, indent=0, compact=True)

				yield '%s%s: %s' %(tabs(depth), field, string)
		else:
			# resource
			lid, resource = value
			rc = resource.__class__
			if '__shortname__' in sys.modules[rc.__module__].__dict__:
				modname = sys.modules[rc.__module__].__shortname__
			else:
				modname = rc.__module__.rsplit('.', 1)[-1]
			rc_id = modname + '.' + rc.__qualname__

			if hasattr(resource, 'actuated'):
				actuated = "->" if resource.actuated else "-"
				if getattr(resource, 'terminating', None):
					terminated = "." if resource.terminating else ""
				else:
					terminated = "|" if resource.terminated else ""
				interrupted = "!" if resource.interrupted else ""
			else:
				actuated = terminated = interrupted = ""

			yield '%s%s%s%s %s [%s]' %(
				tabs(depth),
				actuated, terminated, interrupted,
				lid, rc_id,
			)

def controllers(resource):
	"""
	# Return the stack of controllers of the given &Resource. Excludes initial resource.
	"""

	stack = []
	obj = resource.controller

	while obj is not None:
		add(obj)
		obj = obj.controller

	return stack

class Projection(object):
	"""
	# A set of credentials and identities used by a &Sector to authorize actions by the entity.

	# [ Properties ]

	# /entity/
		# The identity of the user, person, bot, or organization that is being represented.
	# /credentials/
		# The credentials provided to authenticate the user.
	# /role/
		# An effective entity identifier; an override for entity.
	# /authorization/
		# A set of authorization tokens for the systems that are being used by the entity.
	# /device/
		# An identifier for the device that is being used to facilitate the connection.
	"""

	entity = None
	credentials = None
	role = None
	authorization = None
	device = None

	def __init__(self):
		"""
		# Projections are simple data structures and requires no initialization.
		"""

def Encoding(
		transformer,
		encoding:str='utf-8',
		errors:str='surrogateescape',

		gid=codecs.getincrementaldecoder,
		gie=codecs.getincrementalencoder,
	):
	"""
	# Encoding Transformation Generator.
	"""

	emit = transformer.f_emit
	del transformer # don't hold direct reference, only need emit.
	escape_state = 0

	# using incremental decoder to handle partial writes.
	state = gid(encoding)(errors)
	operation = state.decode

	output = None

	input = (yield output)
	output = operation(input)
	while True:
		input = (yield output)
		output = operation(input)
