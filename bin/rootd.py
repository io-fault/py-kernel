"""
Service management daemon, &.libroot.Set, for &..io based applications.

By default, this executable resolves the root service from the
(system:environment)`FAULT_DAEMON_DIRECTORY` environment variable. A parameter
may be provided to override that setting and the default (system:path)`~/.fault`.

This module is intended for use with system invocation only.

! WARNING:
	If the selected daemon directory does not exist, it will be created
	and initialized for use as a root sector daemon.
"""
import os
import sys
from .. import libservice

if __name__ == '__main__':
	# Root Service Invocation; resolve the hardlink and exec() as sectord.
	params = sys.argv[1:]
	os.environ['PYTHON'] = sys.executable

	r = libservice.identify_route(*params[:1])
	rs = libservice.Service(r, None)
	if not rs.exists():
		libservice.configure_root_service(rs)

	os.environ['SERVICE_NAME'] = 'faultd'
	rs.load()
	rs.execute() # For rootd, the replacement will enter .bin.sectord.

	assert False # Should not reach after execl.
