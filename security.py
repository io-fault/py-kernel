"""
&.library.Transports support for PKI based security layer.

Much of the libio security functionality is structured around conditionally
importing &.security in order to avoid the memory and processing
overhead involved.
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

def system(certificates=()):
	"""
	Initialize and return the system's TLS security context.
	Operating system dependant; some platforms may refer to &public.
	"""
	raise NotImplementedError
