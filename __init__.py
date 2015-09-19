"""
I/O management framework

fault.io provides a framework for authoring and managing service daemons.
The core provides classes for managing various processing models, but notably
coroutines, flows, and groups (of flow and coroutines).

Protocols: DNS, HTTP (1.1 and 2.0), TLS (fault.cryptography[openssl]), and SMTP.
"""

__pkg_bottom__ = True
