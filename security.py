"""
&.core.Transports support for PKI based security layer.
"""

import functools

from . import core
from ..cryptography import library as libcrypt

# Asynchronous TLS is fairly complicated when adapted to fault.io Flows.
# The primary issues being termination management where there are
# underlying components that can cause interrupts in the security layer.
# The TLS Transformer should be terminated first independently of the actual Detour.

def operations(transport):
	"""
	Construct the input and output operations for use with a &core.Transports instance.
	"""

	input = (
		transport.decipher, transport.pending_input, transport.pending_output,
	)

	output = (
		transport.encipher, transport.pending_output, transport.pending_input,
	)

	return (input, output)

_public_context = None

def public(certificates=()):
	"""
	Initialize and return a TLS security context for use with the publicly available
	certificates.

	This does *not* consider the system's configured certificates.
	"""

	global _public_context
	if _public_context is None:
		_public_context = libcrypt.pki.Context(certificates=certificates+())

	return _public_context

