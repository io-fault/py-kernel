"""
faultd service storage interface

Configuration manager for initializing service directories.
Deals directly with the file system and should only be used while the fault daemon is not running.

Invoking without arguments displays help to standard error.
"""

import os
import sys
from .. import libservice
from ...routes import library as routeslib

def command_create(srv, *params):
	"Create the service directory and initialize its settings."

	if srv.exists():
		sys.stderr.write("service directory already exists\n")
		raise SystemExit(1)

	srv.create("unspecified")
	srv.enabled = False

	if params:
		type, *command = params
		srv.type = type
		if command:
			exe, *cparams = command
			srv.executable = exe
			srv.parameters = cparams

	srv.store()

def command_void(srv):
	"Remove the service directory and its contents."

	if not srv.exists():
		sys.stderr.write("service directory does not exist\n")
		raise SystemExit(1)

	srv.route.void()

def command_document(srv, *params):
	"Document the service describing its purpose."

	srv.load()
	srv.documentation = ' '.join(params)
	srv.store()

def command_define(srv, *params):
	"Define the executable and its parameters for starting the service."

	exe, *params = params

	srv.load()
	srv.executable = exe
	srv.parameters = params

	if srv.type in ("root", "sectors"):
		srv.libexec(recreate=True)

	srv.store()

def command_enable(srv):
	"Enable the service causing it to be started when faultd is ran."

	srv.load_enabled()
	srv.enabled = True
	srv.store_enabled()

def command_disable(srv):
	"Disable the service; attempts to start afterward will fail unless forced."

	srv.load_enabled()
	srv.enabled = False
	srv.store_enabled()

def command_set_concurrency(srv, level):
	"Number of forks to create when spawning sectord based services."

	srv.load()
	srv.concurrency = int(level)
	srv.store()

def command_environ_add(srv, *pairs):
	"Add the given settings as environment variables. (No equal sign used in assignments)"

	srv.load()
	for k, v in zip(pairs[::2], pairs[1::2]):
		srv.environment[k] = v

	srv.store_invocation()

def command_environ_del(srv, *varnames):
	"Remove the given environment variables from the service."

	srv.load()
	for var in varnames:
		del srv.environment[var]

	srv.store_invocation()

def command_requirement_add(srv, *reqs):
	"Add the given parameters as service requirements (service dependencies)."

	srv.load()
	srv.requirements.extend(reqs)
	srv.store_invocation()

def command_requirement_del(srv, *reqs):
	"Remove the given parameters from the service requirements list."

	srv.load()

	for r in reqs:
		srv.requirements.remove(r)

	srv.store_invocation()

def command_library_add(srv, *reqs):
	"Add the given parameters to the list of libraries; library name-path pairs."

	srv.load()

	for k, v in zip(pairs[::2], pairs[1::2]):
		srv.libraries[k] = v

	srv.store_invocation()

def command_library_del(srv, *reqs):
	"Remove the given parameters from the list of libraries."

	srv.load()

	for r in reqs:
		del srv.libraries[k]

	srv.store_invocation()

def command_interface_add(srv, slot, atype, *binds):
	"Add a set of interface bindings to the selected slot."

	srv.load()
	bind_set = srv.interfaces.setdefault(slot, set())

	for (addr, port) in zip(binds[::2], binds[1::2]):
		bind_set.add((atype, addr, port))

	srv.store()

def command_interface_del(srv, slot, *binds):
	"Remove a set of interface bindings from the selected slot."

	pass

def command_set_type(srv, type):
	"Set the service's type: daemon, command, or sectors."

	srv.load()
	srv.type = type
	srv.store_invocation()

def command_report(srv):
	"Report the service's definition to standard error."

	srv.load()
	name = srv.service

	command = [srv.executable]
	command.extend(srv.parameters)

	docs = srv.documentation
	dist = srv.concurrency
	reqs = ' '.join(srv.requirements)
	envvars = ' '.join(['%s=%r' %(k, v) for k, v in srv.environment.items()])
	dir = srv.route.fullpath

	ifs = ''
	for slot, binds in srv.interfaces.items():
		ifs += slot + '='
		ifs += ' '.join(['[%s]:%s' %(a, p) for t, a, p in binds])

	report = """
		Service: {name}
		Type: {srv.type}
		Enabled: {srv.enabled}
		Concurrency: {dist}
		Directory: {dir}
		Command: {command}
		Requirements: {reqs}
		Environment: {envvars}
		Interfaces: {ifs}
		Documentation:

			{docs}\n\n""".format(**locals())

	sys.stderr.write(report)

def command_execute(srv):
	"For testing, execute the service (using exec) as if it were ran by faultd."

	srv.load()
	params = srv.parameters or ()
	params = (srv.service,) + tuple(params)

	os.environ.update(srv.environment or ())
	os.chdir(srv.route.fullpath)
	os.execl(srv.executable, *params)

	assert False

def command_update(srv):
	"Recreate the hardlink for root and sectors."

	srv.load()

	if srv.type in ("root", "sectors"):
		srv.libexec(recreate=True)

command_synopsis = {
	'create': "type:(sectors|daemon|command) executable [parameters ...]",
	'env-add': "[VARNAME1 VALUE1 VARNAME2 VALUE2 ...]",
	'lib-add': "[LIBRARY_NAME MODULE_PATH ...]",
	'if-add': "interface-slot-name type:(local|ip4|ip6) addr-1 port-1 addr-2 port-2 ..."
}

command_map = {
	'void': command_void,
	'create': command_create,
	'command': command_define,
	'update': command_update,
	'type': command_set_type,
	'concurrency': command_set_concurrency,

	'env-add': command_environ_add,
	'env-del': command_environ_del,

	'req-add': command_requirement_add,
	'req-del': command_requirement_del,

	'lib-add': command_library_add,
	'lib-del': command_library_del,

	'if-add': command_interface_add,
	'if-del': command_interface_del,

	'enable': command_enable,
	'disable': command_disable,

	'document': command_document,
	'execute': command_execute,
	'report': command_report,
}

def menu(route, syn=command_synopsis):
	global command_map

	commands = [
		(cname, cfunc.__doc__, cfunc.__code__.co_firstlineno)
		for cname, cfunc in command_map.items()
	]

	commands.sort(key=lambda x: x[2])

	head = "service [service_name] [command] ...\n\n"

	descr = "Modify the fault services' stored configuration. Modifications\n"
	descr += "apply directly to disk and do not effect "
	descr += "the running process unless reloaded.\n"
	descr += "\nThis should only be used prior starting faultd.\n"
	ctl = __package__ + '.control'
	descr += "Use {0} for interacting with a running faultd instance.\n".format(ctl)

	command_head = "\nCommands:\n\t"

	command_help = '\n\t'.join([
		cname + (' ' if cname in syn else '') + (syn.get(cname, "")) + '\n\t\t' + cdoc
		for cname, cdoc, lineno in commands
	])

	sl = route.subnodes()[0]
	service_head = "\n\nServices [%s][%d]:\n\n\t" %(route.fullpath, len(sl),)
	service_list = '\n\t'.join([x.identity for x in sl]) or '[None]'

	return ''.join([
		head, descr, command_head,
		command_help, service_head,
		service_list, '\n\n'
	])

def main(*args, fiod=None):

	if fiod is None:
		fiod = os.environ.get(libservice.environment)

		if fiod is None:
			# from builtin default
			fiod = libservice.default_route
			dsrc = 'default'
		else:
			# from env
			fiod = routeslib.File.from_absolute(fiod)
			dsrc = 'environment'
	else:
		fiod = routeslib.File.from_absolute(fiod)
		dsrc = 'parameter'

	if not args:
		# show help
		sys.stderr.write(menu(fiod))
		sys.stderr.write('\n')
	else:
		service, *args = args
		if args:
			command, *params = args
		else:
			command = 'report'
			params = args

		si = libservice.Service(fiod, service)
		ci = command_map[command]
		ci(si, *params)

if __name__ == '__main__':
	main(*sys.argv[1:])
