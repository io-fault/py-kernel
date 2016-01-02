"""
&.library.Transports support for PKI based security layer.
"""

from ..cryptography import library as libcrypt

def operations(transport):
	"""
	Construct the input and output operations for use with a &.library.Transports instance.
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
