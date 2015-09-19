"""
Sentry Daemon

sentryd is the monitoring process for a faultd instance and potentially
the system as well.

sentryd manages a set of sentries that monitor a set of information points;
these information points are updated via subscription or polling and the sentry
raises alerts based on the threat function.
"""

import sys
import os
import os.path
import psutil

from ...chronometry import library as timelib

machine_boot = timelib.unix(psutil.boot_time())

def render_profile(hostname = None):
	"""
	Dictionary containing a profile of the platform.
	"""

	import platform
	import resource
	import getpass

	# physical
	machine = {
		'boot': machine_boot,
		'architecture': platform.machine(),
		'cpu': {
			'physical': psutil.cpu_count(logical=False),
			'logical': psutil.cpu_count(),
		},
		'memory': {
			'capacity': psutil.virtual_memory().total
		}
	}

	# kernel
	system = {
		'name': platform.system(),
		'version': platform.release(),
		'network': {
			'hostname': hostname or platform.node(),
			'net': psutil.net_io_counters(True),
		},

		'memory': {
			'pagesize': resource.getpagesize(),
		},

		'user': {
			'shell-level': int(os.environ.get('SHLVL', 0)) - 1,
			'user': getpass.getuser(),
			'home': os.path.expanduser('~'),
		}
	}

	python = {
		'name': 'python',
		'implementation': platform.python_implementation(),
		'version': platform.python_version_tuple(),
		'compiler': platform.python_compiler(),
		'abi': sys.abiflags,
	}

	# versions of fault software
	fault = {
		'version': None,
	}

	del sys.modules['platform']
	del sys.modules['getpass']
	del sys.modules['resource']

	return {
		'machine': machine,
		'system' : system,
		'software': {
			'python': python,
			'fault': fault,
		},
	}

profile = render_profile()

class Sentry(object):
	"""
	API Set bound to a set of Interfaces.
	"""

	def __init__(self):
		pass

@boot
def main(sector):
	print('SENTRY!')
	sys.stderr.flush()

