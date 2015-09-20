"""
fault.io Scheduling Daemon

Administrative scheduler for faultd service sets, scheduled provides an alternative to
&at(2) and &cron(2) for the purpose of providing a better interface and better
control over running jobs. Timeout control, exclusive execution, and managed logs are some
of the features provided.

Tasks are the specific commands to run and Executions are running Tasks.
Commands are normally system commands, but they can also be HTTP requests.
"""
import sys
from .. import library
from ...chronometry import library as timelib

class Scheduled(object):
	"""
	API Set bound to a set of Interfaces.
	"""

	def __init__(self):
		pass

def defer(*args):
	print('okay...')

@boot
def main(sector):
	primary_schedule = library.Scheduler()

	# The scheduler blocks the exit of the sector.
	sector.dispatch(primary_schedule)
	primary_schedule.defer(timelib.Measure.of(second=2), defer)
