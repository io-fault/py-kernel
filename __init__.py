"""
Hierarchically structured, asynchronous I/O framework for building applications and servers in Python.

&..io is heavily modelled after UNIX's process structure. &.library.Processor instances represent
concepts similar to processes and &.library.Flow instances represent unidirectional file descriptors
*with* associated transformations.

[ Daemon Manager ]

faultd manages a set of processes and exclusive commands. The invocation parameters and
environment are defined by XML files stored inside directories inside the
(system:environment)`FAULTD_DIRECTORY` path or the user's (system:directory)`~/.faultd`.

XML is used to provide access to the configuration's structure and to allow command based
manipulations for control.

The daemon manager is primarily designed for &.bin.sectord based applications for
services, but it can easily manage arbitrary daemons as well.

[ HTTP ]

The &.libhttp module provides classes for managing HTTP clients and servers. HTTP servers
are implemented as a &.bin.sectord process.

[ SMTP ]

Not implemented.

[ Executables ]

/&.bin.control
	Control a faultd instance and manage its configuration.
/&.bin.service
	Manage the configuration of a faultd instance that is not running.
/&.bin.rootd
	Start faultd.
/&.bin.cache
	Fetch an HTTP resource and store it in the current working directory using the
	resource's name.
/&.bin.sectord
	Manage a &..io based application launched by &.bin.rootd. Direct invocation is possible
	given appropriate configuration of the executing environment.
"""
__factor_type__ = 'project'
