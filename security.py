"""
Transformer access to security layers.

Includes support for TLS 1.2, 1.1, and 1.0 using OpenSSL.

"""

import functools

from . import core
from ..cryptography import openssl

class Transport(core.Transformer):

	@staticmethod
	def input(transport):
		return (transport.write_enciphered, transport.read_deciphered)

	@staticmethod
	def output(transport):
		return (transport.write_deciphered, transport.read_enciphered)

	def __init__(self, transport, polarity):
		self.transport = transport
		self.emission = None
		self.polarity = polarity

	@property
	def emit(self):
		return self.emission

	@emit.setter
	def emit(self, val):
		self.emission = val

		if self.polarity == 1:
			pair = self.input()
		else:
			pair = self.output()

		self.transition = functools.partial(transport, val, *pair)

	def coordinate(self, output):
		"Coordinate the input side (&self) with the output side (&output)."

		self.xget = output.get
		self.xput = output.put

	def opposite(self):
		"Inject events into the opposite Flow of the connection."

		pass

	@staticmethod
	def transition(transport, emit, put, get, events, alloc=functools.partial(bytearray,1024*4)):
		mv = memoryview

		for x in events:
			put(x) # put data into openssl BIO

		emits = []
		add = emits.append

		xb = alloc()
		size = get(xb)

		while size: # XXX: compare to buffer size
			add(mv(xb)[:size])
			xb = alloc()
			size = get(xb)

		emit(emits)

	def process(self, events):

		self.transition(events, self.emit, self.put, self.get)

class Context(object):
	"""
	Secure input or output using given @security_state.
	"""

	def __init__(self, context):
		self.context = context

